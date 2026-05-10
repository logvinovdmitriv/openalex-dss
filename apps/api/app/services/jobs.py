from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # POSIX file locking is available in the supported local macOS/Linux setup.
    import fcntl
except ImportError:  # pragma: no cover - defensive fallback for non-POSIX environments
    fcntl = None  # type: ignore[assignment]

from app.core.paths import DATA, ROOT, SRC
from app.services.internal_payloads import normalize_internal_pipeline_payload
from app.services import analysis_jobs, materialization_jobs


RUNS_DIR = DATA / "runs"
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
        "progress_percent": None,
        "progress_stage": "queued",
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
        "error": None,
        "payload": _public_payload(payload),
        "result": None,
        "artifacts": {},
    }
    _write_execution_payload(run_id, action, payload)
    _save(doc)
    with _LOCK:
        _RUN_EXECUTION_PAYLOADS[run_id] = (action, dict(payload))
    if autostart:
        start_run(run_id)
    return doc


def start_run(run_id: str) -> dict[str, Any]:
    doc = get_run(run_id)
    status = str(doc.get("status") or "")
    if status == "running" and _pid_alive(_int_value(doc.get("worker_pid"))):
        return doc
    if status != "queued":
        return doc
    if _active_worker_count(exclude_run_id=run_id) >= _max_active_workers():
        doc["progress_stage"] = "queued_waiting_for_worker_slot"
        _save(doc)
        return doc
    with _LOCK:
        execution = _RUN_EXECUTION_PAYLOADS.get(run_id)
    action, payload = execution if execution else _read_execution_payload(run_id)
    if not action:
        raise ValueError(f"Run {run_id} has no executable action")
    doc["status"] = "running"
    doc["progress_stage"] = "starting"
    doc["cancel_requested"] = False
    _cancel_path(run_id).unlink(missing_ok=True)
    _write_execution_payload(run_id, action, payload)
    proc = _spawn_worker(run_id)
    doc["worker_pid"] = proc.pid
    doc["worker_started_at"] = _now()
    _save(doc)
    return doc


def cancel_run(run_id: str) -> dict[str, Any]:
    doc = get_run(run_id)
    status = str(doc.get("status") or "")
    if status not in {"queued", "running", "cancelling"}:
        return doc
    _cancel_path(run_id).write_text(
        json.dumps({"requested_at": _now(), "mode": "keep_partial"}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    doc["cancel_requested"] = True
    if status == "queued":
        doc["status"] = "cancelled"
        doc["progress_percent"] = None
        doc["progress_stage"] = "cancelled"
        doc["finished_at"] = _now()
        _save(doc)
        _cancel_path(run_id).unlink(missing_ok=True)
        _delete_execution_payload(run_id)
        with _LOCK:
            _RUN_EXECUTION_PAYLOADS.pop(run_id, None)
        return doc
    doc["status"] = "cancelling"
    doc["progress_stage"] = "Остановка загрузки; уже скачанные файлы будут упакованы как частичный срез"
    _save(doc)
    return doc


def get_run(run_id: str) -> dict[str, Any]:
    with _LOCK:
        if run_id in _RUNS:
            cached = dict(_RUNS[run_id])
            if str(cached.get("status") or "") not in {"queued", "running", "cancelling"}:
                return cached
    path = _run_path(run_id)
    if not path.exists():
        raise KeyError(run_id)
    return _normalize_loaded_run(json.loads(path.read_text(encoding="utf-8")))


def update_progress(run_id: str, percent: int | None, stage: str, extra: dict[str, Any] | None = None) -> None:
    doc = get_run(run_id)
    doc["progress_percent"] = None if percent is None else max(0, min(100, int(percent)))
    doc["progress_stage"] = stage
    doc["worker_heartbeat_at"] = _now()
    if percent is not None:
        phase_id = _phase_id_for_stage(str(doc.get("action") or ""), stage)
        if phase_id:
            doc.setdefault("progress", {})[f"{phase_id}_percent"] = doc["progress_percent"]
    if extra:
        doc.setdefault("progress", {}).update(extra)
    _save(doc)


def cancel_requested(run_id: str) -> bool:
    return _cancel_path(run_id).exists()


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
    doc.update({"status": "running", "progress_percent": None, "progress_stage": "preparing", "started_at": _now(), "worker_heartbeat_at": _now(), "error": None})
    _save(doc)
    try:
        doc = _current_doc(run_id, fallback=doc)
        doc.update({"progress_percent": None, "progress_stage": _stage_for_action(action), "worker_heartbeat_at": _now()})
        _save(doc)
        result = _dispatch(run_id, action, payload)
        materialization_jobs.mark_completed(run_id, action, result, payload)
        partial = _result_is_partial(result)
        doc = _current_doc(run_id, fallback=doc)
        doc.update({
            "status": "completed",
            "progress_percent": 100,
            "progress_stage": "partial_completed" if partial else "completed",
            "finished_at": _now(),
            "worker_heartbeat_at": _now(),
            "result": result,
            "artifacts": _artifact_links(action, run_id, result),
        })
    except Exception as exc:  # pragma: no cover - defensive job boundary
        error_text = _safe_error_text(str(exc))
        materialization_jobs.mark_failed(run_id, action, error_text, payload)
        doc = _current_doc(run_id, fallback=doc)
        if cancel_requested(run_id):
            doc.update({"status": "cancelled", "progress_percent": None, "progress_stage": "cancelled", "finished_at": _now(), "worker_heartbeat_at": _now(), "error": error_text})
        else:
            doc.update({"status": "failed", "progress_percent": None, "progress_stage": "failed", "finished_at": _now(), "worker_heartbeat_at": _now(), "error": error_text})
    _save(doc)
    if str(doc.get("status") or "") in {"completed", "failed", "cancelled"}:
        _cancel_path(run_id).unlink(missing_ok=True)
    _delete_execution_payload(run_id)
    with _LOCK:
        _RUN_EXECUTION_PAYLOADS.pop(run_id, None)
    _start_next_queued_run()


def _dispatch(run_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = normalize_internal_pipeline_payload({**payload, "run_id": run_id})
    if action in analysis_jobs.ANALYSIS_ACTIONS:
        return analysis_jobs.dispatch(
            run_id,
            action,
            payload,
            update_progress_callback=lambda percent, stage, extra=None: update_progress(run_id, percent, stage, extra),
        )
    if action in materialization_jobs.SUPPORTED_MATERIALIZATION_ACTIONS:
        return materialization_jobs.dispatch(
            run_id,
            action,
            payload,
            download_progress_callback=lambda progress: _download_progress(run_id, progress),
            update_progress_callback=lambda percent, stage, extra=None: update_progress(run_id, percent, stage, extra),
            cancel_callback=lambda: cancel_requested(run_id),
            allow_unchecked_download=_allow_unchecked_download(),
        )
    raise ValueError(f"Unsupported run action: {action}")


def _save(doc: dict[str, Any]) -> None:
    run_id = str(doc["run_id"])
    path = _run_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc["progress_phases"] = _progress_phases(doc)
    payload = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with _file_lock(_lock_path(run_id)):
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(payload, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    with _LOCK:
        _RUNS[run_id] = dict(doc)


def _normalize_loaded_run(doc: dict[str, Any]) -> dict[str, Any]:
    status = str(doc.get("status") or "")
    run_id = str(doc.get("run_id") or "")
    worker_alive = _pid_alive(_int_value(doc.get("worker_pid")))
    if status == "failed" and "прервана при остановке сервера" in str(doc.get("error") or ""):
        recovered = _recover_completed_run(doc)
        if recovered:
            return recovered
        recovered = _recover_materialization_dump_run(doc)
        if recovered:
            return recovered
    if status in {"running", "cancelling"} and not worker_alive:
        recovered = _recover_completed_run(doc)
        if recovered:
            return recovered
        recovered = _recover_materialization_dump_run(doc)
        if recovered:
            return recovered
        doc = dict(doc)
        doc["status"] = "failed"
        doc["progress_percent"] = None
        doc["progress_stage"] = "failed"
        doc["finished_at"] = doc.get("finished_at") or _now()
        doc["error"] = (
            "Задача была прервана при остановке сервера. "
            "Если локальный срез уже скачан, выберите его в списке срезов и запустите расчет индексов."
        )
        if run_id:
            _save(doc)
    doc["progress_phases"] = _progress_phases(doc)
    return doc


def _progress_phases(doc: dict[str, Any]) -> list[dict[str, Any]]:
    action = str(doc.get("action") or "")
    status = str(doc.get("status") or "")
    progress = doc.get("progress") if isinstance(doc.get("progress"), dict) else {}
    stage = str(doc.get("progress_stage") or progress.get("stage") or "")

    def percent(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return None

    def phase(phase_id: str, label: str, value: Any = None, *stage_tokens: str) -> dict[str, Any]:
        current_percent = percent(value)
        if status == "completed":
            state = "done"
            current_percent = 100 if current_percent is not None else current_percent
        elif status in {"failed", "cancelled"}:
            is_current = any(token and token in stage for token in (label, *stage_tokens))
            if current_percent == 100:
                state = "done"
            elif is_current or (current_percent is not None and current_percent > 0):
                state = "error"
            else:
                state = "pending"
        elif status == "queued":
            state = "pending"
        elif any(token and token in stage for token in (label, *stage_tokens)):
            state = "active"
        else:
            state = "pending"
        return {
            "id": phase_id,
            "label": label,
            "state": state,
            "percent": current_percent,
            "determinate": current_percent is not None,
        }

    if action == "build_from_openalex":
        return [
            phase("download", "Скачивание файлов", progress.get("download_percent"), "Загрузка"),
            phase("pack", "Упаковка среза", progress.get("pack_percent"), "Упаковка", "Упаковано"),
            phase("normalize", "Подготовка таблиц", progress.get("normalize_percent"), "Нормализация", "Подготовка таблиц"),
            phase("compute", "Расчет индексов", progress.get("compute_percent"), "Расчет"),
        ]
    if action == "fetch_slice_dump":
        return [
            phase("download", "Скачивание файлов", progress.get("download_percent"), "Загрузка"),
            phase("pack", "Упаковка среза", progress.get("pack_percent"), "Упаковка", "Упаковано"),
        ]
    if action == "repair_dump":
        return [
            phase("check", "Проверка файлов", progress.get("check_percent"), "Проверка"),
            phase("pack", "Упаковка среза", progress.get("pack_percent"), "Упаковка", "Упаковано"),
            phase("normalize", "Подготовка таблиц", progress.get("normalize_percent"), "Нормализация", "Подготовка таблиц"),
            phase("compute", "Расчет индексов", progress.get("compute_percent"), "Расчет"),
        ]
    if action == "backfill_truncated_authorships":
        return [
            phase("check", "Проверка файлов", progress.get("check_percent"), "Проверка"),
            phase("backfill", "Восстановление authorships", progress.get("backfill_percent"), "backfill", "Восстановление singleton"),
            phase("normalize", "Подготовка таблиц", progress.get("normalize_percent"), "Нормализация", "Подготовка таблиц"),
            phase("compute", "Расчет индексов", progress.get("compute_percent"), "Расчет"),
        ]
    if action == "recalculate":
        return [
            phase("check", "Проверка таблиц", progress.get("check_percent"), "Проверка"),
            phase("compute", "Расчет индексов", progress.get("compute_percent"), "Расчет"),
            phase("report", "Паспорт и отчет", progress.get("report_percent"), "Паспорт", "Отчет"),
        ]
    if action in {"bootstrap_analysis", "permutation_analysis", "convergence_analysis"}:
        return [
            phase("prepare", "Подготовка анализа", progress.get("prepare_percent"), "Подготовка"),
            phase("compute", "Расчет протокола", progress.get("compute_percent"), "Расчет", "bootstrap", "permutation", "convergence"),
            phase("write", "Сохранение артефактов", progress.get("write_percent"), "Сохранение"),
        ]
    return []


def _phase_id_for_stage(action: str, stage: str) -> str:
    text = str(stage or "")
    if action in {"build_from_openalex", "fetch_slice_dump"} and "Загрузка" in text:
        return "download"
    if "Упаков" in text or "Упаковано" in text:
        return "pack"
    if "backfill" in text or "Восстановление singleton" in text:
        return "backfill"
    if "Нормализация" in text or "Подготовка таблиц" in text:
        return "normalize"
    if "Расчет" in text:
        return "compute"
    if "Проверка" in text:
        return "check"
    if "Подготовка анализа" in text:
        return "prepare"
    if "Сохранение" in text:
        return "write"
    if "Паспорт" in text or "Отчет" in text:
        return "report"
    return ""


def _spawn_worker(run_id: str) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "apps/api"), str(SRC), env.get("PYTHONPATH", "")])
    log_path = _run_path(run_id).with_name("worker.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("ab")
    return subprocess.Popen(
        [sys.executable, "-m", "app.services.job_worker", run_id],
        cwd=str(ROOT / "apps/api"),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def execute_run_in_worker(run_id: str) -> None:
    action, payload = _read_execution_payload(run_id)
    if not action:
        raise ValueError(f"Run {run_id} has no executable payload")
    _delete_execution_payload(run_id)
    _execute(run_id, action, payload)


def _write_execution_payload(run_id: str, action: str, payload: dict[str, Any]) -> None:
    path = _execution_payload_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock(_lock_path(run_id)):
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(
            json.dumps({"action": action, "payload": payload}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        os.replace(tmp, path)


def _read_execution_payload(run_id: str) -> tuple[str, dict[str, Any]]:
    path = _execution_payload_path(run_id)
    if not path.exists():
        return "", {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return str(doc.get("action") or ""), dict(doc.get("payload") or {})


def _delete_execution_payload(run_id: str) -> None:
    _execution_payload_path(run_id).unlink(missing_ok=True)


def _execution_payload_path(run_id: str) -> Path:
    return _run_path(run_id).with_name("execution_payload.json")


def _cancel_path(run_id: str) -> Path:
    return _run_path(run_id).with_name("cancel.request.json")


def _lock_path(run_id: str) -> Path:
    return _run_path(run_id).with_name("run.lock")


@contextmanager
def _file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        state = _process_state(pid)
        return bool(state) and not state.startswith("Z")
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _process_state(pid: int) -> str:
    try:
        completed = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=1,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unknown"
    return completed.stdout.strip() or ""


def _int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _result_is_partial(result: dict[str, Any]) -> bool:
    dump = result.get("dump") if isinstance(result.get("dump"), dict) else {}
    fetch = result.get("fetch") if isinstance(result.get("fetch"), dict) else {}
    if not dump and isinstance(fetch.get("dump"), dict):
        dump = fetch["dump"]
    return str(dump.get("scientific_completeness") or "") == "partial"


def _recover_completed_run(doc: dict[str, Any]) -> dict[str, Any] | None:
    run_id = str(doc.get("run_id") or "")
    if not run_id:
        return None
    run_dir = RUNS_DIR / "".join(ch for ch in run_id if ch.isalnum() or ch in "_-")
    if not (run_dir / "passports/checksums.json").exists():
        return None
    recovered = dict(doc)
    recovered.update({
        "status": "completed",
        "progress_percent": 100,
        "progress_stage": "completed_recovered",
        "finished_at": recovered.get("finished_at") or _now(),
        "error": None,
        "artifacts": _run_artifact_links(run_id, {"archive": {"run_dir": str(run_dir)}}),
    })
    _save(recovered)
    return recovered


def _recover_materialization_dump_run(doc: dict[str, Any]) -> dict[str, Any] | None:
    action = str(doc.get("action") or "")
    if action not in {"fetch_slice_dump", "build_from_openalex"}:
        return None
    run_id = str(doc.get("run_id") or "")
    manifest = _recover_dump_manifest_for_run(doc)
    if not manifest:
        return None
    raw_jsonl = str(manifest.get("raw_jsonl") or "").strip()
    if not raw_jsonl or not Path(raw_jsonl).is_file() or int(manifest.get("records_downloaded") or 0) <= 0:
        return None
    try:
        from app.services import pipeline as pipeline_service

        eligibility = pipeline_service.analysis_eligibility_from_dump(manifest, dev_override=True)
    except Exception:
        eligibility = {}
    if action == "fetch_slice_dump":
        result = {"status": "ok", "mode": "fetch_slice_dump", "dump": manifest}
    else:
        result = {
            "fetch": {"status": "ok", "mode": "fetch_slice_dump", "dump": manifest},
            "build": None,
            "no_data": False,
            "analysis_eligibility": eligibility,
        }
    recovered = dict(doc)
    partial = str(manifest.get("scientific_completeness") or "") == "partial"
    recovered.update({
        "status": "completed",
        "progress_percent": 100,
        "progress_stage": "partial_completed_recovered" if partial else "download_completed_recovered",
        "finished_at": recovered.get("finished_at") or _now(),
        "worker_heartbeat_at": _now(),
        "error": None,
        "result": result,
        "artifacts": _artifact_links(action, run_id, result),
    })
    try:
        payload = recovered.get("payload") if isinstance(recovered.get("payload"), dict) else {}
        materialization_jobs.mark_completed(run_id, action, result, payload)
    except Exception:
        pass
    _save(recovered)
    return recovered


def _recover_dump_manifest_for_run(doc: dict[str, Any]) -> dict[str, Any]:
    candidates: list[Path] = []
    progress = doc.get("progress") if isinstance(doc.get("progress"), dict) else {}
    for key in ("source_path", "raw_jsonl"):
        raw = str(progress.get(key) or "").strip()
        if raw:
            candidates.append(Path(raw).with_name("dump_manifest.json"))
    result = doc.get("result") if isinstance(doc.get("result"), dict) else {}
    dump = result.get("dump") if isinstance(result.get("dump"), dict) else {}
    fetch = result.get("fetch") if isinstance(result.get("fetch"), dict) else {}
    if not dump and isinstance(fetch.get("dump"), dict):
        dump = fetch["dump"]
    for raw in (dump.get("dump_manifest"), dump.get("manifest_path")):
        if str(raw or "").strip():
            candidates.append(Path(str(raw)))
    raw_jsonl = str(dump.get("raw_jsonl") or "").strip()
    if raw_jsonl:
        candidates.append(Path(raw_jsonl).with_name("dump_manifest.json"))

    payload = doc.get("payload") if isinstance(doc.get("payload"), dict) else {}
    tokens = {
        _safe_token(doc.get("run_id")),
        _safe_token(payload.get("materialization_id")),
        _safe_token(payload.get("slice_name")),
    }
    tokens.discard("")
    raw_root = DATA / "raw" / "openalex_cli"
    if raw_root.exists() and tokens:
        for manifest_path in raw_root.glob("**/dump_manifest.json"):
            parts = {_safe_token(part) for part in manifest_path.parts}
            if parts & tokens:
                candidates.append(manifest_path)
    for manifest_path in candidates:
        manifest = _read_json_file(manifest_path)
        if manifest:
            return manifest
    return {}


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _safe_token(value: Any) -> str:
    return "".join(ch for ch in str(value or "").strip() if ch.isalnum() or ch in "_-.")


def _current_doc(run_id: str, *, fallback: dict[str, Any]) -> dict[str, Any]:
    path = _run_path(run_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(fallback)


def _active_worker_count(*, exclude_run_id: str = "") -> int:
    count = 0
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    for path in RUNS_DIR.glob("run_*/run_status.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if str(doc.get("run_id") or "") == exclude_run_id:
            continue
        if str(doc.get("status") or "") in {"running", "cancelling"} and _pid_alive(_int_value(doc.get("worker_pid"))):
            count += 1
    return count


def _max_active_workers() -> int:
    try:
        return max(1, min(8, int(os.environ.get("OPENALEX_DSS_MAX_ACTIVE_WORKERS", "1"))))
    except ValueError:
        return 1


def _start_next_queued_run() -> None:
    if _active_worker_count() >= _max_active_workers():
        return
    queued: list[tuple[str, str]] = []
    for path in RUNS_DIR.glob("run_*/run_status.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if str(doc.get("status") or "") == "queued":
            queued.append((str(doc.get("created_at") or ""), str(doc.get("run_id") or "")))
    for _, run_id in sorted(queued):
        if run_id:
            start_run(run_id)
            return


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


def _safe_error_text(text: str) -> str:
    cleaned = re.sub(r"([?&]api_key=)[^\s'\"&]+", r"\1***", text)
    if "Credits exhausted" in cleaned or "Rate limited" in cleaned or "429" in cleaned:
        return (
            "OpenAlex ограничил запросы к API. Уже скачанные файлы сохранены; "
            "повторите скачивание позже или восстановите частичный срез."
        )
    return cleaned


def _stage_for_action(action: str) -> str:
    return {
        "fetch_slice_dump": "Загрузка локального среза",
        "build_from_openalex": "Загрузка и построение локального среза",
        "repair_dump": "Восстановление локального среза",
        "backfill_truncated_authorships": "Восстановление authorships",
        "recalculate": "Расчет индексов",
        "bootstrap_analysis": "Bootstrap-анализ устойчивости",
        "permutation_analysis": "Permutation-анализ совпадения рейтингов",
        "convergence_analysis": "Анализ сходимости корпуса",
    }.get(action, "running")


def _download_progress(run_id: str, progress: dict[str, Any]) -> None:
    action = str(get_run(run_id).get("action") or "")
    raw_percent = progress.get("percent")
    phase_percent = None
    if raw_percent is not None:
        try:
            phase_percent = max(0, min(100, int(raw_percent)))
        except (TypeError, ValueError):
            phase_percent = None
    scope = str(progress.get("progress_scope") or ("download" if action in {"build_from_openalex", "fetch_slice_dump"} else "")).strip()
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
        stage = str(progress.get("stage") or "Загрузчик OpenAlex запущен; ожидаем первые локальные файлы")
    extra = {key: value for key, value in progress.items() if key != "percent"}
    if phase_percent is not None:
        if scope == "pack":
            extra["pack_percent"] = phase_percent
        elif scope == "download":
            extra["download_percent"] = phase_percent
        else:
            extra["phase_percent"] = phase_percent
    update_progress(run_id, None, stage, extra)


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
    if action == "repair_dump":
        build = result.get("build") if isinstance(result.get("build"), dict) else {}
        return _run_artifact_links(run_id, build) if build else {}
    if action == "backfill_truncated_authorships":
        build = result.get("build") if isinstance(result.get("build"), dict) else {}
        links = _run_artifact_links(run_id, build) if build else {}
        backfill = result.get("backfill") if isinstance(result.get("backfill"), dict) else {}
        if backfill.get("manifest_path"):
            links["backfill_manifest"] = _relative_data_artifact(backfill.get("manifest_path"))
        return links
    if action == "recalculate":
        return _run_artifact_links(run_id, result)
    if action in {"bootstrap_analysis", "permutation_analysis", "convergence_analysis"}:
        artifact = str((result or {}).get("artifact_path") or "").strip()
        return {"analysis_artifact": _relative_data_artifact(artifact)} if artifact else {}
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
