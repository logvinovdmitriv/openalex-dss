from __future__ import annotations

import json
import re
import uuid
import hashlib
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.paths import DATA
from app.services.internal_payloads import normalize_internal_pipeline_payload
from app.services import artifact_context, author_slice, jobs, metadata_store, query_planner, registry, warehouse
from openalex_dss.config import config_to_dict
from openalex_dss.openalex import cli_download_signature, corpus_request, corpus_signature


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
    technical_payload = _canonical_payload(cfg, slice_name=slice_id)
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
        "current_estimate": None,
        "current_materialization_plan": None,
    }
    _write_slice(doc)
    return doc


def get_slice(slice_id: str) -> dict[str, Any]:
    path = _slice_path(slice_id)
    if not path.exists():
        raise KeyError(slice_id)
    return _read_json(path)


def delete_slice(slice_id: str) -> dict[str, Any]:
    doc = get_slice(slice_id)
    deleted_materializations = 0
    for path in MATERIALIZATIONS_DIR.glob("*.json"):
        plan = _read_json(path)
        if str(plan.get("slice_id") or "") != slice_id:
            continue
        if str(plan.get("state") or "") == "materializing":
            raise ValueError("Cannot delete a slice while its materialization is running.")
        try:
            path.unlink()
            deleted_materializations += 1
        except OSError:
            continue
    path = _slice_path(slice_id)
    try:
        path.unlink()
        path.parent.rmdir()
    except OSError:
        pass
    return {
        "deleted": True,
        "slice_id": str(doc.get("slice_id") or slice_id),
        "deleted_materializations": deleted_materializations,
    }


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
    cfg = author_slice.config_from_payload({**merged_payload, "workflow_mode": "strict_works"})
    doc["technical_payload"] = _public_payload(_canonical_payload(cfg, slice_name=slice_id))
    doc["state"] = _advance_state(str(doc.get("state") or "draft"), "estimated")
    doc["updated_at_utc"] = _now()
    doc["current_estimate"] = estimate
    doc["lifecycle"] = _lifecycle(doc["state"])
    _write_slice(doc)
    return estimate


def _current_estimate_or_refresh(slice_id: str, doc: dict[str, Any], cfg: Any, download_policy: dict[str, Any]) -> dict[str, Any]:
    current = doc.get("current_estimate") if isinstance(doc.get("current_estimate"), dict) else {}
    current_estimate = current.get("estimate") if isinstance(current.get("estimate"), dict) else {}
    if (
        current_estimate.get("estimate_signature") == corpus_signature(cfg)
        and current_estimate.get("download_signature") == cli_download_signature(cfg)
        and _download_policy(current.get("download_policy") or {}, fallback=doc.get("download_policy_default")) == download_policy
    ):
        return current
    return estimate_slice(slice_id, {"download_policy": download_policy})


def create_materialization_plan(slice_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = get_slice(slice_id)
    payload = payload or {}
    profile_id = str(payload.get("storage_profile_id") or payload.get("profile_id") or payload.get("materialization_profile") or "minimal_analytics")
    profiles = _storage_profiles()
    profile = profiles.get(profile_id) or next(iter(profiles.values()))
    source_strategy = str(payload.get("source_strategy") or payload.get("data_source_id") or "openalex_cli")
    download_dir = str(payload.get("download_dir") or "").strip()
    download_policy = _download_policy(payload, fallback=doc.get("download_policy_default"))
    plan_id = _safe_id(f"mat_{slice_id}_{profile['profile_id']}_{uuid.uuid4().hex[:8]}")
    cfg = author_slice.config_from_payload({**doc["technical_payload"], "workflow_mode": "strict_works"})
    estimate = _current_estimate_or_refresh(slice_id, doc, cfg, download_policy)
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
            **({"download_dir": download_dir} if download_dir else {}),
            "download_policy": download_policy,
            "accepted_estimate_signature": (estimate.get("estimate") or {}).get("estimate_signature"),
            "accepted_download_signature": (estimate.get("estimate") or {}).get("download_signature"),
            "query_plan": estimate,
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
        "download_dir": download_dir,
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
            "runs/{run_id}/tables/author_work.csv",
            "runs/{run_id}/tables/author_work.parquet",
            "runs/{run_id}/tables/indices.csv",
            "runs/{run_id}/tables/indices.parquet",
            "runs/{run_id}/tables/ratings.csv",
            "runs/{run_id}/tables/ratings.parquet",
            "runs/{run_id}/passports/slice_passport.json",
            "runs/{run_id}/passports/calculation_passport.json",
            "runs/{run_id}/passports/checksums.json",
            "runs/{run_id}/reports/report_{report_scope_hash}.json",
        ],
    }
    _write_materialization(materialization)
    doc["state"] = _advance_state(str(doc.get("state") or "estimated"), "planned")
    doc["current_materialization_plan"] = materialization
    doc["updated_at_utc"] = _now()
    doc["lifecycle"] = _lifecycle(doc["state"])
    _write_slice(doc)
    return materialization


def run_materialization(materialization_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = get_materialization_plan(materialization_id)
    payload = payload or {}
    if "download_dir" in payload:
        download_dir = str(payload.get("download_dir") or "").strip()
        plan["download_dir"] = download_dir
        technical_payload = dict(plan.get("technical_payload") or {})
        if download_dir:
            technical_payload["download_dir"] = download_dir
        else:
            technical_payload.pop("download_dir", None)
        plan["technical_payload"] = normalize_internal_pipeline_payload(technical_payload)
    run_payload = normalize_internal_pipeline_payload({
        **plan["technical_payload"],
        "materialization_id": plan["materialization_id"],
        "query_plan": plan.get("estimated"),
        "accepted_estimate_signature": plan.get("accepted_estimate_signature"),
        "accepted_download_signature": plan.get("accepted_download_signature"),
        **payload,
    })
    run = jobs.create_run("build_from_openalex", run_payload, autostart=False)
    plan["state"] = "materializing"
    plan["run_id"] = run["run_id"]
    plan["updated_at_utc"] = _now()
    _write_materialization(plan)
    try:
        doc = get_slice(plan["slice_id"])
        doc["state"] = _advance_state(str(doc.get("state") or "planned"), "materializing")
        doc["current_materialization_plan"] = plan
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
    requested_limit = max(1, min(limit, 250))
    dumps = _merged_dump_records(limit=requested_limit)
    return {"dumps": dumps[:requested_limit], "total": len(dumps)}


def delete_dump(dump_id: str) -> dict[str, Any]:
    requested_dump_id = str(dump_id or "").strip()
    if not requested_dump_id:
        raise ValueError("dump_id is required")
    raw_dump_id, dump = _resolve_dump_record(requested_dump_id)
    if not dump:
        raise KeyError(requested_dump_id)
    deleted_paths: list[str] = []
    for path in _dump_delete_paths(raw_dump_id, dump):
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        deleted_paths.append(str(path))
    deleted_runs = _delete_runs_for_dump(raw_dump_id)
    deleted_materializations = _delete_materializations_for_dump(raw_dump_id)
    db_result = metadata_store.delete_slice_dump_by_dump_id(raw_dump_id)
    active_context = artifact_context.read_active_context()
    if str(active_context.get("active_dump_id") or "") == raw_dump_id or str(active_context.get("active_run_id") or "") in deleted_runs:
        artifact_context.write_active_context(run_id="", dump_id="", source="deleted_local_slice")
    return {
        "deleted": True,
        "dump_id": raw_dump_id,
        "deleted_paths": deleted_paths,
        "deleted_runs": deleted_runs,
        "deleted_materializations": deleted_materializations,
        "metadata_rows_deleted": db_result["deleted"],
    }


def select_dump(dump_id: str) -> dict[str, Any]:
    requested_dump_id = str(dump_id or "").strip()
    if not requested_dump_id:
        raise ValueError("dump_id is required")
    raw_dump_id, dump = _resolve_dump_record(requested_dump_id)
    if not dump:
        raise KeyError(requested_dump_id)
    associated_run_id = _recent_run_for_dump(raw_dump_id)
    active_context = artifact_context.write_active_context(
        run_id=associated_run_id,
        dump_id=raw_dump_id,
        source="selected_local_slice",
        extra={
            "slice_id": str(dump.get("slice_id") or ""),
            "associated_run_id": associated_run_id,
            "allowed_for_final_analysis": dump.get("allowed_for_final_analysis"),
            "scientific_completeness": str(dump.get("scientific_completeness") or ""),
        },
    )
    return {"status": "ok", "dump": dump, "associated_run_id": associated_run_id, "active_context": active_context}


def repair_dump(dump_id: str) -> dict[str, Any]:
    requested_dump_id = str(dump_id or "").strip()
    if not requested_dump_id:
        raise ValueError("dump_id is required")
    raw_dump_id, dump = _resolve_dump_record(requested_dump_id)
    if not dump:
        raise KeyError(requested_dump_id)
    health = _dump_health(raw_dump_id, dump)
    if not health.get("repairable"):
        raise ValueError(str(health.get("reason") or "Этот локальный срез нельзя восстановить автоматически."))
    run_payload = normalize_internal_pipeline_payload(
        {
            "dump_id": raw_dump_id,
            "source_path": dump.get("raw_jsonl"),
            "dump_manifest": dump,
            "analysis_eligibility": {
                "allowed_for_final_analysis": bool(dump.get("allowed_for_final_analysis")),
                "scientific_completeness": str(dump.get("scientific_completeness") or ""),
                "records_downloaded": int(dump.get("records_downloaded") or 0),
                "dump_id": raw_dump_id,
            },
        }
    )
    run = jobs.create_run("repair_dump", run_payload, autostart=False)
    jobs.start_run(run["run_id"])
    return {"status": "queued", "dump": dump, "health": health, "run": jobs.get_run(run["run_id"])}


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
        doc["current_materialization_plan"] = plan
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
        doc["current_materialization_plan"] = plan
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
    quality = warehouse.read_json_doc("quality", run_id=active_run_id) if active_run_id else {}
    quality = quality or {}
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
    {"id": "draft", "label": "Черновик", "description": "Срез задан пользователем."},
    {"id": "resolved", "label": "Сопоставлен", "description": "Срез сопоставлен со справочниками OpenAlex."},
    {"id": "estimated", "label": "Оценен", "description": "Оценены объем, прогноз загрузки и использование API."},
    {"id": "planned", "label": "План готов", "description": "Выбраны режим хранения и папка загрузки."},
    {"id": "materializing", "label": "Загружается", "description": "Идет загрузка или сборка локального среза."},
    {"id": "empty", "label": "Нет работ", "description": "OpenAlex вернул пустой корпус для выбранного среза."},
    {"id": "ready", "label": "Готов", "description": "Локальные файлы и таблицы готовы."},
    {"id": "analyzed", "label": "Индексы готовы", "description": "Индексы и рейтинги рассчитаны."},
    {"id": "reported", "label": "Отчет готов", "description": "Отчет и паспорта подготовлены."},
    {"id": "failed", "label": "Ошибка", "description": "Загрузка или расчет завершились ошибкой."},
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


def _canonical_payload(cfg: Any, *, slice_name: str | None = None) -> dict[str, Any]:
    payload = config_to_dict(cfg)
    if slice_name is not None:
        payload["slice_name"] = slice_name
    return normalize_internal_pipeline_payload(payload)


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
            "label": "Стандартные данные среза",
            "description": "Базовая настройка хранения из конфигурации не найдена.",
            "format": "jsonl.gz + parquet",
            "selected_fields": [],
        }
    return out


def select_directory(initial_dir: str = "") -> dict[str, Any]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # pragma: no cover - depends on local desktop runtime
        raise RuntimeError("Системный выбор папки недоступен в текущем окружении. Укажите путь вручную.") from exc

    root = tk.Tk()
    root.withdraw()
    try:
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        initial = Path(str(initial_dir or "")).expanduser()
        kwargs: dict[str, Any] = {"title": "Выберите папку для скачивания среза"}
        if initial.is_dir():
            kwargs["initialdir"] = str(initial)
        selected = filedialog.askdirectory(**kwargs)
    finally:
        root.destroy()
    return {"path": str(selected or "")}


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
    if rows.get("indices", 0) > 0 or rows.get("ratings", 0) > 0:
        active_stage = "analyzed"
    elif rows.get("works", 0) > 0 and rows.get("authorships", 0) > 0:
        active_stage = "tables"
    elif any(str(item.get("state") or "") == "materializing" for item in materializations):
        active_stage = "materializing"
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


def _resolve_dump_record(dump_id: str) -> tuple[str, dict[str, Any] | None]:
    raw_dump_id = str(dump_id or "").strip()
    if not raw_dump_id:
        return "", None
    exact = _metadata_dump_by_id(raw_dump_id)
    if exact:
        return str(exact.get("dump_id") or raw_dump_id), exact
    prefixed = raw_dump_id if raw_dump_id.startswith("dump_") else f"dump_{_safe_id(raw_dump_id)}"
    if prefixed != raw_dump_id:
        candidate = _metadata_dump_by_id(prefixed)
        if candidate:
            return str(candidate.get("dump_id") or prefixed), candidate
    safe_raw = _safe_id(raw_dump_id)
    for candidate in _merged_dump_records(limit=250):
        candidate_id = str(candidate.get("dump_id") or "")
        safe_candidate = _safe_id(candidate_id)
        if safe_candidate == safe_raw or safe_candidate == f"dump_{safe_raw}" or safe_candidate.endswith(f"_{safe_raw}"):
            return candidate_id, candidate
    return raw_dump_id, None


def _merged_dump_records(limit: int = 250) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for dump in _metadata_dump_records(limit=limit):
        dump_id = str(dump.get("dump_id") or "").strip()
        if dump_id:
            merged[dump_id] = dump
    for dump in _filesystem_dump_records(limit=limit):
        dump_id = str(dump.get("dump_id") or "").strip()
        if not dump_id:
            continue
        merged[dump_id] = {**dump, **merged.get(dump_id, {})}
    records = [_with_dump_health(dump_id, dump) for dump_id, dump in merged.items()]
    return sorted(
        records,
        key=lambda item: str(item.get("created_at_utc") or item.get("download_finished_at_utc") or ""),
        reverse=True,
    )


def _with_dump_health(dump_id: str, dump: dict[str, Any]) -> dict[str, Any]:
    health = _dump_health(dump_id, dump)
    return {**dump, "health": health, "storage": _dump_storage_summary(dump_id, dump, health)}


def _dump_health(dump_id: str, dump: dict[str, Any]) -> dict[str, Any]:
    raw_jsonl = Path(str(dump.get("raw_jsonl") or ""))
    raw_exists = raw_jsonl.is_file()
    storage_plan = dump.get("storage_plan") if isinstance(dump.get("storage_plan"), dict) else {}
    cli_files_dir_raw = str(dump.get("cli_files_dir") or storage_plan.get("cli_output_dir") or "").strip()
    cli_files_dir = Path(cli_files_dir_raw) if cli_files_dir_raw else None
    manifest_path = Path(str(dump.get("dump_manifest") or dump.get("manifest_path") or raw_jsonl.with_name("dump_manifest.json")))
    files_manifest_path = Path(str(dump.get("files_manifest") or manifest_path.with_name("files_manifest.json")))
    cli_files_snapshot = _downloaded_files_snapshot(cli_files_dir, files_manifest_path) if cli_files_dir is not None else {"files_seen": 0, "bytes_written": 0}
    cli_files_ready = bool(cli_files_dir is not None and cli_files_snapshot["files_seen"] > 0)
    manifest_exists = manifest_path.is_file()
    records = int(dump.get("records_downloaded") or 0)
    completeness = str(dump.get("scientific_completeness") or "").strip()
    safe_dump_id = _safe_id(str(dump_id or dump.get("dump_id") or ""))
    table_dir = DATA / "tables" / safe_dump_id
    dump_dir = DATA / "dumps" / safe_dump_id
    table_files = [table_dir / "works.parquet", table_dir / "authorships.parquet", table_dir / "work_topics.parquet"]
    tables_ready = all(path.is_file() for path in table_files)
    associated_run = _recent_run_for_dump(safe_dump_id)
    indices_ready = bool(associated_run and (DATA / "runs" / associated_run / "tables" / "indices.csv").is_file())
    if not raw_exists and cli_files_ready:
        return {
            "status": "needs_repair",
            "label": "требует восстановления",
            "reason": "Скачанные файлы есть, но единый файл среза еще не собран.",
            "repairable": True,
            "raw_exists": False,
            "manifest_exists": manifest_exists,
            "tables_ready": tables_ready,
            "indices_ready": indices_ready,
            "associated_run_id": associated_run,
            "files_seen": cli_files_snapshot["files_seen"],
            "bytes_written": cli_files_snapshot["bytes_written"],
        }
    if not raw_exists:
        return {
            "status": "broken",
            "label": "поврежден",
            "reason": "Файл локального среза не найден на диске.",
            "repairable": False,
            "raw_exists": False,
            "manifest_exists": manifest_exists,
            "tables_ready": tables_ready,
            "indices_ready": indices_ready,
            "associated_run_id": associated_run,
            "files_seen": cli_files_snapshot["files_seen"],
            "bytes_written": cli_files_snapshot["bytes_written"],
        }
    if records <= 0:
        return {
            "status": "broken",
            "label": "нет работ",
            "reason": "В локальном срезе нет записей для анализа.",
            "repairable": False,
            "raw_exists": True,
            "manifest_exists": manifest_exists,
            "tables_ready": tables_ready,
            "indices_ready": indices_ready,
            "associated_run_id": associated_run,
            "files_seen": cli_files_snapshot["files_seen"],
            "bytes_written": cli_files_snapshot["bytes_written"],
        }
    if not tables_ready:
        return {
            "status": "needs_repair",
            "label": "требует восстановления",
            "reason": "Скачанный файл есть, но нормализованные таблицы не собраны.",
            "repairable": True,
            "raw_exists": True,
            "manifest_exists": manifest_exists,
            "tables_ready": False,
            "indices_ready": indices_ready,
            "associated_run_id": associated_run,
            "files_seen": cli_files_snapshot["files_seen"],
            "bytes_written": cli_files_snapshot["bytes_written"],
        }
    if not indices_ready:
        return {
            "status": "ready",
            "label": "данные готовы",
            "reason": "Срез можно открыть; для авторских показателей запустите расчет индексов.",
            "repairable": True,
            "raw_exists": True,
            "manifest_exists": manifest_exists,
            "tables_ready": True,
            "indices_ready": False,
            "associated_run_id": associated_run,
            "files_seen": cli_files_snapshot["files_seen"],
            "bytes_written": cli_files_snapshot["bytes_written"],
        }
    status = "partial" if completeness == "partial" else "analyzed"
    label = "частичный срез" if completeness == "partial" else "готов"
    return {
        "status": status,
        "label": label,
        "reason": "Срез готов к работе.",
        "repairable": False,
        "raw_exists": True,
        "manifest_exists": manifest_exists,
        "tables_ready": True,
        "indices_ready": True,
        "associated_run_id": associated_run,
        "dump_dir": str(dump_dir),
        "files_seen": cli_files_snapshot["files_seen"],
        "bytes_written": cli_files_snapshot["bytes_written"],
    }


def _metadata_dump_records(limit: int = 250) -> list[dict[str, Any]]:
    try:
        return metadata_store.list_slice_dumps(limit=limit)
    except sqlite3.OperationalError:
        return []


def _metadata_dump_by_id(dump_id: str) -> dict[str, Any] | None:
    try:
        return metadata_store.get_slice_dump_by_dump_id(dump_id)
    except sqlite3.OperationalError:
        return None


def _filesystem_dump_records(limit: int = 250) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    manifests = []
    dumps_dir = DATA / "dumps"
    if dumps_dir.exists():
        manifests.extend(dumps_dir.glob("*/dump_manifest.json"))
    raw_dir = DATA / "raw" / "openalex_cli"
    if raw_dir.exists():
        manifests.extend(raw_dir.glob("*/dump_manifest.json"))
        manifests.extend(raw_dir.glob("*/*/dump_manifest.json"))
    manifests = sorted(set(manifests), key=_path_mtime, reverse=True)
    manifest_dirs = {manifest_path.parent.resolve() for manifest_path in manifests}
    for manifest_path in manifests[: max(1, min(limit, 250))]:
        manifest = _read_json(manifest_path)
        if not manifest:
            continue
        dump_id = str(manifest.get("dump_id") or manifest_path.parent.name).strip()
        raw_jsonl = str(manifest.get("raw_jsonl") or "").strip()
        files_manifest = str(manifest.get("files_manifest") or "").strip()
        source = {
            **manifest,
            "dump_id": dump_id,
            "slice_id": str(manifest.get("slice_id") or ""),
            "raw_jsonl": raw_jsonl,
            "records_downloaded": int(manifest.get("records_downloaded") or 0),
            "records_expected": manifest.get("records_expected"),
            "bytes_written": int(manifest.get("bytes_written") or _path_size(raw_jsonl)),
            "sha256": str(manifest.get("raw_jsonl_sha256") or manifest.get("sha256") or ""),
            "stop_reason": str(manifest.get("stop_reason") or ""),
            "created_at_utc": str(manifest.get("created_at_utc") or manifest.get("download_finished_at_utc") or ""),
            "source_mode": str(manifest.get("source_mode") or "openalex_cli"),
            "scientific_completeness": str(manifest.get("scientific_completeness") or ""),
            "allowed_for_final_analysis": bool(manifest.get("allowed_for_final_analysis")),
            "openalex_filter": str((manifest.get("openalex_request") or {}).get("filter") or manifest.get("openalex_filter") or ""),
            "estimate_signature": str((manifest.get("signatures") or {}).get("estimate_signature") or manifest.get("estimate_signature") or ""),
            "download_signature": str((manifest.get("signatures") or {}).get("download_signature") or manifest.get("download_signature") or ""),
            "files_manifest": files_manifest,
            "dump_manifest": str(manifest_path),
            "manifest_path": str(manifest_path),
            "source": "filesystem",
        }
        records.append(source)
    if raw_dir.exists() and len(records) < limit:
        candidate_file_dirs = list(raw_dir.glob("*/files")) + list(raw_dir.glob("*/*/files"))
        for files_dir in sorted(candidate_file_dirs, key=_path_mtime, reverse=True):
            base_dir = files_dir.parent
            try:
                if base_dir.resolve() in manifest_dirs:
                    continue
            except OSError:
                continue
            snapshot = _downloaded_files_snapshot(files_dir, base_dir / "files_manifest.json")
            if snapshot["files_seen"] <= 0:
                continue
            fingerprint = hashlib.sha256(str(base_dir).encode("utf-8")).hexdigest()[:16]
            created = datetime.fromtimestamp(_path_mtime(base_dir), tz=timezone.utc).isoformat()
            records.append(
                {
                    "dump_id": f"dump_pending_{fingerprint}",
                    "slice_id": base_dir.parent.name,
                    "raw_jsonl": str(base_dir / "works.jsonl.gz"),
                    "records_downloaded": 0,
                    "records_expected": None,
                    "bytes_written": snapshot["bytes_written"],
                    "sha256": "",
                    "stop_reason": "not_packed",
                    "created_at_utc": created,
                    "source_mode": "openalex_cli",
                    "scientific_completeness": "partial",
                    "allowed_for_final_analysis": False,
                    "openalex_filter": "",
                    "estimate_signature": "",
                    "download_signature": "",
                    "files_manifest": str(base_dir / "files_manifest.json"),
                    "dump_manifest": str(base_dir / "dump_manifest.json"),
                    "manifest_path": str(base_dir / "dump_manifest.json"),
                    "cli_files_dir": str(files_dir),
                    "source": "filesystem",
                    "storage_plan": {
                        "download_base_dir": str(base_dir),
                        "cli_output_dir": str(files_dir),
                        "raw_jsonl": str(base_dir / "works.jsonl.gz"),
                    },
                }
            )
            if len(records) >= limit:
                break
    return records


def _downloaded_files_snapshot(files_dir: Path, manifest_path: Path | None = None) -> dict[str, int]:
    manifest_snapshot = _files_manifest_snapshot(manifest_path or files_dir.parent / "files_manifest.json")
    if manifest_snapshot["files_seen"] > 0:
        return manifest_snapshot
    files_seen = 0
    bytes_written = 0
    if not files_dir.is_dir():
        return {"files_seen": 0, "bytes_written": 0}
    stack = [files_dir]
    max_files = 5000
    while stack and files_seen < max_files:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for path in entries:
            if path.is_dir():
                stack.append(path)
                continue
            if not path.is_file():
                continue
            files_seen += 1
            try:
                bytes_written += path.stat().st_size
            except OSError:
                continue
            if files_seen >= max_files:
                break
    return {"files_seen": files_seen, "bytes_written": bytes_written}


def _files_manifest_snapshot(manifest_path: Path) -> dict[str, int]:
    if not manifest_path.is_file():
        return {"files_seen": 0, "bytes_written": 0}
    doc = _read_json(manifest_path)
    files = doc.get("files") if isinstance(doc, dict) else None
    if not isinstance(files, list):
        return {"files_seen": 0, "bytes_written": 0}
    bytes_written = 0
    for item in files:
        if isinstance(item, dict):
            bytes_written += int(item.get("bytes") or 0)
    return {"files_seen": len(files), "bytes_written": bytes_written}


def _path_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _path_size(path: str) -> int:
    if not path:
        return 0
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def _dump_storage_summary(dump_id: str, dump: dict[str, Any], health: dict[str, Any]) -> dict[str, int | str]:
    safe_dump_id = _safe_id(str(dump_id or dump.get("dump_id") or ""))
    raw_jsonl = str(dump.get("raw_jsonl") or "")
    raw_bytes = _path_size(raw_jsonl)
    if raw_bytes <= 0:
        raw_bytes = int(health.get("bytes_written") or dump.get("bytes_written") or 0)
    tables_bytes = _dir_size(DATA / "tables" / safe_dump_id)
    dump_meta_bytes = _dir_size(DATA / "dumps" / safe_dump_id)
    run_bytes = 0
    analytics_cache_bytes = 0
    for run_id in _run_ids_for_dump(safe_dump_id):
        run_dir = DATA / "runs" / run_id
        run_bytes += _dir_size(run_dir)
        analytics_cache_bytes += _dir_size(run_dir / "analytics")
    total = raw_bytes + tables_bytes + dump_meta_bytes + run_bytes
    return {
        "raw_bytes": raw_bytes,
        "tables_bytes": tables_bytes,
        "dump_metadata_bytes": dump_meta_bytes,
        "runs_bytes": run_bytes,
        "analytics_cache_bytes": analytics_cache_bytes,
        "total_known_bytes": total,
        "raw_path": raw_jsonl,
        "tables_path": str(DATA / "tables" / safe_dump_id),
        "dump_path": str(DATA / "dumps" / safe_dump_id),
    }


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        if not child.is_file():
            continue
        try:
            total += child.stat().st_size
        except OSError:
            continue
    return total


def _run_ids_for_dump(dump_id: str) -> list[str]:
    target = _safe_id(str(dump_id or ""))
    if not target:
        return []
    run_ids: list[str] = []
    for metric_run in (DATA / "runs").glob("run_*/metric_run.json"):
        manifest = _read_json(metric_run)
        manifest_dump_id = _safe_id(str(manifest.get("dump_id") or manifest.get("input_dump_id") or ""))
        if manifest_dump_id == target:
            run_ids.append(metric_run.parent.name)
    return run_ids


def _recent_run_for_dump(dump_id: str) -> str:
    target = _safe_id(str(dump_id or ""))
    if not target:
        return ""
    best_run_id = ""
    best_mtime = -1.0
    for metric_run in (DATA / "runs").glob("run_*/metric_run.json"):
        manifest = _read_json(metric_run)
        manifest_dump_id = _safe_id(str(manifest.get("dump_id") or manifest.get("input_dump_id") or ""))
        if manifest_dump_id != target:
            continue
        try:
            mtime = metric_run.stat().st_mtime
        except OSError:
            mtime = 0.0
        if mtime >= best_mtime:
            best_mtime = mtime
            best_run_id = metric_run.parent.name
    return best_run_id


def _dump_delete_paths(dump_id: str, dump: dict[str, Any]) -> list[Path]:
    safe_dump_id = _safe_id(dump_id)
    paths = [
        DATA / "dumps" / safe_dump_id,
        DATA / "tables" / safe_dump_id,
    ]
    raw_jsonl = Path(str(dump.get("raw_jsonl") or ""))
    if raw_jsonl.is_file():
        paths.append(raw_jsonl)
        raw_base = raw_jsonl.parent
        storage_plan = dump.get("storage_plan") if isinstance(dump.get("storage_plan"), dict) else {}
        raw_download_base = str(storage_plan.get("download_base_dir") or "").strip()
        if raw_download_base:
            download_base = Path(raw_download_base)
            if download_base.exists():
                paths.append(download_base)
        if raw_base.name == "openalex_cli":
            paths.append(raw_base)
        elif raw_base.parent.name == "openalex_cli":
            paths.append(raw_base)
        elif raw_base.parent.parent.name == "openalex_cli":
            paths.append(raw_base.parent)
    return _unique_child_paths(paths)


def _delete_runs_for_dump(dump_id: str) -> list[str]:
    deleted: list[str] = []
    runs_dir = DATA / "runs"
    target = _safe_id(dump_id)
    for metric_run in runs_dir.glob("run_*/metric_run.json"):
        manifest = _read_json(metric_run)
        manifest_dump_id = _safe_id(str(manifest.get("dump_id") or manifest.get("input_dump_id") or ""))
        if manifest_dump_id != target:
            continue
        run_dir = metric_run.parent
        shutil.rmtree(run_dir, ignore_errors=True)
        deleted.append(run_dir.name)
    return deleted


def _delete_materializations_for_dump(dump_id: str) -> list[str]:
    deleted: list[str] = []
    target = _safe_id(dump_id)
    for path in MATERIALIZATIONS_DIR.glob("*.json"):
        plan = _read_json(path)
        dump_manifest = plan.get("dump_manifest") if isinstance(plan.get("dump_manifest"), dict) else {}
        plan_dump_id = _safe_id(str(plan.get("dump_id") or dump_manifest.get("dump_id") or ""))
        if plan_dump_id != target:
            continue
        try:
            path.unlink()
            deleted.append(str(plan.get("materialization_id") or path.stem))
        except OSError:
            continue
    return deleted


def _unique_child_paths(paths: list[Path]) -> list[Path]:
    resolved: list[Path] = []
    data_root = DATA.resolve()
    for path in paths:
        try:
            current = path.expanduser().resolve()
            current.relative_to(data_root)
        except (OSError, ValueError):
            continue
        if current == data_root:
            continue
        if current not in resolved:
            resolved.append(current)
    return sorted(resolved, key=lambda item: len(item.parts), reverse=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
