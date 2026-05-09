from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "apps/api", ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services import catalog, distribution_engine, metric_registry, ranking_engine


def test_catalog_uses_shared_metric_registry() -> None:
    registry_metrics = metric_registry.catalog_metrics()
    catalog_metrics = catalog.system_catalog()["metrics"]

    assert catalog_metrics == registry_metrics
    assert registry_metrics
    assert all(item["id"] and item["label"] for item in registry_metrics)
    assert any(item.get("formula") or item.get("algorithm") for item in registry_metrics)


def test_ranking_and_distribution_engines_keep_service_contracts() -> None:
    rows = [
        {"author_id": "a1", "author_display_name": "A", "h": 5, "p": 2},
        {"author_id": "a2", "author_display_name": "B", "h": 7, "p": 4},
        {"author_id": "a3", "author_display_name": "C", "h": 7, "p": 1},
    ]

    ranked, total = ranking_engine.build_metric_ranking_rows(rows, "h", ["p"], limit=10, max_limit=100)
    summary = distribution_engine.describe([row["h"] for row in rows])
    histogram = distribution_engine.histogram([row["h"] for row in rows], bins=2)

    assert total == 3
    assert [row["author_id"] for row in ranked] == ["a2", "a3", "a1"]
    assert ranked[0]["rank_competition"] == ranked[1]["rank_competition"] == 1
    assert summary["median"] == 7
    assert sum(bucket["count"] for bucket in histogram) == 3
