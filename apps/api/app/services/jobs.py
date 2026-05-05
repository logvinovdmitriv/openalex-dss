from __future__ import annotations

import json
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


def create_run(action: str, payload: dict[str, Any]) -> dict[str, Any]:
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
    return warehouse.query_table(
        table_name,
        q=q,
        fraction_mode=fraction_mode,
        metric=metric,
        limit=limit,
        offset=offset,
    )


def _execute(run_id: str, action: str, payload: dict[str, Any]) -> None:
    doc = get_run(run_id)
    doc.update({"status": "running", "progress_percent": 10, "progress_stage": "preparing", "started_at": _now(), "error": None})
    _save(doc)
    try:
        doc.update({"progress_percent": _progress_before_dispatch(action), "progress_stage": _stage_for_action(action)})
        _save(doc)
        result = _dispatch(run_id, action, payload)
        doc.update({"status": "completed", "progress_percent": 100, "progress_stage": "completed", "finished_at": _now(), "result": result, "artifacts": _artifact_links()})
    except Exception as exc:  # pragma: no cover - defensive job boundary
        doc.update({"status": "failed", "progress_percent": 100, "progress_stage": "failed", "finished_at": _now(), "error": str(exc)})
    _save(doc)


def _dispatch(run_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action == "plan":
        return query_planner.plan_slice(payload)
    if action == "fetch_slice_dump":
        return pipeline.fetch_slice_dump(payload, progress_callback=lambda progress: _download_progress(run_id, progress))
    if action == "build_from_openalex":
        fetched = pipeline.fetch_slice_dump(payload, progress_callback=lambda progress: _download_progress(run_id, progress))
        dump = fetched.get("dump") or {}
        raw_jsonl = str(dump.get("raw_jsonl") or "").strip()
        if not raw_jsonl or dump.get("no_data"):
            return {"fetch": fetched, "build": None, "no_data": True}
        update_progress(run_id, 96, "normalizing local file", {"source_path": raw_jsonl})
        built = pipeline.import_local_file({
            **payload,
            "source_path": raw_jsonl,
            "api_key": None,
            "run_id": run_id,
            "dump_id": dump.get("dump_id"),
            "dump_manifest": dump,
        })
        return {"fetch": fetched, "build": built, "no_data": False}
    if action == "import_file":
        return pipeline.import_local_file(payload)
    if action == "recalculate":
        return pipeline.recalculate(payload)
    if action == "author_preview":
        return pipeline.fetch_author_preview(payload)
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
        "author_preview": 30,
    }.get(action, 20)


def _stage_for_action(action: str) -> str:
    return {
        "plan": "estimating slice",
        "fetch_slice_dump": "fetching mini-dump",
        "build_from_openalex": "fetching and building local mart",
        "import_file": "normalizing local file",
        "recalculate": "computing indices",
        "author_preview": "enriching author preview",
    }.get(action, "running")


def _download_progress(run_id: str, progress: dict[str, Any]) -> None:
    percent = int(progress.get("percent") or 0)
    # Keep a little room for normalization and report-building in build_from_openalex.
    bounded = min(95, max(25, percent))
    fetched = int(progress.get("fetched") or 0)
    total = progress.get("total_available")
    if total:
        stage = f"downloading works: {fetched}/{total}"
    else:
        stage = f"downloading works: {fetched}"
    update_progress(run_id, bounded, stage, progress)


def _artifact_links() -> dict[str, str]:
    return {
        "slice_passport": "data/passports/slice_passport.json",
        "calculation_passport": "data/passports/calculation_passport.json",
        "quality_report": "data/passports/quality_report.json",
        "author_indices": "data/results/author_indices.csv",
        "rating_positions": "data/results/rating_positions.csv",
        "report_bundle": "data/reports/report_bundle.json",
    }
