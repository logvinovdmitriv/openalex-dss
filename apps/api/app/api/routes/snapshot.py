from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services import snapshot


router = APIRouter(tags=["openalex-snapshot"])


@router.get("/snapshot/manifest")
def snapshot_manifest(entity: str = "works") -> dict[str, Any]:
    return snapshot.fetch_manifest(entity)
