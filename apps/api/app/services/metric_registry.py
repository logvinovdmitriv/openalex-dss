from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.services import registry as config_registry


@lru_cache(maxsize=1)
def computed_metrics() -> tuple[dict[str, Any], ...]:
    """Return current local metric definitions from the shared registry config."""
    items = config_registry.registry().get("metric_registry") or []
    out: list[dict[str, Any]] = []
    for item in items:
        metric_id = str(item.get("metric_id") or "").strip()
        if not metric_id:
            continue
        out.append(
            {
                "id": metric_id,
                "label": str(item.get("label") or metric_id),
                "group": str(item.get("group") or ""),
                "source": str(item.get("source") or "computed_from_slice_works"),
                "formula": item.get("formula"),
                "algorithm": item.get("algorithm"),
                "warning": item.get("warning"),
                "visible": bool(item.get("visible", True)),
                "local_only": bool(item.get("local_only", True)),
                "params": item.get("params") or {},
            }
        )
    return tuple(out)


def catalog_metrics() -> list[dict[str, Any]]:
    return [dict(item) for item in computed_metrics() if item.get("visible", True)]


def computed_metric_ids() -> set[str]:
    return {str(item["id"]) for item in computed_metrics()}


def metric_formula(metric_id: str) -> str:
    for item in computed_metrics():
        if item["id"] == metric_id:
            return str(item.get("formula") or item.get("algorithm") or "")
    return ""

