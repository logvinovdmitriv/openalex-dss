from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.services import filesystem


router = APIRouter(tags=["sources"])


@router.get("/sources/storage")
def storage_overview() -> dict[str, Any]:
    return filesystem.storage_overview()


@router.get("/sources/files")
def source_files(root: str = "data", limit: int = Query(300, ge=1, le=2000)) -> dict[str, Any]:
    return filesystem.list_data_files(root=root, limit=limit)


@router.post("/sources/prepare-lakehouse")
def prepare_lakehouse() -> dict[str, Any]:
    return filesystem.prepare_lakehouse_dirs()
