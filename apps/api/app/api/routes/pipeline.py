from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.schemas import PipelineRequest
from app.services import pipeline


router = APIRouter(tags=["pipeline"])


@router.post("/pipeline/recalculate")
def pipeline_recalculate(request: PipelineRequest) -> dict[str, Any]:
    try:
        return pipeline.recalculate(request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pipeline/fetch", deprecated=True)
def pipeline_fetch(request: PipelineRequest) -> dict[str, Any]:
    try:
        return pipeline.fetch_and_run(request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pipeline/fetch-slice-dump")
def pipeline_fetch_slice_dump(request: PipelineRequest) -> dict[str, Any]:
    try:
        return pipeline.fetch_slice_dump(request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pipeline/fetch-authors-preview")
def pipeline_fetch_authors_preview(request: PipelineRequest) -> dict[str, Any]:
    try:
        return pipeline.fetch_author_preview(request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pipeline/import-file")
def pipeline_import_file(request: PipelineRequest) -> dict[str, Any]:
    try:
        return pipeline.import_local_file(request.model_dump(exclude_none=True))
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pipeline/preview")
def pipeline_preview(request: PipelineRequest) -> dict[str, Any]:
    try:
        return pipeline.preview(request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pipeline/clear")
def pipeline_clear() -> dict[str, Any]:
    return pipeline.clear_generated_data()
