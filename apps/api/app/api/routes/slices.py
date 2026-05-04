from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from app.api.schemas import MaterializationPlanRequest, MaterializationRunRequest, PipelineRequest, SliceCreateRequest, SliceEstimateRequest
from app.services import query_planner, slice_workbench


router = APIRouter(tags=["slices"])


@router.post("/slices/plan")
def plan_slice(request: PipelineRequest) -> dict[str, Any]:
    try:
        return query_planner.plan_slice(request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/slices")
def list_slices(limit: int = Query(50, ge=1, le=250)) -> dict[str, Any]:
    return slice_workbench.list_slices(limit=limit)


@router.post("/slices")
def create_slice(payload: SliceCreateRequest) -> dict[str, Any]:
    try:
        return slice_workbench.create_slice(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/slices/{slice_id}")
def get_slice(slice_id: str) -> dict[str, Any]:
    try:
        return slice_workbench.get_slice(slice_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Slice not found") from exc


@router.post("/slices/{slice_id}/resolve")
def resolve_slice(slice_id: str) -> dict[str, Any]:
    try:
        return slice_workbench.resolve_slice(slice_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Slice not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/slices/{slice_id}/estimate")
def estimate_slice(slice_id: str, payload: SliceEstimateRequest = Body(default_factory=SliceEstimateRequest)) -> dict[str, Any]:
    try:
        return slice_workbench.estimate_slice(slice_id, payload.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Slice not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/slices/{slice_id}/materialization-plans")
def create_materialization_plan(slice_id: str, payload: MaterializationPlanRequest) -> dict[str, Any]:
    try:
        return slice_workbench.create_materialization_plan(slice_id, payload.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Slice not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/materialization-plans")
def list_materialization_plans(limit: int = Query(50, ge=1, le=250)) -> dict[str, Any]:
    return slice_workbench.list_materialization_plans(limit=limit)


@router.post("/materializations/{materialization_id}/run", status_code=202)
def run_materialization(materialization_id: str, payload: MaterializationRunRequest = Body(default_factory=MaterializationRunRequest)) -> dict[str, Any]:
    try:
        return slice_workbench.run_materialization(materialization_id, payload.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Materialization plan not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/dumps")
def list_dumps(limit: int = Query(50, ge=1, le=250)) -> dict[str, Any]:
    return slice_workbench.list_dumps(limit=limit)


@router.get("/workbench")
def workbench_summary() -> dict[str, Any]:
    return slice_workbench.workbench_summary()
