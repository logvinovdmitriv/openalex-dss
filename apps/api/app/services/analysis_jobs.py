from __future__ import annotations

from typing import Any

from app.services import pipeline
from app.services.internal_payloads import normalize_internal_pipeline_payload


ANALYSIS_ACTIONS = {"recalculate"}


def recalculate(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return pipeline.recalculate(normalize_internal_pipeline_payload({**payload, "run_id": run_id}))
