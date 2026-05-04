from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services import bi


router = APIRouter(tags=["bi"])


@router.get("/bi/superset")
def bi_superset() -> dict[str, Any]:
    return bi.superset_status()


@router.post("/bi/prepare")
def bi_prepare() -> dict[str, Any]:
    return bi.prepare_warehouse()
