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
from app.services.internal_payloads import normalize_internal_pipeline_payload
from app.services import analysis_jobs, materialization_jobs


RUNS_DIR = DATA / "runs"
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="openalex-dss-run")
_LOCK = threading.Lock()
_RUNS: dict[str, dict[str, Any]] = {}
_RUN_EXECUTION_PAYLOADS: dict[str, tuple[str, dict[str, Any]]] = {}
SUPPORTED_JOB_ACTIONS = analysis_jobs.ANALYSIS_ACTIONS | materialization_jobs.SUPPORTED_MATERIALIZATION_ACTIONS


def create_run(action: str, payload: dict[str, Any], *, autostart: bool = True) -> dict[str, Any]:
    if action not in SUPPORTED_JOB_ACTIONS:
        raise ValueError(f"Unsupported run action: {action}")
    payload = normalize_internal_pipeline_payload(payload)
    if action in materialization_jobs.REQUIRES_ACCEPTED_SIGNATURE_ACTIONS and not _allow_unchecked_download() and not (
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
        "artifacts": {},
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
    return _normalize_loaded_run(json.loads(path.read_text(encoding="utf-8")))


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
            docs.append(_normalize_loaded_run(json.loads(path.read_text(encoding="utf-8"))))
        except json.JSONDecodeError:
            continue
        if len(docs) >= limit:
            break
    return {"runs": docs, "total": len(docs), "limit": limit}


def _execute(run_id: str, action: str, payload: dict[str, Any]) -> None:
    doc = get_run(run_id)
    doc.update({"status": "running", "progress_percent": 10, "progress_stage": "preparing", "started_at": _now(), "error": None})
    _save(doc)
    try:
        doc.update({"progress_percent": _progress_before_dispatch(action), "progress_stage": _stage_for_action(action)})
        _save(doc)
        result = _dispatch(run_id, action, payload)
        materialization_jobs.mark_completed(run_id, action, result, payload)
        doc.update({
            "status": "completed",
            "progress_percent": 100,
            "progress_stage": "completed",
            "finished_at": _now(),
            "result": result,
            "artifacts": _artifact_links(action, run_id, result),
        })
    except Exception as exc:  # pragma: no cover - defensive job boundary
        materialization_jobs.mark_failed(run_id, action, str(exc), payload)
        doc.update({"status": "failed", "progress_percent": 100, "progress_stage": "failed", "finished_at": _now(), "error": str(exc)})
    _save(doc)
    with _LOCK:
        _RUN_EXECUTION_PAYLOADS.pop(run_id, None)


def _dispatch(run_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = normalize_internal_pipeline_payload(payload)
    if action in analysis_jobs.ANALYSIS_ACTIONS:
        return analysis_jobs.recalculate(run_id, payload)
    if action in materialization_jobs.SUPPORTED_MATERIALIZATION_ACTIONS:
        return materialization_jobs.dispatch(
            run_id,
            action,
            payload,
            download_progress_callback=lambda progress: _download_progress(run_id, progress),
            update_progress_callback=lambda percent, stage, extra=None: update_progress(run_id, percent, stage, extra),
            allow_unchecked_download=_allow_unchecked_download(),
        )
    raise ValueError(f"Unsupported run action: {action}")


def _save(doc: dict[str, Any]) -> None:
    run_id = str(doc["run_id"])
    path = _run_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8", newline="\n")
    with _LOCK:
        _RUNS[run_id] = dict(doc)


def _normalize_loaded_run(doc: dict[str, Any]) -> dict[str, Any]:
    status = str(doc.get("status") or "")
    run_id = str(doc.get("run_id") or "")
    with _LOCK:
        in_memory = run_id in _RUNS or run_id in _RUN_EXECUTION_PAYLOADS
    if status in {"queued", "running"} and not in_memory:
        doc = dict(doc)
        doc["status"] = "failed"
        doc["progress_percent"] = 100
        doc["progress_stage"] = "failed"
        doc["finished_at"] = doc.get("finished_at") or _now()
        doc["error"] = (
            "Задача была прервана при остановке сервера. "
            "Если локальный срез уже скачан, выберите его в списке срезов и запустите расчет индексов."
        )
        if run_id:
            _save(doc)
    return doc


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
        "fetch_slice_dump": 25,
        "build_from_openalex": 20,
        "recalculate": 45,
    }.get(action, 20)


def _stage_for_action(action: str) -> str:
    return {
        "fetch_slice_dump": "Загрузка локального среза",
        "build_from_openalex": "Загрузка и построение локального среза",
        "recalculate": "Расчет индексов",
    }.get(action, "running")


def _download_progress(run_id: str, progress: dict[str, Any]) -> None:
    percent = int(progress.get("percent") or 0)
    # Keep a little room for normalization and report-building in build_from_openalex.
    bounded = min(95, max(25, percent))
    fetched = int(progress.get("fetched") or 0)
    total = progress.get("total_available")
    files_seen = int(progress.get("files_seen") or 0)
    bytes_written = int(progress.get("bytes_written") or 0)
    if total:
        stage = f"Загрузка работ: {fetched}/{total}"
    elif fetched:
        stage = f"Загрузка работ: {fetched}"
    elif files_seen or bytes_written:
        stage = str(progress.get("stage") or f"Загрузчик OpenAlex скачал файлов: {files_seen}")
    else:
        stage = str(progress.get("stage") or "Загрузчик OpenAlex запущен; точный процент появится после упаковки локальных файлов")
    update_progress(run_id, bounded, stage, progress)


def _allow_unchecked_download() -> bool:
    return os.environ.get("OPENALEX_DSS_ALLOW_UNCHECKED_DOWNLOAD") == "1"


def _artifact_links(action: str, run_id: str, result: dict[str, Any] | None = None) -> dict[str, str]:
    result = result or {}
    if action == "fetch_slice_dump":
        return _dump_artifact_links(result.get("dump") if isinstance(result.get("dump"), dict) else {})
    if action == "build_from_openalex":
        build = result.get("build") if isinstance(result.get("build"), dict) else {}
        if build:
            return _run_artifact_links(run_id, build)
        fetch = result.get("fetch") if isinstance(result.get("fetch"), dict) else {}
        return _dump_artifact_links(fetch.get("dump") if isinstance(fetch.get("dump"), dict) else {})
    if action == "recalculate":
        return _run_artifact_links(run_id, result)
    return {}


def _run_artifact_links(run_id: str, result: dict[str, Any]) -> dict[str, str]:
    archive = result.get("archive") if isinstance(result.get("archive"), dict) else {}
    run_prefix = _relative_data_artifact(archive.get("run_dir")) or f"runs/{run_id}"
    copied = archive.get("copied") if isinstance(archive.get("copied"), dict) else {}

    def copied_or_default(rel: str) -> str:
        return _relative_data_artifact(copied.get(rel)) or f"{run_prefix}/{rel}"

    return {
        "slice_passport": copied_or_default("passports/slice_passport.json"),
        "calculation_passport": copied_or_default("passports/calculation_passport.json"),
        "quality_report": copied_or_default("passports/quality_report.json"),
        "indices": copied_or_default("tables/indices.csv"),
        "ratings": copied_or_default("tables/ratings.csv"),
        "report_bundle": f"{run_prefix}/reports",
    }


def _dump_artifact_links(dump: dict[str, Any]) -> dict[str, str]:
    raw_jsonl = str(dump.get("raw_jsonl") or "").strip()
    if not raw_jsonl:
        return {}
    manifest = str(dump.get("dump_manifest") or dump.get("manifest_path") or Path(raw_jsonl).with_name("dump_manifest.json"))
    links = {
        "raw_jsonl": _relative_data_artifact(raw_jsonl),
        "dump_manifest": _relative_data_artifact(manifest),
    }
    files_manifest = str(dump.get("files_manifest") or "").strip()
    if files_manifest:
        links["files_manifest"] = _relative_data_artifact(files_manifest)
    return {key: value for key, value in links.items() if value}


def _relative_data_artifact(path: Any) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    candidate = Path(raw)
    try:
        return str(candidate.resolve().relative_to(DATA.resolve()))
    except (OSError, ValueError):
        return raw
