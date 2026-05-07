from __future__ import annotations

import json
import re
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.paths import DATA
from app.services.internal_payloads import normalize_internal_pipeline_payload
from app.services import artifact_context, author_slice, jobs, metadata_store, query_planner, registry, warehouse
from openalex_mvp.openalex import cli_download_signature, corpus_request


SLICES_DIR = DATA / "slices"
MATERIALIZATIONS_DIR = DATA / "materialization_plans"

def list_slices(limit: int = 50) -> dict[str, Any]:
    _ensure_dirs()
    docs = [_read_json(path) for path in sorted(SLICES_DIR.glob("*/slice_definition.json"), reverse=True)]
    docs = [doc for doc in docs if doc]
    return {"slices": docs[: max(1, min(limit, 250))], "total": len(docs), "states": SLICE_STATES}


def create_slice(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure_dirs()
    technical_payload = normalize_internal_pipeline_payload(_technical_payload(payload))
    cfg = author_slice.config_from_payload({**technical_payload, "workflow_mode": "strict_works"})
    slice_fingerprint = _slice_fingerprint(cfg)
    slice_id = _slice_id(payload, cfg, slice_fingerprint)
    technical_payload = normalize_internal_pipeline_payload({**technical_payload, "slice_name": slice_id})
    cfg = author_slice.config_from_payload({**technical_payload, "workflow_mode": "strict_works"})
    now = _now()
    doc = {
        "slice_id": slice_id,
        "slice_fingerprint": slice_fingerprint,
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
    merged_payload = normalize_internal_pipeline_payload(
        {
            **doc["technical_payload"],
            "download_policy": _download_policy(payload or {}, fallback=doc.get("download_policy_default")),
            **_technical_payload(payload or {}),
        }
    )
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
    estimate = estimate_slice(slice_id, {"download_policy": download_policy})
    doc = get_slice(slice_id)
    cfg = author_slice.config_from_payload({**doc["technical_payload"], "workflow_mode": "strict_works"})
    materialization_fingerprint = _materialization_fingerprint(
        cfg,
        slice_fingerprint=str(doc.get("slice_fingerprint") or _slice_fingerprint(cfg)),
        source_strategy=source_strategy,
        storage_profile_id=str(profile["profile_id"]),
        download_policy=download_policy,
    )
    technical_payload = normalize_internal_pipeline_payload(
        {
            **doc["technical_payload"],
            "source_strategy": source_strategy,
            "download_policy": download_policy,
            "accepted_estimate_signature": (estimate.get("estimate") or {}).get("estimate_signature"),
            "accepted_download_signature": (estimate.get("estimate") or {}).get("download_signature"),
        }
    )
    materialization = {
        "materialization_id": plan_id,
        "slice_id": slice_id,
        "slice_fingerprint": doc.get("slice_fingerprint"),
        "materialization_fingerprint": materialization_fingerprint,
        "state": "planned",
        "created_at_utc": _now(),
        "storage_profile": profile,
        "profile": profile,
        "source_strategy": source_strategy,
        "download_policy": download_policy,
        "estimated": estimate,
        "accepted_estimate_signature": (estimate.get("estimate") or {}).get("estimate_signature"),
        "accepted_download_signature": (estimate.get("estimate") or {}).get("download_signature"),
        "technical_payload": technical_payload,
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
    run_payload = normalize_internal_pipeline_payload({**plan["technical_payload"], "materialization_id": plan["materialization_id"], **(payload or {})})
    run = jobs.create_run("build_from_openalex", run_payload, autostart=False)
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
    jobs.start_run(run["run_id"])
    return {"materialization": get_materialization_plan(materialization_id), "run": jobs.get_run(run["run_id"])}


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


def mark_materialization_run_completed(run_id: str, result: dict[str, Any], *, materialization_id: str = "") -> None:
    _ensure_dirs()
    fetch = result.get("fetch") if isinstance(result.get("fetch"), dict) else {}
    dump = fetch.get("dump") if isinstance(fetch.get("dump"), dict) else {}
    if not dump and isinstance(result.get("dump"), dict):
        dump = result["dump"]
    no_data = bool(result.get("no_data") or dump.get("no_data"))
    build = result.get("build") if isinstance(result.get("build"), dict) else {}
    target_slice_state = "empty" if no_data else ("analyzed" if build else "ready")
    target_materialization_state = "empty" if no_data else "ready"

    for path in MATERIALIZATIONS_DIR.glob("*.json"):
        plan = _read_json(path)
        if not _matches_materialization_run(plan, run_id, materialization_id):
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


def mark_materialization_run_failed(run_id: str, error: str, *, materialization_id: str = "") -> None:
    _ensure_dirs()
    for path in MATERIALIZATIONS_DIR.glob("*.json"):
        plan = _read_json(path)
        if not _matches_materialization_run(plan, run_id, materialization_id):
            continue
        plan["state"] = "failed"
        plan["updated_at_utc"] = _now()
        plan["error"] = error
        _write_materialization(plan)
        try:
            doc = get_slice(str(plan["slice_id"]))
        except KeyError:
            return
        doc["state"] = "failed"
        doc["latest_materialization_plan"] = plan
        doc["updated_at_utc"] = _now()
        doc["error"] = error
        doc["lifecycle"] = _lifecycle(doc["state"])
        _write_slice(doc)
        return


def workbench_summary() -> dict[str, Any]:
    active_context = artifact_context.read_active_context()
    active_run_id = str(active_context.get("active_run_id") or "").strip()
    active_dump_id = str(active_context.get("active_dump_id") or "").strip()
    tables = (
        warehouse.list_tables(run_id=active_run_id, dump_id=active_dump_id)
        if active_run_id or active_dump_id
        else {}
    )
    slices = list_slices(limit=20)
    materializations = list_materialization_plans(limit=20)
    dumps = list_dumps(limit=20)
    quality = warehouse.read_json_doc("quality") or {}
    return {
        "states": SLICE_STATES,
        "slices": slices["slices"],
        "materializations": materializations["materializations"],
        "dumps": dumps["dumps"],
        "tables": tables,
        "quality": quality,
        "active_context": active_context,
        "workflow": _workbench_workflow(
            tables=tables,
            slices=slices["slices"],
            materializations=materializations["materializations"],
            dumps=dumps["dumps"],
            quality=quality,
            active_context=active_context,
        ),
    }


SLICE_STATES = [
    {"id": "draft", "label": "Draft", "description": "Логический срез задан пользователем."},
    {"id": "resolved", "label": "Resolved", "description": "Срез сопоставлен с OpenAlex-проекцией."},
    {"id": "estimated", "label": "Estimated", "description": "Оценены объем и API-бюджет."},
    {"id": "planned", "label": "Planned", "description": "Выбран режим хранения и технический бюджет загрузки."},
    {"id": "materializing", "label": "Materializing", "description": "Идет загрузка или сборка локального набора."},
    {"id": "empty", "label": "Empty", "description": "OpenAlex вернул пустой корпус для выбранного среза."},
    {"id": "ready", "label": "Ready", "description": "Мини-дамп и локальные таблицы готовы."},
    {"id": "analyzed", "label": "Analyzed", "description": "Индексы и рейтинги рассчитаны."},
    {"id": "reported", "label": "Reported", "description": "Отчет и паспорта подготовлены."},
    {"id": "failed", "label": "Failed", "description": "Загрузка или расчет завершились ошибкой."},
]


def _technical_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("technical_payload") if isinstance(payload.get("technical_payload"), dict) else payload
    return {
        key: value
        for key, value in raw.items()
        if key not in {"api_key", "download_policy", "storage_profile_id", "profile_id", "materialization_profile", "slice_id", "title"}
    }


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


def _workbench_workflow(
    *,
    tables: dict[str, Any],
    slices: list[dict[str, Any]],
    materializations: list[dict[str, Any]],
    dumps: list[dict[str, Any]],
    quality: dict[str, Any],
    active_context: dict[str, Any],
) -> dict[str, Any]:
    rows = {name: int((info or {}).get("rows") or 0) for name, info in tables.items()}
    active_stage = "idle"
    if any(str(item.get("state") or "") == "materializing" for item in materializations):
        active_stage = "materializing"
    elif rows.get("indices", 0) > 0 or rows.get("ratings", 0) > 0:
        active_stage = "analyzed"
    elif rows.get("works", 0) > 0 and rows.get("authorships", 0) > 0:
        active_stage = "tables"
    elif dumps:
        active_stage = "ready"
    elif slices:
        active_stage = str(slices[0].get("state") or "slice")

    quality_counts = quality.get("quality_counts") or {}
    allowed_raw = active_context.get("allowed_for_final_analysis")
    allowed_for_final_analysis = allowed_raw if isinstance(allowed_raw, bool) else None
    return {
        "active_stage": active_stage,
        "active_run_id": active_context.get("active_run_id"),
        "active_dump_id": active_context.get("active_dump_id"),
        "active_context_source": active_context.get("source"),
        "active_context_updated_at_utc": active_context.get("updated_at_utc"),
        "current_slice": slices[0] if slices else {},
        "quality_summary": {
            "quality_flags": sum(int(value or 0) for value in quality_counts.values()),
            "works": rows.get("works", 0),
            "authorships": rows.get("authorships", 0),
            "authors_indexed": rows.get("indices", 0),
            "analysis_eligibility_status": active_context.get("analysis_eligibility_status"),
            "allowed_for_final_analysis": allowed_for_final_analysis,
        },
    }


def _slice_title(cfg: Any) -> str:
    subject = cfg.entity_display_name or cfg.keyword_display_name or cfg.text_search_query or "все направления"
    territory = cfg.institution_display_name or cfg.country_code or "все страны"
    return f"{subject} / {territory} / {cfg.from_publication_date[:4]}-{cfg.to_publication_date[:4]}"


def _lifecycle(active: str) -> list[dict[str, Any]]:
    seen = True
    out: list[dict[str, Any]] = []
    for state in reversed(SLICE_STATES):
        if state["id"] == active:
            seen = False
        out.append({**state, "ready": not seen, "active": state["id"] == active})
    return list(reversed(out))


def _advance_state(current: str, target: str) -> str:
    if current in {"failed", "empty"} and target in {"estimated", "planned", "materializing", "ready", "analyzed", "reported"}:
        return target
    order = [state["id"] for state in SLICE_STATES]
    if current not in order or target not in order:
        return target
    return target if order.index(target) >= order.index(current) else current


def _matches_materialization_run(plan: dict[str, Any], run_id: str, materialization_id: str = "") -> bool:
    if str(plan.get("run_id") or "") == run_id:
        return True
    return bool(materialization_id and str(plan.get("materialization_id") or "") == materialization_id)


def _safe_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return text.strip("_.-")[:140] or f"slice_{uuid.uuid4().hex[:8]}"


def _slice_id(payload: dict[str, Any], cfg: Any, fingerprint: str) -> str:
    explicit = str(payload.get("slice_id") or "").strip()
    base = _safe_id(explicit or str(cfg.slice_name or "openalex_slice"))
    suffix = f"_{fingerprint}"
    prefix = base[: max(1, 140 - len(suffix))].strip("_.-") or "openalex_slice"
    return _safe_id(f"{prefix}{suffix}")


def _slice_fingerprint(cfg: Any) -> str:
    canonical = {
        "version": "slice_fingerprint_v3",
        "corpus_request": corpus_request(cfg),
        "quality_policy": {
            "exclude_retracted": cfg.exclude_retracted,
            "exclude_paratext": cfg.exclude_paratext,
            "include_xpac": cfg.include_xpac,
        },
    }
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:10]


def _materialization_fingerprint(
    cfg: Any,
    *,
    slice_fingerprint: str,
    source_strategy: str,
    storage_profile_id: str,
    download_policy: dict[str, Any],
) -> str:
    canonical = {
        "version": "materialization_fingerprint_v1",
        "slice_fingerprint": slice_fingerprint,
        "source_strategy": source_strategy,
        "storage_profile_id": storage_profile_id,
        "storage_profile_hash": _storage_profile_hash(storage_profile_id),
        "download_signature": cli_download_signature(cfg),
        "sort": cfg.sort,
        "download_policy": {
            key: value
            for key, value in sorted(download_policy.items())
            if key in {"complete_slice_required", "allow_incomplete_preview"}
        },
    }
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:10]


def _storage_profile_hash(storage_profile_id: str) -> str:
    profiles = _storage_profiles()
    profile = profiles.get(storage_profile_id) or {"profile_id": storage_profile_id}
    canonical = {
        "version": "storage_profile_hash_v1",
        "profile": profile,
    }
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:10]


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
