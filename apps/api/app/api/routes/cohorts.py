from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import AuthorCohortCreateRequest
from app.services import cohorts


router = APIRouter(tags=["cohorts"])


@router.post("/cohorts")
def create_cohort(payload: AuthorCohortCreateRequest) -> dict[str, Any]:
    try:
        return cohorts.create_cohort(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cohorts")
def list_cohorts(limit: int = Query(50, ge=1, le=250)) -> dict[str, Any]:
    return cohorts.list_cohorts(limit=limit)


@router.get("/cohorts/{cohort_id}")
def get_cohort(cohort_id: str) -> dict[str, Any]:
    try:
        return cohorts.get_cohort(cohort_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc


@router.post("/cohorts/{cohort_id}/statistics")
def cohort_statistics(cohort_id: str) -> dict[str, Any]:
    try:
        return cohorts.cohort_statistics(cohort_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
