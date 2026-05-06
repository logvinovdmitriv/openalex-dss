from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services import catalog


router = APIRouter(tags=["catalog"])


@router.get("/catalog")
def system_catalog() -> dict[str, Any]:
    return catalog.system_catalog()
