from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.providers import openalex_cli_provider
from app.services import pipeline
from app.services.internal_payloads import normalize_internal_pipeline_payload


MATERIALIZATION_ACTIONS = {"fetch_slice_dump", "build_from_openalex", "repair_dump"}
SUPPORTED_MATERIALIZATION_ACTIONS = MATERIALIZATION_ACTIONS
REQUIRES_ACCEPTED_SIGNATURE_ACTIONS = {"build_from_openalex", "fetch_slice_dump"}
MATERIALIZATION_LIFECYCLE_ACTIONS = {"build_from_openalex", "fetch_slice_dump", "repair_dump"}

DownloadProgressCallback = Callable[[dict[str, Any]], None]
StageProgressCallback = Callable[[int, str, dict[str, Any] | None], None]
CancelCallback = Callable[[], bool]


def dispatch(
    run_id: str,
    action: str,
    payload: dict[str, Any],
    *,
    download_progress_callback: DownloadProgressCallback | None = None,
    update_progress_callback: StageProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
    allow_unchecked_download: bool = False,
) -> dict[str, Any]:
    payload = normalize_internal_pipeline_payload(payload)
    if action == "fetch_slice_dump":
        return pipeline.fetch_slice_dump(
            payload,
            progress_callback=download_progress_callback,
            cancel_callback=cancel_callback,
            require_accepted_signatures=not allow_unchecked_download,
        )
    if action == "build_from_openalex":
        return _build_from_openalex(
            run_id,
            payload,
            download_progress_callback=download_progress_callback,
            update_progress_callback=update_progress_callback,
            cancel_callback=cancel_callback,
            allow_unchecked_download=allow_unchecked_download,
        )
    if action == "repair_dump":
        return _repair_dump(run_id, payload, update_progress_callback=update_progress_callback)
    raise ValueError(f"Unsupported materialization job action: {action}")


def _build_from_openalex(
    run_id: str,
    payload: dict[str, Any],
    *,
    download_progress_callback: DownloadProgressCallback | None,
    update_progress_callback: StageProgressCallback | None,
    cancel_callback: CancelCallback | None,
    allow_unchecked_download: bool,
) -> dict[str, Any]:
    fetched = pipeline.fetch_slice_dump(
        payload,
        progress_callback=download_progress_callback,
        cancel_callback=cancel_callback,
        require_accepted_signatures=not allow_unchecked_download,
    )
    dump = fetched.get("dump") or {}
    raw_jsonl = str(dump.get("raw_jsonl") or "").strip()
    if not raw_jsonl or dump.get("no_data"):
        return {"fetch": fetched, "build": None, "no_data": True}
    analysis_eligibility = pipeline.analysis_eligibility_from_dump(dump, dev_override=allow_unchecked_download)
    partial_ok = str(dump.get("scientific_completeness") or "") == "partial" and bool(dump.get("usable_for_exploratory_analysis"))
    if not analysis_eligibility["allowed_for_final_analysis"] and not (allow_unchecked_download or partial_ok):
        raise ValueError("Срез не допущен к анализу: скачивание не завершилось и нет пригодной частичной выборки.")
    if update_progress_callback:
        update_progress_callback(86, "Нормализация локального среза", {"source_path": raw_jsonl})
    built = pipeline.import_local_file(
        normalize_internal_pipeline_payload(
            {
                **payload,
                "source_path": raw_jsonl,
                "api_key": None,
                "run_id": run_id,
                "dump_id": dump.get("dump_id"),
                "dump_manifest": dump,
                "analysis_eligibility": analysis_eligibility,
                "import_mode": "final_reproducible" if analysis_eligibility["allowed_for_final_analysis"] else "exploratory",
                "active_context_source": "materialization",
            }
        ),
        progress_callback=update_progress_callback,
        compute_progress_base=90,
    )
    return {"fetch": fetched, "build": built, "no_data": False, "analysis_eligibility": analysis_eligibility}


def _repair_dump(
    run_id: str,
    payload: dict[str, Any],
    *,
    update_progress_callback: StageProgressCallback | None,
) -> dict[str, Any]:
    dump = payload.get("dump_manifest") if isinstance(payload.get("dump_manifest"), dict) else {}
    raw_jsonl = str(payload.get("source_path") or dump.get("raw_jsonl") or "").strip()
    raw_jsonl, dump = _ensure_repair_raw_file(dump, raw_jsonl, update_progress_callback)
    if update_progress_callback:
        update_progress_callback(25, "Проверка локального файла среза", {"source_path": raw_jsonl})
    analysis_eligibility = pipeline.analysis_eligibility_from_dump(dump, dev_override=True)
    built = pipeline.import_local_file(
        normalize_internal_pipeline_payload(
            {
                **payload,
                "source_path": raw_jsonl,
                "api_key": None,
                "run_id": run_id,
                "dump_id": dump.get("dump_id") or payload.get("dump_id"),
                "dump_manifest": dump,
                "analysis_eligibility": analysis_eligibility,
                "import_mode": "final_reproducible" if analysis_eligibility["allowed_for_final_analysis"] else "exploratory",
                "active_context_source": "dump_repair",
            }
        ),
        progress_callback=update_progress_callback,
        compute_progress_base=35,
    )
    return {"status": "ok", "mode": "repair_dump", "dump": dump, "build": built, "analysis_eligibility": analysis_eligibility}


def _ensure_repair_raw_file(
    dump: dict[str, Any],
    raw_jsonl: str,
    update_progress_callback: StageProgressCallback | None,
) -> tuple[str, dict[str, Any]]:
    raw_path = Path(raw_jsonl).expanduser() if raw_jsonl else Path("")
    if raw_jsonl and raw_path.is_file():
        return str(raw_path), dump
    files_dir_raw = str(dump.get("cli_files_dir") or "").strip()
    if not files_dir_raw:
        raise ValueError("Для восстановления нужен локальный файл среза или папка скачанных файлов OpenAlex.")
    files_dir = Path(files_dir_raw).expanduser()
    if not files_dir.is_dir():
        raise ValueError("Папка скачанных файлов OpenAlex не найдена.")
    base_dir = files_dir.parent
    raw_path = Path(raw_jsonl).expanduser() if raw_jsonl else base_dir / "works.jsonl.gz"
    files_manifest_path = Path(str(dump.get("files_manifest") or base_dir / "files_manifest.json"))
    if update_progress_callback:
        update_progress_callback(28, "Упаковка уже скачанных файлов OpenAlex", {"source_path": str(raw_path), "files_dir": str(files_dir)})
    records, _ = openalex_cli_provider.pack_existing_cli_files(
        files_dir,
        raw_path,
        manifest_path=files_manifest_path,
        progress_callback=(
            lambda progress: update_progress_callback(
                min(34, max(29, int(progress.get("percent") or 29))),
                str(progress.get("stage") or "Упаковка уже скачанных файлов OpenAlex"),
                {key: value for key, value in progress.items() if key != "percent"},
            )
            if update_progress_callback
            else None
        ),
    )
    if records <= 0:
        raise ValueError("В скачанных файлах OpenAlex не найдено работ для восстановления среза.")
    checksum = openalex_cli_provider.sha256_file(raw_path)
    finished_at = datetime.now(timezone.utc).isoformat()
    restored = {
        **dump,
        "dump_id": f"dump_{checksum[:16]}" if checksum else str(dump.get("dump_id") or base_dir.name),
        "raw_jsonl": str(raw_path),
        "raw_jsonl_sha256": checksum,
        "records_downloaded": records,
        "bytes_written": raw_path.stat().st_size,
        "files_manifest": str(files_manifest_path),
        "dump_manifest": str(base_dir / "dump_manifest.json"),
        "manifest_path": str(base_dir / "dump_manifest.json"),
        "download_finished_at_utc": dump.get("download_finished_at_utc") or finished_at,
        "created_at_utc": dump.get("created_at_utc") or finished_at,
        "scientific_completeness": dump.get("scientific_completeness") or "partial",
        "usable_for_exploratory_analysis": True,
        "allowed_for_final_analysis": bool(dump.get("allowed_for_final_analysis")),
        "stop_reason": dump.get("stop_reason") or "restored_from_downloaded_files",
        "storage_plan": {
            **(dump.get("storage_plan") if isinstance(dump.get("storage_plan"), dict) else {}),
            "download_base_dir": str(base_dir),
            "cli_output_dir": str(files_dir),
            "raw_jsonl": str(raw_path),
        },
    }
    openalex_cli_provider.write_json(base_dir / "dump_manifest.json", restored)
    return str(raw_path), restored


def mark_completed(run_id: str, action: str, result: dict[str, Any], payload: dict[str, Any]) -> None:
    if action not in MATERIALIZATION_LIFECYCLE_ACTIONS:
        return
    try:
        from app.services import slice_workbench

        slice_workbench.mark_materialization_run_completed(run_id, result, materialization_id=str(payload.get("materialization_id") or ""))
    except Exception:
        return


def mark_failed(run_id: str, action: str, error: str, payload: dict[str, Any]) -> None:
    if action not in MATERIALIZATION_LIFECYCLE_ACTIONS:
        return
    try:
        from app.services import slice_workbench

        slice_workbench.mark_materialization_run_failed(run_id, error, materialization_id=str(payload.get("materialization_id") or ""))
    except Exception:
        return
