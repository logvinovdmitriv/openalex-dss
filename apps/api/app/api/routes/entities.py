from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services import warehouse


router = APIRouter(tags=["entities"])


@router.get("/authors/{author_id:path}")
def author(author_id: str, run_id: str = "", dump_id: str = "") -> dict[str, Any]:
    return warehouse.author_detail(author_id, run_id=run_id, dump_id=dump_id)


@router.get("/works/{work_id:path}")
def work(work_id: str, run_id: str = "", dump_id: str = "") -> dict[str, Any]:
    return warehouse.work_detail(work_id, run_id=run_id, dump_id=dump_id)
