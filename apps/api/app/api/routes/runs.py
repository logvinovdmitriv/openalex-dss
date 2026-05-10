from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import RunRequest
from app.services import jobs


router = APIRouter(tags=["runs"])
PUBLIC_RUN_ACTIONS = {"recalculate", "bootstrap_analysis", "permutation_analysis", "convergence_analysis"}


@router.post("/runs", status_code=202)
def create_run(request: RunRequest) -> dict[str, Any]:
    if request.action not in PUBLIC_RUN_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported public run action: {request.action}. "
                "Use the slice/materialization workflow for OpenAlex downloads."
            ),
        )
    payload = request.payload.model_dump(exclude_none=True)
    if not str(payload.get("dump_id") or "").strip():
        detail = "dump_id is required for public recalculate runs" if request.action == "recalculate" else "dump_id is required for public analysis runs"
        raise HTTPException(status_code=400, detail=detail)
    try:
        return jobs.create_run(request.action, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs")
def list_runs(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    return jobs.list_runs(limit=limit)


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    try:
        return jobs.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Задача не найдена") from exc


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, Any]:
    try:
        return jobs.cancel_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Задача не найдена") from exc
