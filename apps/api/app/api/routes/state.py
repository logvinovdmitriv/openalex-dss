from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services import catalog, warehouse, workflow


router = APIRouter(tags=["state"])


@router.get("/state")
def state() -> dict[str, Any]:
    return {
        "tables": warehouse.list_tables(),
        "fetch_meta": warehouse.read_json_doc("fetch_meta"),
        "quality": warehouse.read_json_doc("quality"),
        "stats": _stats_summary(warehouse.read_json_doc("stats")),
        "theory": _theory_summary(warehouse.read_json_doc("theory")),
        "checksums": _checksums_summary(warehouse.read_json_doc("checksums")),
        "pipeline": warehouse.read_json_doc("pipeline"),
        "workflow": workflow.state(),
    }


@router.get("/catalog")
def system_catalog() -> dict[str, Any]:
    return catalog.system_catalog()


def _stats_summary(doc: dict[str, Any] | None) -> dict[str, Any]:
    data = doc or {}
    fraction_modes = data.get("fraction_modes") or {}
    return {
        "available": bool(data),
        "fraction_modes": list(fraction_modes.keys()),
    }


def _theory_summary(doc: dict[str, Any] | None) -> dict[str, Any]:
    data = doc or {}
    return {
        "available": bool(data),
        "core_metrics": data.get("core_metrics") or [],
        "experimental_metrics": data.get("experimental_metrics") or [],
        "lrdi_parameters": data.get("lrdi_parameters") or {},
        "iupv_parameters": data.get("iupv_parameters") or {},
        "islv_parameters": data.get("islv_parameters") or {},
    }


def _checksums_summary(doc: dict[str, Any] | None) -> dict[str, Any]:
    data = doc or {}
    artifacts = data.get("primary_artifacts") or {}
    return {
        "available": bool(data),
        "algorithm": data.get("algorithm"),
        "primary_artifacts_count": len(artifacts),
    }
