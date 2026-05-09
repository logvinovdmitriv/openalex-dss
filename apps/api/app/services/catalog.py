from __future__ import annotations

from typing import Any

from app.providers import openalex_cli_provider
from app.services import filesystem, metric_registry, registry, snapshot, workflow
from openalex_dss.config import load_config


FRACTION_MODES = [
    {"id": "strict_authors_count", "label": "Долевой учет по всем авторам"},
    {"id": "renorm_valid_authors", "label": "Долевой учет по распознанным авторам"},
    {"id": "integer", "label": "Каждый автор учитывается полностью"},
]

def system_catalog() -> dict[str, Any]:
    config_registry = registry.registry()
    storage = filesystem.storage_overview()
    native_metric_registry = config_registry.get("native_metric_registry") or []
    ranking_profiles = config_registry.get("ranking_profiles") or []
    return {
        "metrics": metric_registry.catalog_metrics(),
        "native_metrics": native_metric_registry,
        "fraction_modes": FRACTION_MODES,
        "data_sources": config_registry.get("data_sources") or [],
        "ranking_profiles": ranking_profiles,
        "execution_limits": config_registry.get("execution_limits") or {},
        "storage_profiles": config_registry.get("storage_profiles") or [],
        "ui_options": config_registry.get("ui_options") or {},
        "openalex_filter_registry": config_registry.get("openalex_filter_registry") or {},
        "openalex_cli": openalex_cli_provider.cli_status(_api_key_env()),
        "domain_presets": config_registry.get("domain_presets") or [],
        "organization_presets": config_registry.get("organization_presets") or [],
        "filter_schema": config_registry.get("filter_schema") or {},
        "data_root": storage["data_root"],
        "safe_roots": storage["safe_roots"],
        "openalex_snapshot_entities": snapshot.ENTITIES,
        "export_formats": ["csv", "json"],
        "workflow_stages": workflow.STAGE_DEFINITIONS,
        "author_filters": _openalex_filter_options(config_registry.get("openalex_filter_registry") or {}),
    }


def _api_key_env() -> str:
    try:
        return load_config().api_key_env
    except Exception:
        return "OPENALEX_API_KEY"


def _openalex_filter_options(filter_registry: dict[str, Any]) -> list[dict[str, str]]:
    filters = filter_registry.get("filters") or {}
    out: list[dict[str, str]] = []
    for filter_id, item in filters.items():
        if not isinstance(item, dict):
            continue
        works_filter = item.get("works_filter") or {}
        field = str(works_filter.get("field") or "").strip()
        if field and item.get("class") == "openalex_pushdown":
            out.append({"id": str(filter_id), "label": str(item.get("label") or filter_id), "source": f"works.{field}"})
    return out
