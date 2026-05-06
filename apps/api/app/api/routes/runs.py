from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import RunRequest
from app.services import jobs


router = APIRouter(tags=["runs"])
PUBLIC_RUN_ACTIONS = {"recalculate"}


@router.post("/runs", status_code=202)
def create_run(request: RunRequest) -> dict[str, Any]:
    if request.action not in PUBLIC_RUN_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported public run action: {request.action}. "
                "Use the slice/materialization workflow for OpenAlex downloads; "
                "fixture import and legacy pipeline actions are internal."
            ),
        )
    payload = request.payload.model_dump(exclude_none=True)
    if request.action == "recalculate" and not str(payload.get("dump_id") or "").strip():
        raise HTTPException(status_code=400, detail="dump_id is required for public recalculate runs")
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
        raise HTTPException(status_code=404, detail="Run not found") from exc


@router.get("/runs/{run_id}/tables/{table_name}")
def run_table(
    run_id: str,
    table_name: str,
    q: str = "",
    fraction_mode: str = "",
    metric: str = "",
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    try:
        return jobs.table_for_run(
            run_id,
            table_name,
            q=q,
            fraction_mode=fraction_mode,
            metric=metric,
            limit=limit,
            offset=offset,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
