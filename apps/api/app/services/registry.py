from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.paths import ROOT


CONFIGS = ROOT / "configs"


def registry() -> dict[str, Any]:
    domain = _read_yaml("domain_presets.yaml")
    organizations = _read_yaml("organization_presets.yaml")
    metrics = _read_yaml("metric_registry.yaml")
    ranking_profiles = _read_yaml("ranking_profiles.yaml")
    execution_limits = _read_yaml("execution_limits.yaml")
    return {
        "version": "1.0",
        "config_root": str(CONFIGS),
        "domain_presets": [_domain_preset(item) for item in domain.get("presets", [])],
        "organization_presets": [_organization_preset(item) for item in organizations.get("organizations", [])],
        "filter_schema": _read_yaml("filter_schema.yaml"),
        "work_type_presets": _read_yaml("work_type_presets.yaml").get("work_types", []),
        "metric_registry": metrics.get("metrics", []),
        "native_metric_registry": metrics.get("native_metrics", []),
        "ranking_profiles": ranking_profiles.get("profiles", []),
        "execution_limits": execution_limits.get("execution_limits", {}),
        "openalex_filter_registry": _read_yaml("openalex_filter_registry.yaml"),
    }


def find_domain_aliases(query: str, limit: int = 8) -> list[dict[str, Any]]:
    return _alias_matches(registry()["domain_presets"], query, limit)


def find_organization_aliases(query: str, limit: int = 8) -> list[dict[str, Any]]:
    return _alias_matches(registry()["organization_presets"], query, limit)


def _domain_preset(item: dict[str, Any]) -> dict[str, Any]:
    mapping = item.get("default_mapping") or {}
    entity_type = str(mapping.get("entity_type") or "subfield")
    entity_id = str(mapping.get("entity_id") or "")
    return {
        "value": str(item.get("preset_id") or entity_id or item.get("label") or ""),
        "label": str(item.get("label") or entity_id),
        "description": str(item.get("public_description") or ""),
        "group": str(item.get("group") or ""),
        "aliases": [str(value) for value in item.get("aliases", [])],
        "subject_level": entity_type,
        "subject_id": entity_id,
        "subject_name": str(mapping.get("entity_display_name") or item.get("label") or entity_id),
        "filter_mode": str(mapping.get("topic_mode") or "primary_topic"),
        "openalex_id": _openalex_entity_url(entity_type, entity_id),
        "confidence": str(mapping.get("confidence") or ""),
        "candidates": item.get("openalex_candidates", []),
    }


def _organization_preset(item: dict[str, Any]) -> dict[str, Any]:
    mapping = item.get("default_mapping") or {}
    openalex_id = str(mapping.get("openalex_id") or "")
    return {
        "value": str(item.get("organization_id") or openalex_id or item.get("label") or ""),
        "label": str(item.get("label") or mapping.get("display_name") or openalex_id),
        "description": str(item.get("public_description") or ""),
        "aliases": [str(value) for value in item.get("aliases", [])],
        "institution_id": openalex_id,
        "institution_name": str(mapping.get("display_name") or ""),
        "country_code": str(mapping.get("country_code") or ""),
        "ror": str(mapping.get("ror") or ""),
        "confidence": str(mapping.get("confidence") or ""),
        "validation_required": bool(mapping.get("validation_required", False)),
    }


def _alias_matches(items: list[dict[str, Any]], query: str, limit: int) -> list[dict[str, Any]]:
    needle = query.casefold().strip()
    if len(needle) < 2:
        return []
    matches: list[dict[str, Any]] = []
    for item in items:
        haystack = " ".join(
            [
                str(item.get("value", "")),
                str(item.get("label", "")),
                str(item.get("description", "")),
                " ".join(str(alias) for alias in item.get("aliases", [])),
            ]
        ).casefold()
        if needle in haystack:
            matches.append(item)
        if len(matches) >= limit:
            break
    return matches


def _openalex_entity_url(level: str, entity_id: str) -> str:
    if not entity_id:
        return ""
    if level == "topic":
        return f"https://openalex.org/{entity_id}"
    return f"https://openalex.org/{level}s/{entity_id}"


@lru_cache(maxsize=16)
def _read_yaml(filename: str) -> dict[str, Any]:
    path = CONFIGS / filename
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}
