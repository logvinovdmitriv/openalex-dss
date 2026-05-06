from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services import pipeline
from app.services.internal_payloads import normalize_internal_pipeline_payload


MATERIALIZATION_ACTIONS = {"fetch_slice_dump", "build_from_openalex"}
# Retained for deterministic fixture/dev imports; it is not part of the public API.
DEV_MATERIALIZATION_ACTIONS = {"import_file"}
SUPPORTED_MATERIALIZATION_ACTIONS = MATERIALIZATION_ACTIONS | DEV_MATERIALIZATION_ACTIONS
REQUIRES_ACCEPTED_SIGNATURE_ACTIONS = {"build_from_openalex", "fetch_slice_dump"}
MATERIALIZATION_LIFECYCLE_ACTIONS = {"build_from_openalex", "fetch_slice_dump"}

DownloadProgressCallback = Callable[[dict[str, Any]], None]
StageProgressCallback = Callable[[int, str, dict[str, Any] | None], None]


def dispatch(
    run_id: str,
    action: str,
    payload: dict[str, Any],
    *,
    download_progress_callback: DownloadProgressCallback | None = None,
    update_progress_callback: StageProgressCallback | None = None,
    allow_unchecked_download: bool = False,
) -> dict[str, Any]:
    payload = normalize_internal_pipeline_payload(payload)
    if action == "fetch_slice_dump":
        return pipeline.fetch_slice_dump(
            payload,
            progress_callback=download_progress_callback,
            require_accepted_signatures=not allow_unchecked_download,
        )
    if action == "build_from_openalex":
        return _build_from_openalex(
            run_id,
            payload,
            download_progress_callback=download_progress_callback,
            update_progress_callback=update_progress_callback,
            allow_unchecked_download=allow_unchecked_download,
        )
    if action == "import_file":
        return pipeline.import_local_file(
            normalize_internal_pipeline_payload(
                {
                    **payload,
                    "run_id": run_id,
                    "active_context_source": "dev_import_file",
                }
            )
        )
    raise ValueError(f"Unsupported materialization job action: {action}")


def _build_from_openalex(
    run_id: str,
    payload: dict[str, Any],
    *,
    download_progress_callback: DownloadProgressCallback | None,
    update_progress_callback: StageProgressCallback | None,
    allow_unchecked_download: bool,
) -> dict[str, Any]:
    fetched = pipeline.fetch_slice_dump(
        payload,
        progress_callback=download_progress_callback,
        require_accepted_signatures=not allow_unchecked_download,
    )
    dump = fetched.get("dump") or {}
    raw_jsonl = str(dump.get("raw_jsonl") or "").strip()
    if not raw_jsonl or dump.get("no_data"):
        return {"fetch": fetched, "build": None, "no_data": True}
    analysis_eligibility = pipeline.analysis_eligibility_from_dump(dump, dev_override=allow_unchecked_download)
    if not analysis_eligibility["allowed_for_final_analysis"] and not allow_unchecked_download:
        raise ValueError("Дамп не допущен к финальному анализу. Обновите оценку и скачивание либо используйте явный dev-режим.")
    if update_progress_callback:
        update_progress_callback(96, "normalizing local file", {"source_path": raw_jsonl})
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
        )
    )
    return {"fetch": fetched, "build": built, "no_data": False, "analysis_eligibility": analysis_eligibility}


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
