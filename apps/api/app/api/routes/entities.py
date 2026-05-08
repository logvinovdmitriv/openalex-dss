from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.services import warehouse


router = APIRouter(tags=["entities"])


@router.get("/authors/{author_id:path}")
def author(
    author_id: str,
    run_id: str = "",
    dump_id: str = "",
    works_limit: int = Query(100, ge=1, le=1_000),
    works_offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    try:
        return warehouse.author_detail(
            author_id,
            run_id=run_id,
            dump_id=dump_id,
            works_limit=works_limit,
            works_offset=works_offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/works/{work_id:path}")
def work(
    work_id: str,
    run_id: str = "",
    dump_id: str = "",
    authors_limit: int = Query(500, ge=1, le=5_000),
    authors_offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    try:
        return warehouse.work_detail(
            work_id,
            run_id=run_id,
            dump_id=dump_id,
            authors_limit=authors_limit,
            authors_offset=authors_offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
