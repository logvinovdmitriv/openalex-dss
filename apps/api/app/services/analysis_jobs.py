from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services import pipeline
from app.services.internal_payloads import normalize_internal_pipeline_payload


ANALYSIS_ACTIONS = {"recalculate"}


StageProgressCallback = Callable[[int | None, str, dict[str, Any] | None], None]


def recalculate(
    run_id: str,
    payload: dict[str, Any],
    *,
    update_progress_callback: StageProgressCallback | None = None,
) -> dict[str, Any]:
    return pipeline.recalculate(
        normalize_internal_pipeline_payload({**payload, "run_id": run_id}),
        progress_callback=update_progress_callback,
    )
