from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.paths import DATA
from app.services import pipeline, query_planner, warehouse


RUNS_DIR = DATA / "runs"
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="openalex-dss-run")
_LOCK = threading.Lock()
_RUNS: dict[str, dict[str, Any]] = {}
_RUN_EXECUTION_PAYLOADS: dict[str, tuple[str, dict[str, Any]]] = {}


def create_run(action: str, payload: dict[str, Any], *, autostart: bool = True) -> dict[str, Any]:
    if action in {"build_from_openalex", "fetch_slice_dump"} and not _allow_unchecked_download() and not (
        str(payload.get("accepted_estimate_signature") or "").strip()
        and str(payload.get("accepted_download_signature") or "").strip()
    ):
        raise ValueError(f"{action} requires accepted estimate and download signatures. Create or refresh a materialization plan first.")
    run_id = _new_run_id()
    doc = {
        "run_id": run_id,
        "action": action,
        "status": "queued",
        "progress_percent": 0,
        "progress_stage": "queued",
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
        "error": None,
        "payload": _public_payload(payload),
        "result": None,
        "artifacts": _artifact_links(),
    }
    _save(doc)
    with _LOCK:
        _RUN_EXECUTION_PAYLOADS[run_id] = (action, dict(payload))
    if autostart:
        start_run(run_id)
    return doc


def start_run(run_id: str) -> dict[str, Any]:
    doc = get_run(run_id)
    if doc.get("status") != "queued":
        return doc
    with _LOCK:
        execution = _RUN_EXECUTION_PAYLOADS.get(run_id)
    action, payload = execution if execution else (str(doc.get("action") or ""), dict(doc.get("payload") or {}))
    if not action:
        raise ValueError(f"Run {run_id} has no executable action")
    doc["status"] = "running"
    doc["progress_stage"] = "starting"
    _save(doc)
    _EXECUTOR.submit(_execute, run_id, action, payload)
    return doc


def get_run(run_id: str) -> dict[str, Any]:
    with _LOCK:
        if run_id in _RUNS:
            return dict(_RUNS[run_id])
    path = _run_path(run_id)
    if not path.exists():
        raise KeyError(run_id)
    return json.loads(path.read_text(encoding="utf-8"))


def update_progress(run_id: str, percent: int, stage: str, extra: dict[str, Any] | None = None) -> None:
    doc = get_run(run_id)
    doc["progress_percent"] = max(0, min(100, int(percent)))
    doc["progress_stage"] = stage
    if extra:
        doc.setdefault("progress", {}).update(extra)
    _save(doc)


def list_runs(limit: int = 20) -> dict[str, Any]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    docs: list[dict[str, Any]] = []
    for path in sorted(RUNS_DIR.glob("run_*/run_status.json"), reverse=True):
        try:
            docs.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
        if len(docs) >= limit:
            break
    return {"runs": docs, "total": len(docs), "limit": limit}


def table_for_run(
    run_id: str,
    table_name: str,
    *,
    q: str = "",
    fraction_mode: str = "",
    metric: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    get_run(run_id)
    archived = _run_table_path(run_id, table_name)
    if archived:
        return warehouse.query_table_file(
            table_name,
            archived,
            q=q,
            fraction_mode=fraction_mode,
            metric=metric,
            limit=limit,
            offset=offset,
        )
    return warehouse.query_table(
        table_name,
        q=q,
        fraction_mode=fraction_mode,
        metric=metric,
        limit=limit,
        offset=offset,
    )


def _run_table_path(run_id: str, table_name: str) -> Path | None:
    run_dir = _run_path(run_id).parent / "tables"
    for suffix in (".parquet", ".csv"):
        candidate = run_dir / f"{table_name}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def _execute(run_id: str, action: str, payload: dict[str, Any]) -> None:
    doc = get_run(run_id)
    doc.update({"status": "running", "progress_percent": 10, "progress_stage": "preparing", "started_at": _now(), "error": None})
    _save(doc)
    try:
        doc.update({"progress_percent": _progress_before_dispatch(action), "progress_stage": _stage_for_action(action)})
        _save(doc)
        result = _dispatch(run_id, action, payload)
        _mark_dependent_state_completed(run_id, action, result, payload)
        doc.update({"status": "completed", "progress_percent": 100, "progress_stage": "completed", "finished_at": _now(), "result": result, "artifacts": _artifact_links()})
    except Exception as exc:  # pragma: no cover - defensive job boundary
        _mark_dependent_state_failed(run_id, action, str(exc), payload)
        doc.update({"status": "failed", "progress_percent": 100, "progress_stage": "failed", "finished_at": _now(), "error": str(exc)})
    _save(doc)
    with _LOCK:
        _RUN_EXECUTION_PAYLOADS.pop(run_id, None)


def _dispatch(run_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action == "plan":
        return query_planner.plan_slice(payload)
    if action == "fetch_slice_dump":
        return pipeline.fetch_slice_dump(
            payload,
            progress_callback=lambda progress: _download_progress(run_id, progress),
            require_accepted_signatures=not _allow_unchecked_download(),
        )
    if action == "build_from_openalex":
        fetched = pipeline.fetch_slice_dump(
            payload,
            progress_callback=lambda progress: _download_progress(run_id, progress),
            require_accepted_signatures=not _allow_unchecked_download(),
        )
        dump = fetched.get("dump") or {}
        raw_jsonl = str(dump.get("raw_jsonl") or "").strip()
        if not raw_jsonl or dump.get("no_data"):
            return {"fetch": fetched, "build": None, "no_data": True}
        analysis_eligibility = pipeline.analysis_eligibility_from_dump(dump, dev_override=_allow_unchecked_download())
        if not analysis_eligibility["allowed_for_final_analysis"] and not _allow_unchecked_download():
            raise ValueError("Дамп не допущен к финальному анализу. Обновите оценку и скачивание либо используйте явный dev-режим.")
        update_progress(run_id, 96, "normalizing local file", {"source_path": raw_jsonl})
        built = pipeline.import_local_file({
            **payload,
            "source_path": raw_jsonl,
            "api_key": None,
            "run_id": run_id,
            "dump_id": dump.get("dump_id"),
            "dump_manifest": dump,
            "analysis_eligibility": analysis_eligibility,
            "import_mode": "final_reproducible" if analysis_eligibility["allowed_for_final_analysis"] else "exploratory",
        })
        return {"fetch": fetched, "build": built, "no_data": False, "analysis_eligibility": analysis_eligibility}
    if action == "import_file":
        return pipeline.import_local_file(payload)
    if action == "recalculate":
        return pipeline.recalculate(payload)
    raise ValueError(f"Unsupported run action: {action}")


def _save(doc: dict[str, Any]) -> None:
    run_id = str(doc["run_id"])
    path = _run_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8", newline="\n")
    with _LOCK:
        _RUNS[run_id] = dict(doc)


def _run_path(run_id: str) -> Path:
    safe = "".join(ch for ch in run_id if ch.isalnum() or ch in "_-")
    return RUNS_DIR / safe / "run_status.json"


def _new_run_id() -> str:
    return f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    clean = dict(payload)
    if "api_key" in clean:
        clean["api_key"] = "***" if str(clean.get("api_key") or "").strip() else ""
    return clean


def _progress_before_dispatch(action: str) -> int:
    return {
        "plan": 25,
        "fetch_slice_dump": 25,
        "build_from_openalex": 20,
        "import_file": 35,
        "recalculate": 45,
    }.get(action, 20)


def _stage_for_action(action: str) -> str:
    return {
        "plan": "estimating slice",
        "fetch_slice_dump": "fetching mini-dump",
        "build_from_openalex": "fetching and building local mart",
        "import_file": "normalizing local file",
        "recalculate": "computing indices",
    }.get(action, "running")


def _download_progress(run_id: str, progress: dict[str, Any]) -> None:
    percent = int(progress.get("percent") or 0)
    # Keep a little room for normalization and report-building in build_from_openalex.
    bounded = min(95, max(25, percent))
    fetched = int(progress.get("fetched") or 0)
    total = progress.get("total_available")
    if total:
        stage = f"downloading works: {fetched}/{total}"
    elif fetched:
        stage = f"downloading works: {fetched}"
    else:
        stage = str(progress.get("stage") or "OpenAlex CLI is running; exact progress is unavailable until local files are packed")
    update_progress(run_id, bounded, stage, progress)


def _mark_dependent_state_completed(run_id: str, action: str, result: dict[str, Any], payload: dict[str, Any]) -> None:
    if action not in {"build_from_openalex", "fetch_slice_dump"}:
        return
    try:
        from app.services import slice_workbench

        slice_workbench.mark_materialization_run_completed(run_id, result, materialization_id=str(payload.get("materialization_id") or ""))
    except Exception:
        return


def _mark_dependent_state_failed(run_id: str, action: str, error: str, payload: dict[str, Any]) -> None:
    if action not in {"build_from_openalex", "fetch_slice_dump"}:
        return
    try:
        from app.services import slice_workbench

        slice_workbench.mark_materialization_run_failed(run_id, error, materialization_id=str(payload.get("materialization_id") or ""))
    except Exception:
        return


def _allow_unchecked_download() -> bool:
    return os.environ.get("OPENALEX_DSS_ALLOW_UNCHECKED_DOWNLOAD") == "1"


def _artifact_links() -> dict[str, str]:
    return {
        "slice_passport": "data/passports/slice_passport.json",
        "calculation_passport": "data/passports/calculation_passport.json",
        "quality_report": "data/passports/quality_report.json",
        "author_indices": "data/results/author_indices.csv",
        "rating_positions": "data/results/rating_positions.csv",
        "report_bundle": "data/reports/report_bundle.json",
    }
