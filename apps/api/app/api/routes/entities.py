from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services import warehouse


router = APIRouter(tags=["entities"])


@router.get("/authors/{author_id:path}")
def author(author_id: str) -> dict[str, Any]:
    return warehouse.author_detail(author_id)


@router.get("/works/{work_id:path}")
def work(work_id: str) -> dict[str, Any]:
    return warehouse.work_detail(work_id)
