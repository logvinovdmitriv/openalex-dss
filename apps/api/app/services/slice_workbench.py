from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.paths import DATA
from app.services import author_slice, jobs, metadata_store, query_planner, warehouse


SLICES_DIR = DATA / "slices"
MATERIALIZATIONS_DIR = DATA / "materialization_plans"

MATERIALIZATION_PROFILES: dict[str, dict[str, Any]] = {
    "minimal_analytics": {
        "profile_id": "minimal_analytics",
        "label": "Минимальный для рейтингов",
        "description": "Работы, авторства, темы, источники и цитирования для локальных индексов.",
        "format": "jsonl + parquet",
        "selected_fields": [
            "id",
            "doi",
            "display_name",
            "publication_year",
            "publication_date",
            "type",
            "cited_by_count",
            "authorships",
            "primary_topic",
            "topics",
            "primary_location",
            "is_retracted",
            "is_paratext",
            "is_xpac",
            "is_authors_truncated",
        ],
    },
    "evidence_package": {
        "profile_id": "evidence_package",
        "label": "Расширенный для отчета",
        "description": "Минимальный профиль плюс дополнительные OpenAlex IDs и даты обновления.",
        "format": "jsonl + parquet + report assets",
        "selected_fields": [
            "id",
            "doi",
            "display_name",
            "publication_year",
            "publication_date",
            "type",
            "cited_by_count",
            "authorships",
            "primary_topic",
            "topics",
            "primary_location",
            "ids",
            "created_date",
            "updated_date",
            "is_retracted",
            "is_paratext",
            "is_xpac",
            "is_authors_truncated",
        ],
    },
}


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
            "limits": {
                "max_works": cfg.max_works,
                "max_dump_bytes": int(payload.get("max_dump_bytes") or 500 * 1024 * 1024),
            },
        },
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
    merged_payload = {**doc["technical_payload"], **_technical_payload(payload or {})}
    plan = query_planner.plan_slice(merged_payload)
    estimate = {
        "slice_id": slice_id,
        "status": plan["decision"]["status"],
        "decision": plan["decision"],
        "estimate": plan["estimate"],
        "openalex_filter": plan["openalex_filter"],
        "filter_classes": plan["filter_classes"],
        "limits": plan["limits"],
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
    profile_id = str(payload.get("profile_id") or payload.get("materialization_profile") or "minimal_analytics")
    profile = MATERIALIZATION_PROFILES.get(profile_id) or MATERIALIZATION_PROFILES["minimal_analytics"]
    max_dump_bytes = int(payload.get("max_dump_bytes") or doc["slice_definition"]["limits"].get("max_dump_bytes") or 500 * 1024 * 1024)
    plan_id = _safe_id(f"mat_{slice_id}_{profile['profile_id']}_{uuid.uuid4().hex[:8]}")
    estimate = doc.get("latest_estimate") or estimate_slice(slice_id)
    materialization = {
        "materialization_id": plan_id,
        "slice_id": slice_id,
        "state": "planned",
        "created_at_utc": _now(),
        "profile": profile,
        "source_strategy": "api_then_cache",
        "max_dump_bytes": max_dump_bytes,
        "estimated": estimate,
        "technical_payload": {
            **doc["technical_payload"],
            "max_dump_bytes": max_dump_bytes,
            "max_works": int((doc["technical_payload"].get("max_works") or 1000)),
        },
        "outputs": [
            "raw/openalex_slices/{slice_id}/works.jsonl",
            "normalized/works_flat.csv",
            "normalized/authorships_flat.csv",
            "results/author_indices.csv",
            "passports/slice_passport.json",
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
    return {"materializations": docs[: max(1, min(limit, 250))], "profiles": list(MATERIALIZATION_PROFILES.values())}


def list_dumps(limit: int = 50) -> dict[str, Any]:
    dumps = metadata_store.list_slice_dumps(limit=limit)
    return {"dumps": dumps, "total": len(dumps)}


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
    {"id": "planned", "label": "Planned", "description": "Выбран профиль материализации."},
    {"id": "materializing", "label": "Materializing", "description": "Идет загрузка или сборка локального набора."},
    {"id": "ready", "label": "Ready", "description": "Мини-дамп и локальные таблицы готовы."},
    {"id": "analyzed", "label": "Analyzed", "description": "Индексы и рейтинги рассчитаны."},
    {"id": "reported", "label": "Reported", "description": "Отчет и паспорта подготовлены."},
]


def _technical_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("technical_payload") if isinstance(payload.get("technical_payload"), dict) else payload
    return {key: value for key, value in raw.items() if key not in {"api_key"}}


def _public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "api_key"}


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
