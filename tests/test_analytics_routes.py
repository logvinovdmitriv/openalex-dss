from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps/api"
SRC = ROOT / "src"
for path in (API, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.api.routes import analytics as analytics_routes  # noqa: E402


class AnalyticsRouteTests(unittest.TestCase):
    def test_ranking_json_forwards_full_slice_filter_contract(self) -> None:
        captured: dict[str, object] = {}

        def fake_ranking(fraction_mode: str, metric: str, filters: dict[str, str], **kwargs: object) -> dict[str, object]:
            captured["fraction_mode"] = fraction_mode
            captured["metric"] = metric
            captured["filters"] = filters
            captured["kwargs"] = kwargs
            return {"fields": ["author_id", "score"], "rows": [{"author_id": "https://openalex.org/A1", "score": 1}], "total": 1}

        with (
            patch.object(analytics_routes.warehouse, "metric_ranking", side_effect=fake_ranking),
            patch.object(analytics_routes.warehouse, "analysis_filter_warnings", return_value=["keyword local match is best-effort"]),
        ):
            payload = analytics_routes.ranking_json(
                run_id="run_a",
                dump_id="dump_a",
                fraction_mode="integer",
                metric="h",
                country_code="ru",
                filter_mode="keyword",
                subject_level="subfield",
                subject_id="1706",
                keyword_id="https://openalex.org/K1",
                keyword_display_name="Decision support",
                text_search_query="ergodesign",
                author_id="https://openalex.org/A1",
                author_orcid="0000-0001-0000-0000",
                doi="10.123/example",
                affiliation_mode="historical",
                institution_id="https://openalex.org/I1",
                source_id="https://openalex.org/S1",
                source_display_name="Journal",
                source_type="journal",
                language="en",
                open_access_is_oa="true",
                has_abstract="true",
                min_cited_by_count=5,
                from_publication_date="2020-01-01",
                to_publication_date="2024-12-31",
                work_type="article",
                limit=25,
            )

        filters = captured["filters"]
        self.assertEqual(captured["fraction_mode"], "integer")
        self.assertEqual(captured["metric"], "h")
        self.assertEqual(captured["kwargs"], {"limit": 25, "max_limit": 500_000, "run_id": "run_a", "dump_id": "dump_a", "author_ids": None})
        self.assertEqual(filters["country_code"], "RU")
        self.assertEqual(filters["filter_mode"], "keyword")
        self.assertEqual(filters["keyword_id"], "https://openalex.org/K1")
        self.assertEqual(filters["text_search_query"], "ergodesign")
        self.assertEqual(filters["author_orcid"], "0000-0001-0000-0000")
        self.assertEqual(filters["doi"], "10.123/example")
        self.assertEqual(filters["affiliation_mode"], "historical")
        self.assertEqual(filters["min_cited_by_count"], "5")
        self.assertEqual(payload["filter_warnings"], ["keyword local match is best-effort"])

    def test_ranking_json_with_cohort_limits_rows_to_cohort_authors(self) -> None:
        captured: dict[str, object] = {}

        def fake_ranking(fraction_mode: str, metric: str, filters: dict[str, str], **kwargs: object) -> dict[str, object]:
            captured["filters"] = filters
            captured["kwargs"] = kwargs
            return {"fields": ["author_id", "score"], "rows": [{"author_id": "https://openalex.org/A2", "score": 2}], "total": 1}

        cohort = {
            "cohort": {
                "cohort_id": "cohort_a",
                "name": "Cohort A",
                "source": "top_n",
                "n_authors": 1,
                "checksum": "sha",
            },
            "author_ids": {"https://openalex.org/A2"},
            "run_id": "run_a",
            "dump_id": "dump_a",
            "fraction_mode": "integer",
            "filters": {"country_code": "RU"},
        }
        with (
            patch.object(analytics_routes.cohorts, "resolve_cohort_context", return_value=cohort),
            patch.object(analytics_routes.warehouse, "metric_ranking", side_effect=fake_ranking),
            patch.object(analytics_routes.warehouse, "analysis_filter_warnings", return_value=[]),
        ):
            payload = analytics_routes.ranking_json(cohort_id="cohort_a", fraction_mode="integer", metric="h", limit=100)

        self.assertEqual(captured["filters"], {"country_code": "RU"})
        self.assertEqual(captured["kwargs"]["author_ids"], {"https://openalex.org/A2"})
        self.assertEqual(captured["kwargs"]["run_id"], "run_a")
        self.assertEqual(payload["cohort"]["cohort_id"], "cohort_a")


if __name__ == "__main__":
    unittest.main()
