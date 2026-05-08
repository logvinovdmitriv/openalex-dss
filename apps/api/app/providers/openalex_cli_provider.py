from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from app.core.paths import DATA, SRC

import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_dss.io_utils import ensure_dir, sha256_file, write_json  # noqa: E402
from openalex_dss.openalex import build_filter, cli_download_signature, corpus_signature, download_consistency  # noqa: E402


def cli_status(api_key_env: str = "OPENALEX_API_KEY") -> dict[str, Any]:
    executable = shutil.which("openalex")
    key_env = str(api_key_env or "OPENALEX_API_KEY").strip() or "OPENALEX_API_KEY"
    return {
        "available": bool(executable),
        "executable": executable or "",
        "api_key_env": key_env,
        "api_key_configured": bool(os.environ.get(key_env)),
        "api_key_required_for_remote_download": False,
        "install": "pip install openalex-official",
        "purpose": "скачивание выбранного среза OpenAlex локальным загрузчиком; ключ передается только если пользователь явно его указал",
    }


def download_works_metadata(
    cfg: Any,
    *,
    api_key: str,
    out_dir: str | Path | None = None,
    estimate: dict[str, Any] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    cancel_callback: Callable[[], bool] | None = None,
    max_download_bytes: int = 0,
) -> dict[str, Any]:
    status = cli_status()
    if not status["available"]:
        raise RuntimeError("Загрузчик OpenAlex не установлен. Установите его локально: pip install openalex-official")
    consistency = download_consistency(cfg)
    if consistency.get("compatible") is False:
        raise ValueError("; ".join(consistency.get("reasons") or []) or "Этот срез нельзя скачать установленным загрузчиком OpenAlex.")

    filter_value = build_filter(cfg)
    if not filter_value:
        raise ValueError("Для скачивания среза нужен конкретный фильтр OpenAlex, чтобы не запустить неограниченную загрузку.")

    base_dir = ensure_dir(Path(out_dir) if out_dir else DATA / "raw/openalex_cli" / cfg.slice_name)
    files_dir = ensure_dir(base_dir / "files")
    raw_path = base_dir / "works.jsonl.gz"
    dump_manifest_path = base_dir / "dump_manifest.json"
    failed_dump_manifest_path = base_dir / "dump_manifest_failed.json"
    stdout_path = base_dir / "openalex_cli_stdout.log"
    stderr_path = base_dir / "openalex_cli_stderr.log"
    manifest_path = base_dir / "files_manifest.json"
    started_at = datetime.now(timezone.utc)
    command = [
        str(status["executable"]),
        "download",
        "--output",
        str(files_dir),
        "--filter",
        filter_value,
    ]
    if api_key.strip():
        command[2:2] = ["--api-key", api_key.strip()]
    public_command = [part if part != api_key else "***" for part in command]
    cli_version = _cli_version(str(status["executable"]))
    current_corpus_signature = corpus_signature(cfg)
    current_download_signature = cli_download_signature(cfg)
    estimate_signature = str((estimate or {}).get("estimate_signature") or current_corpus_signature)
    accepted_estimate_signature = str((estimate or {}).get("accepted_estimate_signature") or "")
    accepted_download_signature = str((estimate or {}).get("accepted_download_signature") or "")
    planned_records = int(((estimate or {}).get("estimate_count") or 0))
    planned_raw_bytes = int(((estimate or {}).get("estimated_cli_metadata_bytes") or (estimate or {}).get("estimated_raw_bytes_p90") or (estimate or {}).get("estimated_raw_bytes") or 0))
    estimate_signature_verified = estimate_signature == current_corpus_signature
    accepted_estimate_signature_verified = bool(accepted_estimate_signature and accepted_estimate_signature == current_corpus_signature)
    download_signature_verified = bool(accepted_download_signature and accepted_download_signature == current_download_signature)

    if progress_callback:
        progress_callback({
            "percent": 25,
            "stage": "Загрузка среза началась; ожидаем первые файлы",
            "target_records": planned_records or None,
            "estimated_raw_bytes": planned_raw_bytes or None,
            "external_progress": True,
        })

    download_result = _run_cli_download(
        command,
        base_dir=base_dir,
        files_dir=files_dir,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        started_at=started_at,
        planned_records=planned_records,
        planned_raw_bytes=planned_raw_bytes,
        progress_callback=progress_callback,
        cancel_callback=cancel_callback,
        max_download_bytes=max_download_bytes,
    )
    if isinstance(download_result, tuple):
        completed, stop_reason = download_result
    else:  # Test doubles and older internal callers may return only a CompletedProcess-like object.
        completed, stop_reason = download_result, "cli_completed"
    partial_stop = stop_reason in {"user_cancelled", "size_limit_reached"}
    if completed.returncode != 0 and not partial_stop:
        stderr_text = stderr_path.read_text(encoding="utf-8") if stderr_path.exists() else ""
        stdout_text = stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else ""
        raise RuntimeError((stderr_text or stdout_text or "Загрузка OpenAlex завершилась ошибкой").strip())

    if progress_callback:
        progress_callback({"percent": 82, "stage": "Упаковка файлов OpenAlex", "fetched": 0})

    try:
        records, files_manifest = _pack_work_json_files(files_dir, raw_path, strict=not partial_stop, progress_callback=progress_callback, manifest_path=manifest_path)
    except Exception as exc:
        finished_at = datetime.now(timezone.utc)
        failed_manifest = {
            "slice_id": cfg.slice_name,
            "dump_id": f"dump_failed_{cfg.slice_name}",
            "source_mode": "openalex_cli",
            "source": "Загрузка работ OpenAlex",
            "created_at_utc": finished_at.isoformat(),
            "download_started_at_utc": started_at.isoformat(),
            "download_finished_at_utc": finished_at.isoformat(),
            "elapsed_seconds": round((finished_at - started_at).total_seconds(), 3),
            "openalex_request": {"filter": filter_value, "search": "", "command": public_command, "content": "metadata_only"},
            "openalex_cli": {
                "executable": status["executable"],
                "version": cli_version,
                "stdout_log": str(stdout_path),
                "stderr_log": str(stderr_path),
            },
            "signatures": {
                "estimate_signature": estimate_signature,
                "download_signature": current_download_signature,
                "corpus_signature": current_corpus_signature,
                "accepted_estimate_signature": accepted_estimate_signature or None,
                "accepted_download_signature": accepted_download_signature or None,
                "estimate_signature_verified": estimate_signature_verified,
                "accepted_estimate_signature_verified": accepted_estimate_signature_verified,
                "download_signature_verified": download_signature_verified,
                "download_equivalence": consistency.get("download_equivalence"),
                "compatible": bool(consistency.get("compatible")),
            },
            "records_expected": planned_records or None,
            "records_downloaded": 0,
            "no_data": False,
            "stop_reason": "cli_pack_failed",
            "scientific_completeness": "failed",
            "allowed_for_final_analysis": False,
            "raw_jsonl": str(raw_path),
            "files_manifest": str(manifest_path),
            "error": str(exc),
        }
        write_json(failed_dump_manifest_path, failed_manifest)
        raise
    checksum = sha256_file(raw_path)
    dump_id = f"dump_{checksum[:16]}" if checksum else f"dump_{cfg.slice_name}"
    finished_at = datetime.now(timezone.utc)
    actual_raw_bytes = raw_path.stat().st_size
    completeness = "partial" if partial_stop and records > 0 else "complete" if records > 0 else "empty"
    allowed_for_final_analysis = (
        bool(consistency.get("compatible"))
        and estimate_signature_verified
        and accepted_estimate_signature_verified
        and download_signature_verified
        and records > 0
        and completeness == "complete"
    )
    dump_manifest = {
        "slice_id": cfg.slice_name,
        "dump_id": dump_id,
        "source_mode": "openalex_cli",
        "source": "Загрузка работ OpenAlex",
        "created_at_utc": finished_at.isoformat(),
        "download_started_at_utc": started_at.isoformat(),
        "download_finished_at_utc": finished_at.isoformat(),
        "elapsed_seconds": round((finished_at - started_at).total_seconds(), 3),
        "openalex_request": {
            "filter": filter_value,
            "search": "",
            "command": public_command,
            "content": "metadata_only",
        },
        "openalex_cli": {
            "executable": status["executable"],
            "version": cli_version,
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
        },
        "signatures": {
            "estimate_signature": estimate_signature,
            "download_signature": current_download_signature,
            "corpus_signature": current_corpus_signature,
            "accepted_estimate_signature": accepted_estimate_signature or None,
            "accepted_download_signature": accepted_download_signature or None,
            "estimate_signature_verified": estimate_signature_verified,
            "accepted_estimate_signature_verified": accepted_estimate_signature_verified,
            "download_signature_verified": download_signature_verified,
            "download_equivalence": consistency.get("download_equivalence"),
            "compatible": bool(consistency.get("compatible")),
        },
        "records_expected": planned_records or None,
        "records_downloaded": records,
        "records_delta": (records - planned_records) if planned_records else None,
        "no_data": records == 0,
        "bytes_written": actual_raw_bytes,
        "estimated_raw_bytes": planned_raw_bytes or None,
        "actual_vs_estimate_ratio": round(actual_raw_bytes / planned_raw_bytes, 4) if planned_raw_bytes else None,
        "stop_reason": stop_reason,
        "scientific_completeness": completeness,
        "usable_for_exploratory_analysis": records > 0,
        "allowed_for_final_analysis": allowed_for_final_analysis,
        "raw_jsonl": str(raw_path),
        "raw_jsonl_sha256": checksum,
        "files_manifest": str(manifest_path),
        "used_api_key": bool(api_key.strip()),
        "execution_plan": {
            "strategy": "openalex_cli_filtered_metadata",
            "checkpointing": True,
            "adaptive_rate_limiting": True,
            "parallel_downloads": True,
            "estimate_signature_verified": estimate_signature_verified,
            "accepted_estimate_signature_verified": accepted_estimate_signature_verified,
            "download_signature_verified": download_signature_verified,
        },
        "storage_plan": {
            "download_base_dir": str(base_dir),
            "cli_output_dir": str(files_dir),
            "raw_jsonl": str(raw_path),
            "raw_size_mb": round(actual_raw_bytes / (1024 * 1024), 3),
            "cleanup_policy": "keep_cli_files_and_packed_jsonl_gz",
            "kept_raw_files": True,
            "max_download_bytes": max_download_bytes or None,
        },
    }
    write_json(dump_manifest_path, dump_manifest)

    if progress_callback:
        stage = "Частичный локальный срез упакован" if completeness == "partial" else "Локальный срез упакован"
        progress_callback({"percent": 95, "stage": stage, "fetched": records, "stop_reason": stop_reason})

    return dump_manifest


def _pack_work_json_files(
    files_dir: Path,
    raw_path: Path,
    *,
    strict: bool = True,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    manifest_path: Path | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    records = 0
    manifest: list[dict[str, Any]] = []
    errors: list[str] = []
    candidates = sorted(path for path in files_dir.rglob("*") if path.is_file() and _supported_metadata_file(path))
    with gzip.open(raw_path, "wt", encoding="utf-8", newline="\n") as handle:
        for index, path in enumerate(candidates, start=1):
            before = records
            error = ""
            try:
                for payload in _iter_work_payloads(path):
                    if not str(payload.get("id") or "").startswith("https://openalex.org/W"):
                        continue
                    handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
                    records += 1
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                error = str(exc)
                errors.append(f"{path.relative_to(files_dir)}: {error}")
            file_records = records - before
            item = {
                "path": str(path.relative_to(files_dir)),
                "bytes": path.stat().st_size,
                "records": file_records,
                "sha256": sha256_file(path) if file_records else "",
                "status": "failed" if error else "ok",
            }
            if error:
                item["parse_error"] = error
            manifest.append(item)
            if progress_callback and (index == len(candidates) or records % 500 == 0):
                progress_callback({"percent": 82, "stage": f"Упаковано {records} работ", "fetched": records, "files_seen": index})
    if manifest_path:
        write_json(manifest_path, {"files": manifest, "records": records, "errors": errors, "status": "failed" if errors else "ok"})
    if strict and errors:
        raise ValueError("Не удалось разобрать файлы загрузчика OpenAlex: " + "; ".join(errors[:5]))
    return records, manifest


def _run_cli_download(
    command: list[str],
    *,
    base_dir: Path,
    files_dir: Path,
    stdout_path: Path,
    stderr_path: Path,
    started_at: datetime,
    planned_records: int,
    planned_raw_bytes: int,
    progress_callback: Callable[[dict[str, Any]], None] | None,
    cancel_callback: Callable[[], bool] | None,
    max_download_bytes: int,
) -> tuple[subprocess.CompletedProcess[str], str]:
    stop_reason = "cli_completed"
    with stdout_path.open("w", encoding="utf-8", newline="\n") as stdout_handle, stderr_path.open("w", encoding="utf-8", newline="\n") as stderr_handle:
        process = subprocess.Popen(command, cwd=str(base_dir), text=True, stdout=stdout_handle, stderr=stderr_handle)
        while process.poll() is None:
            time.sleep(5)
            snapshot = _cli_download_snapshot(files_dir)
            elapsed = max(0, int((datetime.now(timezone.utc) - started_at).total_seconds()))
            if cancel_callback and cancel_callback():
                stop_reason = "user_cancelled"
                _terminate_process_group(process)
            elif max_download_bytes > 0 and snapshot["bytes_written"] >= max_download_bytes:
                stop_reason = "size_limit_reached"
                _terminate_process_group(process)
            if progress_callback:
                percent = _cli_download_percent(snapshot["bytes_written"], planned_raw_bytes, elapsed)
                stage = _cli_download_stage(snapshot["files_seen"], snapshot["bytes_written"], elapsed)
                if stop_reason == "user_cancelled":
                    stage = "Остановка по запросу пользователя; готовим частичный срез"
                elif stop_reason == "size_limit_reached":
                    stage = "Достигнут лимит загрузки; готовим частичный срез"
                progress_callback({
                    "percent": percent,
                    "stage": stage,
                    "fetched": 0,
                    "files_seen": snapshot["files_seen"],
                    "bytes_written": snapshot["bytes_written"],
                    "elapsed_seconds": elapsed,
                    "target_records": planned_records or None,
                    "estimated_raw_bytes": planned_raw_bytes or None,
                    "max_download_bytes": max_download_bytes or None,
                    "stop_reason": stop_reason,
                    "external_progress": True,
                })
        return_code = process.wait()
    return subprocess.CompletedProcess(command, return_code), stop_reason


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        process.terminate()
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
    except ProcessLookupError:
        return


def _cli_download_snapshot(files_dir: Path) -> dict[str, int]:
    files_seen = 0
    bytes_written = 0
    if not files_dir.exists():
        return {"files_seen": 0, "bytes_written": 0}
    for path in files_dir.rglob("*"):
        if not path.is_file():
            continue
        files_seen += 1
        try:
            bytes_written += path.stat().st_size
        except OSError:
            continue
    return {"files_seen": files_seen, "bytes_written": bytes_written}


def _cli_download_percent(bytes_written: int, planned_raw_bytes: int, elapsed_seconds: int) -> int:
    if planned_raw_bytes > 0 and bytes_written > 0:
        return min(80, max(30, 30 + int((bytes_written / planned_raw_bytes) * 45)))
    return min(75, 25 + elapsed_seconds // 15)


def _cli_download_stage(files_seen: int, bytes_written: int, elapsed_seconds: int) -> str:
    mb = round(bytes_written / (1024 * 1024), 1)
    if files_seen or bytes_written:
        return f"Загрузка среза: {files_seen} файлов, {mb} МБ на диске"
    return f"Загрузчик OpenAlex запущен, ожидание первых файлов; прошло {elapsed_seconds} сек."


def _supported_metadata_file(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".json") or name.endswith(".jsonl") or name.endswith(".jsonl.gz")


def _iter_work_payloads(path: Path) -> Iterator[dict[str, Any]]:
    if path.name.lower().endswith(".jsonl.gz"):
        with gzip.open(path, "rt", encoding="utf-8", newline="\n") as handle:
            for line_no, line in enumerate(handle, start=1):
                if line.strip():
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        yield payload
                    else:
                        raise ValueError(f"{path.name}:{line_no} is not a JSON object")
        return
    if path.name.lower().endswith(".jsonl"):
        with path.open("rt", encoding="utf-8", newline="\n") as handle:
            for line_no, line in enumerate(handle, start=1):
                if line.strip():
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        yield payload
                    else:
                        raise ValueError(f"{path.name}:{line_no} is not a JSON object")
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        for item in payload["results"]:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(payload, dict):
        yield payload


def _cli_version(executable: str) -> str:
    completed = subprocess.run([executable, "--version"], text=True, capture_output=True, check=False)
    return (completed.stdout or completed.stderr or "").strip()
