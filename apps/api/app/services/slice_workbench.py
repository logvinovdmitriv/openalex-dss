from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.paths import DATA
from app.services import author_slice, jobs, metadata_store, query_planner, registry, warehouse


SLICES_DIR = DATA / "slices"
MATERIALIZATIONS_DIR = DATA / "materialization_plans"

def list_slices(limit: int = 50) -> dict[str, Any]:
    _ensure_dirs()
    docs = [_read_json(path) for path in sorted(SLICES_DIR.glob("*/slice_definition.json"), reverse=True)]
    docs = [doc for doc in docs if doc]
    return {"slices": docs[: max(1, min(limit, 250))], "total": len(docs), "states": SLICE_STATES}


def create_slice(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure_dirs()
    technical_payload = _technical_payload(payload)
    cfg = author_slice.config_from_payload({**technical_payload, "workflow_mode": "strict_works"})
    now = _now()
    slice_id = _safe_id(str(payload.get("slice_id") or cfg.slice_name or f"slice_{uuid.uuid4().hex[:8]}"))
    doc = {
        "slice_id": slice_id,
        "title": str(payload.get("title") or _slice_title(cfg)),
        "state": "draft",
        "created_at_utc": now,
        "updated_at_utc": now,
        "slice_definition": {
            "subject": {
                "label": cfg.entity_display_name,
                "level": cfg.entity_level,
                "mode": cfg.filter_mode,
            },
            "territory": {
                "country_code": cfg.country_code,
                "institution": cfg.institution_display_name,
            },
            "period": {
                "from": cfg.from_publication_date,
                "to": cfg.to_publication_date,
            },
            "works": {
                "types": [part for part in cfg.work_type.split("|") if part],
                "exclude_retracted": cfg.exclude_retracted,
                "exclude_paratext": cfg.exclude_paratext,
                "include_xpac": cfg.include_xpac,
            },
        },
        "download_policy_default": _download_policy(payload),
        "technical_payload": _public_payload(technical_payload),
        "lifecycle": _lifecycle("draft"),
        "latest_estimate": None,
        "latest_materialization_plan": None,
    }
    _write_slice(doc)
    return doc


def get_slice(slice_id: str) -> dict[str, Any]:
    path = _slice_path(slice_id)
    if not path.exists():
        raise KeyError(slice_id)
    return _read_json(path)


def resolve_slice(slice_id: str) -> dict[str, Any]:
    doc = get_slice(slice_id)
    preview = author_slice.preview(doc["technical_payload"])
    doc["state"] = _advance_state(str(doc.get("state") or "draft"), "resolved")
    doc["updated_at_utc"] = _now()
    doc["resolved_slice"] = {
        "openalex_filter": preview["request"]["filter"],
        "select_fields": preview["request"]["select_fields"],
        "technical_projection": preview["slice"],
        "policy": preview["policy"],
    }
    doc["lifecycle"] = _lifecycle(doc["state"])
    _write_slice(doc)
    return doc


def estimate_slice(slice_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = get_slice(slice_id)
    merged_payload = {
        **doc["technical_payload"],
        "download_policy": _download_policy(payload or {}, fallback=doc.get("download_policy_default")),
        **_technical_payload(payload or {}),
    }
    plan = query_planner.plan_slice(merged_payload)
    estimate = {
        "slice_id": slice_id,
        "status": plan["decision"]["status"],
        "decision": plan["decision"],
        "estimate": plan["estimate"],
        "openalex_filter": plan["openalex_filter"],
        "filter_classes": plan["filter_classes"],
        "download_policy": plan["download_policy"],
        "execution_limits": plan["limits"],
    }
    doc["technical_payload"] = _public_payload(merged_payload)
    doc["state"] = _advance_state(str(doc.get("state") or "draft"), "estimated")
    doc["updated_at_utc"] = _now()
    doc["latest_estimate"] = estimate
    doc["lifecycle"] = _lifecycle(doc["state"])
    _write_slice(doc)
    return estimate


def create_materialization_plan(slice_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = get_slice(slice_id)
    payload = payload or {}
    profile_id = str(payload.get("storage_profile_id") or payload.get("profile_id") or payload.get("materialization_profile") or "minimal_analytics")
    profiles = _storage_profiles()
    profile = profiles.get(profile_id) or next(iter(profiles.values()))
    source_strategy = str(payload.get("source_strategy") or payload.get("data_source_id") or "openalex_cli")
    download_policy = _download_policy(payload, fallback=doc.get("download_policy_default"))
    plan_id = _safe_id(f"mat_{slice_id}_{profile['profile_id']}_{uuid.uuid4().hex[:8]}")
    estimate = doc.get("latest_estimate") or estimate_slice(slice_id, {"download_policy": download_policy})
    materialization = {
        "materialization_id": plan_id,
        "slice_id": slice_id,
        "state": "planned",
        "created_at_utc": _now(),
        "storage_profile": profile,
        "profile": profile,
        "source_strategy": source_strategy,
        "download_policy": download_policy,
        "estimated": estimate,
        "accepted_estimate_signature": (estimate.get("estimate") or {}).get("estimate_signature"),
        "accepted_download_signature": (estimate.get("estimate") or {}).get("download_signature"),
        "technical_payload": {
            **doc["technical_payload"],
            "source_strategy": source_strategy,
            "download_policy": download_policy,
            "accepted_estimate_signature": (estimate.get("estimate") or {}).get("estimate_signature"),
            "accepted_download_signature": (estimate.get("estimate") or {}).get("download_signature"),
        },
        "outputs": [
            "raw/openalex_cli/{slice_id}/works.jsonl.gz",
            "tables/{dump_id}/works.parquet",
            "tables/{dump_id}/authorships.parquet",
            "tables/{dump_id}/work_topics.parquet",
            "runs/{run_id}/tables/author_indices.parquet",
            "runs/{run_id}/passports/slice_passport.json",
        ],
    }
    _write_materialization(materialization)
    doc["state"] = _advance_state(str(doc.get("state") or "estimated"), "planned")
    doc["latest_materialization_plan"] = materialization
    doc["updated_at_utc"] = _now()
    doc["lifecycle"] = _lifecycle(doc["state"])
    _write_slice(doc)
    return materialization


def run_materialization(materialization_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = get_materialization_plan(materialization_id)
    run_payload = {**plan["technical_payload"], **(payload or {})}
    run = jobs.create_run("build_from_openalex", run_payload)
    plan["state"] = "materializing"
    plan["run_id"] = run["run_id"]
    plan["updated_at_utc"] = _now()
    _write_materialization(plan)
    try:
        doc = get_slice(plan["slice_id"])
        doc["state"] = _advance_state(str(doc.get("state") or "planned"), "materializing")
        doc["latest_materialization_plan"] = plan
        doc["updated_at_utc"] = _now()
        doc["lifecycle"] = _lifecycle(doc["state"])
        _write_slice(doc)
    except KeyError:
        pass
    return {"materialization": plan, "run": run}


def get_materialization_plan(materialization_id: str) -> dict[str, Any]:
    path = _materialization_path(materialization_id)
    if not path.exists():
        raise KeyError(materialization_id)
    return _read_json(path)


def list_materialization_plans(limit: int = 50) -> dict[str, Any]:
    _ensure_dirs()
    docs = [_read_json(path) for path in sorted(MATERIALIZATIONS_DIR.glob("*.json"), reverse=True)]
    docs = [doc for doc in docs if doc]
    return {"materializations": docs[: max(1, min(limit, 250))], "profiles": list(_storage_profiles().values())}


def list_dumps(limit: int = 50) -> dict[str, Any]:
    dumps = metadata_store.list_slice_dumps(limit=limit)
    return {"dumps": dumps, "total": len(dumps)}


def mark_materialization_run_completed(run_id: str, result: dict[str, Any]) -> None:
    _ensure_dirs()
    no_data = bool(result.get("no_data"))
    fetch = result.get("fetch") if isinstance(result.get("fetch"), dict) else {}
    dump = fetch.get("dump") if isinstance(fetch.get("dump"), dict) else {}
    build = result.get("build") if isinstance(result.get("build"), dict) else {}
    target_slice_state = "ready" if no_data else ("analyzed" if build else "ready")
    target_materialization_state = "ready" if not no_data else "planned"

    for path in MATERIALIZATIONS_DIR.glob("*.json"):
        plan = _read_json(path)
        if str(plan.get("run_id") or "") != run_id:
            continue
        plan["state"] = target_materialization_state
        plan["updated_at_utc"] = _now()
        if dump:
            plan["dump_manifest"] = dump
            plan["dump_id"] = dump.get("dump_id")
        if build:
            plan["analysis_result"] = build
        _write_materialization(plan)
        try:
            doc = get_slice(str(plan["slice_id"]))
        except KeyError:
            return
        doc["state"] = _advance_state(str(doc.get("state") or "materializing"), target_slice_state)
        doc["latest_materialization_plan"] = plan
        doc["updated_at_utc"] = _now()
        doc["lifecycle"] = _lifecycle(doc["state"])
        _write_slice(doc)
        return


def workbench_summary() -> dict[str, Any]:
    tables = warehouse.list_tables()
    slices = list_slices(limit=20)
    materializations = list_materialization_plans(limit=20)
    dumps = list_dumps(limit=20)
    return {
        "states": SLICE_STATES,
        "slices": slices["slices"],
        "materializations": materializations["materializations"],
        "dumps": dumps["dumps"],
        "tables": tables,
    }


SLICE_STATES = [
    {"id": "draft", "label": "Draft", "description": "Логический срез задан пользователем."},
    {"id": "resolved", "label": "Resolved", "description": "Срез сопоставлен с OpenAlex-проекцией."},
    {"id": "estimated", "label": "Estimated", "description": "Оценены объем и API-бюджет."},
    {"id": "planned", "label": "Planned", "description": "Выбран режим хранения и технический бюджет загрузки."},
    {"id": "materializing", "label": "Materializing", "description": "Идет загрузка или сборка локального набора."},
    {"id": "ready", "label": "Ready", "description": "Мини-дамп и локальные таблицы готовы."},
    {"id": "analyzed", "label": "Analyzed", "description": "Индексы и рейтинги рассчитаны."},
    {"id": "reported", "label": "Reported", "description": "Отчет и паспорта подготовлены."},
]


def _technical_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("technical_payload") if isinstance(payload.get("technical_payload"), dict) else payload
    return {key: value for key, value in raw.items() if key not in {"api_key", "download_policy", "storage_profile_id", "profile_id", "materialization_profile"}}


def _public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "api_key"}


def _download_policy(payload: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = payload.get("download_policy") if isinstance(payload.get("download_policy"), dict) else {}
    default = fallback or {
        "complete_slice_required": True,
        "allow_incomplete_preview": False,
    }
    return {
        "complete_slice_required": bool(raw.get("complete_slice_required", payload.get("complete_slice_required", default.get("complete_slice_required", True)))),
        "allow_incomplete_preview": bool(raw.get("allow_incomplete_preview", payload.get("allow_incomplete_preview", default.get("allow_incomplete_preview", False)))),
        "user_controls_download_after_estimate": True,
    }


def _storage_profiles() -> dict[str, dict[str, Any]]:
    profiles = registry.registry().get("storage_profiles") or []
    out: dict[str, dict[str, Any]] = {}
    for item in profiles:
        profile_id = str(item.get("profile_id") or item.get("value") or "").strip()
        if profile_id:
            out[profile_id] = {**item, "profile_id": profile_id}
    if not out:
        out["minimal_analytics"] = {
            "profile_id": "minimal_analytics",
            "label": "Минимальный состав данных",
            "description": "Базовый профиль хранения из конфигурации не найден.",
            "format": "jsonl.gz + parquet",
            "selected_fields": [],
        }
    return out


def _slice_title(cfg: Any) -> str:
    territory = cfg.institution_display_name or cfg.country_code or "все страны"
    return f"{cfg.entity_display_name} / {territory} / {cfg.from_publication_date[:4]}-{cfg.to_publication_date[:4]}"


def _lifecycle(active: str) -> list[dict[str, Any]]:
    seen = True
    out: list[dict[str, Any]] = []
    for state in reversed(SLICE_STATES):
        if state["id"] == active:
            seen = False
        out.append({**state, "ready": not seen, "active": state["id"] == active})
    return list(reversed(out))


def _advance_state(current: str, target: str) -> str:
    order = [state["id"] for state in SLICE_STATES]
    if current not in order or target not in order:
        return target
    return target if order.index(target) >= order.index(current) else current


def _safe_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return text.strip("_.-")[:140] or f"slice_{uuid.uuid4().hex[:8]}"


def _ensure_dirs() -> None:
    SLICES_DIR.mkdir(parents=True, exist_ok=True)
    MATERIALIZATIONS_DIR.mkdir(parents=True, exist_ok=True)


def _slice_path(slice_id: str) -> Path:
    return SLICES_DIR / _safe_id(slice_id) / "slice_definition.json"


def _materialization_path(materialization_id: str) -> Path:
    return MATERIALIZATIONS_DIR / f"{_safe_id(materialization_id)}.json"


def _write_slice(doc: dict[str, Any]) -> None:
    path = _slice_path(str(doc["slice_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_materialization(doc: dict[str, Any]) -> None:
    path = _materialization_path(str(doc["materialization_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
