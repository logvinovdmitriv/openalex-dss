from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services import registry as registry_service


router = APIRouter(tags=["registry"])


@router.get("/registry")
def get_registry() -> dict[str, Any]:
    return registry_service.registry()

