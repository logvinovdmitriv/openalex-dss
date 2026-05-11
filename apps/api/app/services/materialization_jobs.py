from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.providers import openalex_cli_provider
from app.services import authorship_backfill, dump_integrity, pipeline
from app.services.internal_payloads import normalize_internal_pipeline_payload


MATERIALIZATION_ACTIONS = {"fetch_slice_dump", "build_from_openalex", "repair_dump", "backfill_truncated_authorships"}
SUPPORTED_MATERIALIZATION_ACTIONS = MATERIALIZATION_ACTIONS
REQUIRES_ACCEPTED_SIGNATURE_ACTIONS = {"build_from_openalex", "fetch_slice_dump"}
MATERIALIZATION_LIFECYCLE_ACTIONS = {"build_from_openalex", "fetch_slice_dump", "repair_dump"}

DownloadProgressCallback = Callable[[dict[str, Any]], None]
StageProgressCallback = Callable[[int | None, str, dict[str, Any] | None], None]
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
    if action == "backfill_truncated_authorships":
        return _backfill_truncated_authorships(
            run_id,
            payload,
            update_progress_callback=update_progress_callback,
            cancel_callback=cancel_callback,
        )
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
        update_progress_callback(None, "Нормализация локального среза", {"source_path": raw_jsonl})
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
    if update_progress_callback:
        update_progress_callback(None, "Проверка локальных файлов среза", {"source_path": raw_jsonl})
    raw_jsonl, dump = _ensure_repair_raw_file(
        dump,
        raw_jsonl,
        update_progress_callback,
        api_key=str(payload.get("api_key") or ""),
    )
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
        compute_progress_base=40,
    )
    return {"status": "ok", "mode": "repair_dump", "dump": dump, "build": built, "analysis_eligibility": analysis_eligibility}


def _backfill_truncated_authorships(
    run_id: str,
    payload: dict[str, Any],
    *,
    update_progress_callback: StageProgressCallback | None,
    cancel_callback: CancelCallback | None,
) -> dict[str, Any]:
    dump = payload.get("dump_manifest") if isinstance(payload.get("dump_manifest"), dict) else {}
    raw_jsonl = str(payload.get("source_path") or dump.get("raw_jsonl") or "").strip()
    if update_progress_callback:
        update_progress_callback(None, "Проверка локального среза перед backfill", {"source_path": raw_jsonl})
    raw_jsonl, dump = _ensure_repair_raw_file(
        dump,
        raw_jsonl,
        update_progress_callback,
        api_key=str(payload.get("api_key") or ""),
    )
    backfill = authorship_backfill.backfill_truncated_authorships(
        raw_jsonl,
        api_key=str(payload.get("api_key") or ""),
        progress_callback=update_progress_callback,
        cancel_callback=cancel_callback,
        max_works=int(payload.get("max_works") or 0),
    )
    output_path = str(backfill.get("output_path") or raw_jsonl)
    backfill_status = str(backfill.get("status") or "")
    updated_dump = _dump_after_backfill(dump, output_path, backfill)
    analysis_eligibility = pipeline.analysis_eligibility_from_dump(updated_dump, dev_override=True)
    built = pipeline.import_local_file(
        normalize_internal_pipeline_payload(
            {
                **payload,
                "source_path": output_path,
                "api_key": None,
                "run_id": run_id,
                "dump_id": updated_dump.get("dump_id") or payload.get("dump_id"),
                "dump_manifest": updated_dump,
                "analysis_eligibility": analysis_eligibility,
                "import_mode": "final_reproducible" if analysis_eligibility["allowed_for_final_analysis"] else "exploratory",
                "active_context_source": "authorship_backfill",
            }
        ),
        progress_callback=update_progress_callback,
        compute_progress_base=55,
    )
    return {
        "status": "ok",
        "mode": "backfill_truncated_authorships",
        "backfill_status": backfill_status,
        "backfill": backfill,
        "dump": updated_dump,
        "build": built,
        "analysis_eligibility": analysis_eligibility,
    }


def _dump_after_backfill(dump: dict[str, Any], output_path: str, backfill: dict[str, Any]) -> dict[str, Any]:
    target = Path(output_path)
    checksum = str(backfill.get("sha256") or (openalex_cli_provider.sha256_file(target) if target.is_file() else ""))
    status = str(backfill.get("status") or "")
    eligible = _backfill_allows_final(dump, status)
    updated = {
        **dump,
        "raw_jsonl": output_path,
        "raw_jsonl_sha256": checksum,
        "bytes_written": target.stat().st_size if target.is_file() else dump.get("bytes_written"),
        "backfill_status": status,
        "backfill_manifest": str(backfill.get("manifest_path") or ""),
        "backfill_summary": {
            "candidates_total": backfill.get("candidates_total"),
            "attempted": backfill.get("attempted"),
            "replaced": backfill.get("replaced"),
            "unresolved": backfill.get("unresolved"),
        },
        "allowed_for_final_analysis": eligible,
        "quality_gate": {} if eligible else dump.get("quality_gate", {}),
    }
    storage_plan = updated.get("storage_plan") if isinstance(updated.get("storage_plan"), dict) else {}
    if storage_plan:
        updated["storage_plan"] = {**storage_plan, "raw_jsonl": output_path}
    manifest_path = Path(str(updated.get("dump_manifest") or updated.get("manifest_path") or target.with_name("dump_manifest.json")))
    updated["dump_manifest"] = str(manifest_path)
    updated["manifest_path"] = str(manifest_path)
    openalex_cli_provider.write_json(manifest_path, updated)
    return updated


def _backfill_allows_final(dump: dict[str, Any], backfill_status: str) -> bool:
    if backfill_status not in {"complete", "completed", "not_required"}:
        return False
    if bool(dump.get("allowed_for_final_analysis")):
        return True
    eligibility = dump.get("analysis_eligibility") if isinstance(dump.get("analysis_eligibility"), dict) else {}
    quality_gate = dump.get("quality_gate") if isinstance(dump.get("quality_gate"), dict) else eligibility.get("quality_gate") if isinstance(eligibility.get("quality_gate"), dict) else {}
    if str(quality_gate.get("reason") or "") == "truncated_authorships_require_backfill":
        completeness = str(dump.get("scientific_completeness") or "").strip()
        signatures = dump.get("signatures") if isinstance(dump.get("signatures"), dict) else {}
        return completeness in {"complete", "full"} and bool(signatures.get("compatible") or signatures.get("download_signature_verified"))
    return False


def _ensure_repair_raw_file(
    dump: dict[str, Any],
    raw_jsonl: str,
    update_progress_callback: StageProgressCallback | None,
    *,
    api_key: str = "",
) -> tuple[str, dict[str, Any]]:
    raw_path = Path(raw_jsonl).expanduser() if raw_jsonl else Path("")
    storage_plan = dump.get("storage_plan") if isinstance(dump.get("storage_plan"), dict) else {}
    files_dir_raw = str(dump.get("cli_files_dir") or storage_plan.get("cli_output_dir") or "").strip()
    files_dir = Path(files_dir_raw).expanduser() if files_dir_raw else None
    if raw_jsonl and raw_path.is_file():
        validated = dump_integrity.manifest_with_integrity({**dump, "raw_jsonl": str(raw_path)}, require_expected_count=False)
        if validated.get("integrity_validation", {}).get("ok"):
            records = int((validated.get("integrity_validation") or {}).get("records_actual") or validated.get("records_downloaded") or 0)
            checksum = str((validated.get("integrity_validation") or {}).get("raw_jsonl_sha256_actual") or validated.get("raw_jsonl_sha256") or "")
            files_manifest_path = Path(str(validated.get("files_manifest") or raw_path.with_name("files_manifest.json")))
            restored = _repaired_dump_manifest(
                validated,
                raw_path=raw_path,
                files_dir=files_dir,
                files_manifest_path=files_manifest_path,
                records=records,
                checksum=checksum,
            )
            restored = dump_integrity.manifest_with_integrity(restored, require_expected_count=int(restored.get("records_expected") or 0) > 0)
            return str(raw_path), restored
        repair_status = openalex_cli_provider.repair_missing_cli_files(
            {**dump, "raw_jsonl": str(raw_path)},
            api_key=api_key,
            progress_callback=(
                lambda progress: update_progress_callback(
                    None,
                    str(progress.get("stage") or "Проверка файлов OpenAlex CLI"),
                    {key: value for key, value in progress.items() if key != "stage"},
                )
                if update_progress_callback
                else None
            ),
        )
        if not repair_status.get("repairable"):
            raise ValueError("Локальный raw_jsonl поврежден, а исходные файлы OpenAlex CLI недоступны для повторной упаковки.")
    if files_dir is None:
        raise ValueError("Для восстановления нужен локальный файл среза или папка скачанных файлов OpenAlex.")
    if not files_dir.is_dir():
        raise ValueError("Папка скачанных файлов OpenAlex не найдена.")
    base_dir = files_dir.parent
    raw_path = Path(raw_jsonl).expanduser() if raw_jsonl else base_dir / "works.jsonl.gz"
    files_manifest_path = Path(str(dump.get("files_manifest") or base_dir / "files_manifest.json"))
    if update_progress_callback:
        update_progress_callback(None, "Упаковка уже скачанных файлов OpenAlex", {"source_path": str(raw_path), "files_dir": str(files_dir)})
    records, _ = openalex_cli_provider.pack_existing_cli_files(
        files_dir,
        raw_path,
        manifest_path=files_manifest_path,
        progress_callback=(
            lambda progress: update_progress_callback(
                None,
                str(progress.get("stage") or "Упаковка уже скачанных файлов OpenAlex"),
                {
                    **{key: value for key, value in progress.items() if key != "percent"},
                    **({"pack_percent": int(progress.get("percent"))} if progress.get("percent") is not None else {}),
                },
            )
            if update_progress_callback
            else None
        ),
    )
    if records <= 0:
        raise ValueError("В скачанных файлах OpenAlex не найдено работ для восстановления среза.")
    checksum = openalex_cli_provider.sha256_file(raw_path)
    restored = _repaired_dump_manifest(
        dump,
        raw_path=raw_path,
        files_dir=files_dir,
        files_manifest_path=files_manifest_path,
        records=records,
        checksum=checksum,
    )
    restored = dump_integrity.manifest_with_integrity(restored, require_expected_count=int(restored.get("records_expected") or 0) > 0)
    openalex_cli_provider.write_json(base_dir / "dump_manifest.json", restored)
    return str(raw_path), restored


def _repaired_dump_manifest(
    dump: dict[str, Any],
    *,
    raw_path: Path,
    files_dir: Path | None,
    files_manifest_path: Path,
    records: int,
    checksum: str,
) -> dict[str, Any]:
    finished_at = datetime.now(timezone.utc).isoformat()
    expected = int(dump.get("records_expected") or 0)
    records_count_verified = records > 0 and (expected <= 0 or records == expected)
    if records <= 0:
        completeness = "empty"
    elif records_count_verified:
        completeness = "complete"
    elif expected > 0:
        completeness = "partial_count_mismatch"
    else:
        completeness = str(dump.get("scientific_completeness") or "partial")
    signatures = dump.get("signatures") if isinstance(dump.get("signatures"), dict) else {}
    if not signatures and isinstance(dump.get("analysis_eligibility"), dict):
        checks = dump["analysis_eligibility"].get("signature_checks")
        signatures = checks if isinstance(checks, dict) else {}
    allowed_for_final = (
        completeness == "complete"
        and records_count_verified
        and bool(signatures.get("compatible"))
        and bool(signatures.get("estimate_signature_verified"))
        and bool(signatures.get("accepted_estimate_signature_verified"))
        and bool(signatures.get("download_signature_verified"))
    )
    technical_payload = pipeline._slice_payload_from_dump_manifest(dump)
    if not technical_payload and isinstance(dump.get("technical_payload"), dict):
        technical_payload = dict(dump["technical_payload"])
    base_dir = files_dir.parent if files_dir is not None else raw_path.parent
    return {
        **dump,
        "dump_id": f"dump_{checksum[:16]}" if checksum else str(dump.get("dump_id") or base_dir.name),
        "raw_jsonl": str(raw_path),
        "raw_jsonl_sha256": checksum,
        "records_downloaded": records,
        "records_expected": expected or dump.get("records_expected"),
        "records_delta": (records - expected) if expected else dump.get("records_delta"),
        "records_count_verified": bool(records_count_verified),
        "bytes_written": raw_path.stat().st_size,
        "files_manifest": str(files_manifest_path),
        "dump_manifest": str(base_dir / "dump_manifest.json"),
        "manifest_path": str(base_dir / "dump_manifest.json"),
        "download_finished_at_utc": dump.get("download_finished_at_utc") or finished_at,
        "created_at_utc": dump.get("created_at_utc") or finished_at,
        "scientific_completeness": completeness,
        "usable_for_exploratory_analysis": True,
        "allowed_for_final_analysis": allowed_for_final,
        "stop_reason": dump.get("stop_reason") or "restored_from_downloaded_files",
        "technical_payload": technical_payload or dump.get("technical_payload"),
        "storage_plan": {
            **(dump.get("storage_plan") if isinstance(dump.get("storage_plan"), dict) else {}),
            "download_base_dir": str(base_dir),
            **({"cli_output_dir": str(files_dir)} if files_dir is not None else {}),
            "raw_jsonl": str(raw_path),
        },
    }


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
