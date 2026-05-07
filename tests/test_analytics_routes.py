from __future__ import annotations

import sys
import unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch

from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps/api"
SRC = ROOT / "src"
for path in (API, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.api.routes import analytics as analytics_routes  # noqa: E402
from app.api.routes import cohorts as cohort_routes  # noqa: E402


def _request(**params: object) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": urlencode({key: value for key, value in params.items() if value is not None}).encode("utf-8"),
            "headers": [],
        }
    )


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

    def test_ranking_json_marks_no_scope_as_implicit_latest_preview(self) -> None:
        with (
            patch.object(
                analytics_routes.warehouse,
                "metric_ranking",
                return_value={"fields": ["author_id", "score"], "rows": [], "total": 0, "run_id": "", "dump_id": ""},
            ),
            patch.object(analytics_routes.warehouse, "analysis_filter_warnings", return_value=[]),
        ):
            payload = analytics_routes.ranking_json(fraction_mode="integer", metric="h", limit=100)

        self.assertEqual(payload["scope_status"], "implicit_latest_preview")
        self.assertEqual(payload["reproducible"], False)
        self.assertIn("No run_id or dump_id was provided", payload["scope_warnings"][0])

    def test_ranking_json_does_not_treat_unrequested_resolved_scope_as_reproducible(self) -> None:
        with (
            patch.object(
                analytics_routes.warehouse,
                "metric_ranking",
                return_value={"fields": ["author_id", "score"], "rows": [], "total": 0, "run_id": "run_latest", "dump_id": "dump_latest"},
            ),
            patch.object(analytics_routes.warehouse, "analysis_filter_warnings", return_value=[]),
        ):
            payload = analytics_routes.ranking_json(fraction_mode="integer", metric="h", limit=100)

        self.assertEqual(payload["scope_status"], "implicit_latest_preview")
        self.assertEqual(payload["reproducible"], False)

    def test_ranking_json_marks_explicit_scope_as_reproducible(self) -> None:
        with (
            patch.object(
                analytics_routes.warehouse,
                "metric_ranking",
                return_value={"fields": ["author_id", "score"], "rows": [], "total": 0, "run_id": "run_a", "dump_id": "dump_a"},
            ),
            patch.object(analytics_routes.warehouse, "analysis_filter_warnings", return_value=[]),
        ):
            payload = analytics_routes.ranking_json(run_id="run_a", dump_id="dump_a", fraction_mode="integer", metric="h", limit=100)

        self.assertEqual(payload["scope_status"], "explicit_scope")
        self.assertEqual(payload["reproducible"], True)
        self.assertEqual(payload["scope_warnings"], [])

    def test_distribution_marks_no_scope_as_implicit_latest_preview(self) -> None:
        with (
            patch.object(
                analytics_routes.warehouse,
                "metric_distribution",
                return_value={"histogram": [], "run_id": "", "dump_id": ""},
            ),
            patch.object(analytics_routes.warehouse, "analysis_filter_warnings", return_value=[]),
        ):
            payload = analytics_routes.distribution(fraction_mode="integer", metric="h")

        self.assertEqual(payload["scope_status"], "implicit_latest_preview")
        self.assertEqual(payload["reproducible"], False)
        self.assertIn("No run_id or dump_id was provided", payload["scope_warnings"][0])

    def test_ranking_csv_with_empty_cohort_has_header_only(self) -> None:
        cohort = {
            "cohort": {
                "cohort_id": "cohort_empty",
                "name": "Empty Cohort",
                "source": "manual",
                "n_authors": 0,
                "checksum": "empty",
            },
            "author_ids": set(),
            "run_id": "run_a",
            "dump_id": "dump_a",
            "fraction_mode": "integer",
            "filters": {},
        }

        with (
            patch.object(analytics_routes.cohorts, "resolve_cohort_context", return_value=cohort),
            patch.object(analytics_routes.warehouse, "metric_ranking", return_value={"fields": ["author_id", "score"], "rows": [], "total": 0}),
            patch.object(analytics_routes.warehouse, "analysis_filter_warnings", return_value=[]),
        ):
            response = analytics_routes.ranking_csv(cohort_id="cohort_empty", fraction_mode="integer", metric="h", limit=100)

        self.assertEqual(response.body.decode("utf-8").strip(), "author_id,score")

    def test_unknown_cohort_returns_controlled_error(self) -> None:
        with patch.object(analytics_routes.cohorts, "resolve_cohort_context", side_effect=analytics_routes.cohorts.CohortNotFound("Unknown cohort_id: nope")):
            with self.assertRaises(analytics_routes.HTTPException) as raised:
                analytics_routes.ranking_json(cohort_id="nope", fraction_mode="integer", metric="h", limit=100)

        self.assertEqual(raised.exception.status_code, 404)

    def test_scientometric_analysis_route_forwards_scope_filters_and_metrics(self) -> None:
        captured: dict[str, object] = {}

        def fake_analysis(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {"analysis_version": "scientometrics_v4", "n_authors": 2}

        with patch.object(analytics_routes.scientometrics, "build_scientometric_analysis", side_effect=fake_analysis):
            payload = analytics_routes.scientometric_analysis(
                run_id="run_a",
                dump_id="dump_a",
                cohort_id="cohort_a",
                cohort_filter_policy="none",
                fraction_mode="integer",
                metrics="h,g,islv",
                baseline_metric="h",
                top_n=50,
                country_code="ru",
                filter_mode="search",
                text_search_query="ergodesign",
                work_type="article",
            )

        self.assertEqual(payload["analysis_version"], "scientometrics_v4")
        self.assertEqual(captured["run_id"], "run_a")
        self.assertEqual(captured["dump_id"], "dump_a")
        self.assertEqual(captured["cohort_id"], "cohort_a")
        self.assertEqual(captured["cohort_filter_policy"], "none")
        self.assertEqual(captured["fraction_mode"], "integer")
        self.assertEqual(captured["metrics"], ["h", "g", "islv"])
        self.assertEqual(captured["baseline_metric"], "h")
        self.assertEqual(captured["top_n"], 50)
        self.assertEqual(captured["filters"], {"country_code": "RU", "filter_mode": "search", "text_search_query": "ergodesign", "work_type": "article"})

    def test_scientometric_analysis_marks_no_scope_as_preview_warning(self) -> None:
        payload = {
            "analysis_version": "scientometrics_v4",
            "scope": {"run_id": "", "dump_id": ""},
            "warnings": [],
            "n_authors": 0,
        }
        with patch.object(analytics_routes.scientometrics, "build_scientometric_analysis", return_value=payload):
            result = analytics_routes.scientometric_analysis(fraction_mode="integer", metrics="h", baseline_metric="h", top_n=100)

        self.assertEqual(result["scope_status"], "implicit_latest_preview")
        self.assertEqual(result["scope"]["scope_status"], "implicit_latest_preview")
        self.assertEqual(result["scope"]["reproducible"], False)
        self.assertEqual(result["reproducible"], False)
        self.assertIn("No run_id or dump_id was provided", result["warnings"][0])

    def test_scientometric_export_routes_return_csv_artifacts(self) -> None:
        payload = {
            "analysis_version": "scientometrics_v4",
            "descriptive": {
                "h": {
                    "n": 2,
                    "missing_count": 0,
                    "zero_count": 0,
                    "zero_rate": 0.0,
                    "min": 1,
                    "q1": 1,
                    "median": 2,
                    "q3": 3,
                    "max": 3,
                    "mean": 2,
                    "stddev": 1,
                    "coefficient_of_variation": 0.5,
                    "iqr": 2,
                    "tie_rate": 0.0,
                    "outlier_count_iqr": 0,
                    "outlier_share_iqr": 0.0,
                }
            },
            "correlations": {
                "spearman": {"h": {"g": 0.5}},
                "pearson_log1p": {"h": {"g": 0.6}},
                "kendall_tau_b": {"matrix": {"h": {"g": 0.4}}, "skipped": []},
            },
            "rank_comparisons": {
                "g": {
                    "baseline_metric": "h",
                    "largest_shifts": [
                        {
                            "author_id": "https://openalex.org/A1",
                            "author_display_name": "Author One",
                            "baseline_rank": 1,
                            "metric_rank": 3,
                            "rank_delta": 2,
                            "abs_rank_delta": 2,
                        }
                    ],
                }
            },
            "boxplots": {"c": {"outlier_rule": "iqr_1_5", "lower_fence": 0, "upper_fence": 10}},
            "outliers": {"c": [{"author_id": "https://openalex.org/A2", "author_display_name": "Author Two", "value": 99}]},
            "findings": [
                {
                    "id": "heavy_tail:c",
                    "type": "heavy_tail_distribution",
                    "metric": "c",
                    "baseline_metric": None,
                    "severity": "high",
                    "text": "Метрика C имеет тяжелый хвост.",
                    "recommendation": "Использовать log1p.",
                    "evidence": {"skewness": 2.5},
                }
            ],
            "conclusion_draft": {
                "title": "Вывод по сравнению наукометрических индексов",
                "paragraphs": [
                    {
                        "role": "distribution_limits",
                        "text": "Метрика C имеет тяжелый хвост.",
                        "evidence_finding_ids": ["heavy_tail:c"],
                        "evidence_metrics": ["c"],
                    }
                ],
                "limitations": ["Метрики не заменяют экспертную оценку."],
            },
        }
        full_rank_shift_rows = [
            {
                "baseline_metric": "h",
                "compare_metric": "g",
                "author_id": "https://openalex.org/A1",
                "author_display_name": "Author One",
                "baseline_rank": 1,
                "metric_rank": 3,
                "rank_delta": 2,
                "abs_rank_delta": 2,
            },
            {
                "baseline_metric": "h",
                "compare_metric": "g",
                "author_id": "https://openalex.org/A2",
                "author_display_name": "Author Two",
                "baseline_rank": 2,
                "metric_rank": 2,
                "rank_delta": 0,
                "abs_rank_delta": 0,
            },
        ]
        full_outlier_rows = [
            {
                "metric": "c",
                "author_id": "https://openalex.org/A2",
                "author_display_name": "Author Two",
                "value": 99,
                "rule": "iqr_1_5",
                "lower_fence": 0,
                "upper_fence": 10,
            }
        ]

        with (
            patch.object(analytics_routes.scientometrics, "build_scientometric_analysis", return_value=payload),
            patch.object(analytics_routes.scientometrics, "build_rank_shift_export_rows", return_value=full_rank_shift_rows),
            patch.object(analytics_routes.scientometrics, "build_outlier_export_rows", return_value=full_outlier_rows),
        ):
            descriptive = analytics_routes.scientometric_descriptive_csv(_request(metrics="h,g", baseline_metric="h", top_n=20))
            correlations = analytics_routes.scientometric_correlations_csv(_request(metrics="h,g"))
            rank_shifts = analytics_routes.scientometric_rank_shifts_csv(_request(metrics="h,g"))
            largest_rank_shifts = analytics_routes.scientometric_largest_rank_shifts_csv(_request(metrics="h,g"))
            outliers = analytics_routes.scientometric_outliers_csv(_request(metrics="h,c"))
            top_outliers = analytics_routes.scientometric_top_outliers_csv(_request(metrics="h,c"))
            findings = analytics_routes.scientometric_findings_csv(_request(metrics="h,c"))
            conclusion = analytics_routes.scientometric_conclusion_markdown(_request(metrics="h,c"))

        self.assertIn("metric,n,missing_count", descriptive.body.decode("utf-8"))
        self.assertIn("h,2,0", descriptive.body.decode("utf-8"))
        self.assertIn("method,left_metric,right_metric,value", correlations.body.decode("utf-8"))
        self.assertIn("kendall_tau_b,h,g,0.4", correlations.body.decode("utf-8"))
        self.assertIn("baseline_metric,compare_metric,author_id", rank_shifts.body.decode("utf-8"))
        self.assertIn("h,g,https://openalex.org/A1", rank_shifts.body.decode("utf-8"))
        self.assertIn("h,g,https://openalex.org/A2", rank_shifts.body.decode("utf-8"))
        self.assertIn("h,g,https://openalex.org/A1", largest_rank_shifts.body.decode("utf-8"))
        self.assertIn("metric,author_id,author_display_name,value,rule,lower_fence,upper_fence", outliers.body.decode("utf-8"))
        self.assertIn("c,https://openalex.org/A2,Author Two,99,iqr_1_5,0,10", outliers.body.decode("utf-8"))
        self.assertIn("c,https://openalex.org/A2,Author Two,99,iqr_1_5,0,10", top_outliers.body.decode("utf-8"))
        self.assertIn("id,type,metric,baseline_metric,severity,text,recommendation,evidence_json", findings.body.decode("utf-8"))
        self.assertIn("heavy_tail:c,heavy_tail_distribution,c,,high", findings.body.decode("utf-8"))
        self.assertIn('"{""skewness"": 2.5}"', findings.body.decode("utf-8"))
        conclusion_text = conclusion.body.decode("utf-8")
        self.assertEqual(conclusion.media_type, "text/markdown; charset=utf-8")
        self.assertIn("# Вывод по сравнению наукометрических индексов", conclusion_text)
        self.assertIn("## Распределения", conclusion_text)
        self.assertIn("Основания: heavy_tail:c", conclusion_text)
        self.assertIn("Метрики: C", conclusion_text)
        self.assertIn("- Метрики не заменяют экспертную оценку.", conclusion_text)

    def test_cohort_statistics_route_forwards_analysis_scope(self) -> None:
        captured: dict[str, object] = {}

        def fake_statistics(cohort_id: str, **kwargs: object) -> dict[str, object]:
            captured["cohort_id"] = cohort_id
            captured["kwargs"] = kwargs
            return {"cohort_id": cohort_id, "n_rows": 1}

        with patch.object(cohort_routes.cohorts, "cohort_statistics", side_effect=fake_statistics):
            payload = cohort_routes.cohort_statistics(
                "cohort_a",
                run_id="run_a",
                dump_id="dump_a",
                fraction_mode="integer",
                country_code="de",
                filter_mode="search",
                text_search_query="ergodesign",
                cohort_filter_policy="current",
            )

        self.assertEqual(payload["n_rows"], 1)
        self.assertEqual(captured["cohort_id"], "cohort_a")
        self.assertEqual(
            captured["kwargs"],
            {
                "run_id": "run_a",
                "dump_id": "dump_a",
                "fraction_mode": "integer",
                "filters": {"country_code": "DE", "filter_mode": "search", "text_search_query": "ergodesign"},
                "filter_policy": "current",
            },
        )

    def test_cohort_author_metrics_routes_forward_metric_and_scope(self) -> None:
        captured: dict[str, object] = {}

        def fake_payload(cohort_id: str, **kwargs: object) -> dict[str, object]:
            captured["json"] = {"cohort_id": cohort_id, **kwargs}
            return {"fields": ["author_id", "h"], "rows": [{"author_id": "https://openalex.org/A1", "h": 3}], "total": 1}

        def fake_csv(cohort_id: str, **kwargs: object) -> str:
            captured["csv"] = {"cohort_id": cohort_id, **kwargs}
            return "author_id,h\nhttps://openalex.org/A1,3\n"

        with (
            patch.object(cohort_routes.cohorts, "cohort_author_metrics", side_effect=fake_payload),
            patch.object(cohort_routes.cohorts, "cohort_author_metrics_csv", side_effect=fake_csv),
        ):
            json_payload = cohort_routes.cohort_author_metrics_json(
                "cohort_a",
                run_id="run_a",
                dump_id="dump_a",
                fraction_mode="integer",
                metric="islv",
                country_code="ru",
                cohort_filter_policy="none",
                limit=50,
            )
            csv_response = cohort_routes.cohort_author_metrics_csv(
                "cohort_a",
                run_id="run_a",
                dump_id="dump_a",
                fraction_mode="integer",
                metric="islv",
                country_code="ru",
                cohort_filter_policy="none",
                limit=50,
            )

        self.assertEqual(json_payload["total"], 1)
        self.assertEqual(captured["json"]["metric"], "islv")
        self.assertEqual(captured["json"]["filters"], {"country_code": "RU"})
        self.assertEqual(captured["json"]["filter_policy"], "none")
        self.assertEqual(captured["csv"]["metric"], "islv")
        self.assertEqual(captured["csv"]["filter_policy"], "none")
        self.assertIn("author_metrics", csv_response.headers["Content-Disposition"])
        self.assertIn("https://openalex.org/A1", csv_response.body.decode("utf-8"))

    def test_cohort_routes_unknown_cohort_returns_404(self) -> None:
        with patch.object(cohort_routes.cohorts, "cohort_author_metrics", side_effect=cohort_routes.cohorts.CohortNotFound("Unknown cohort_id: nope")):
            with self.assertRaises(cohort_routes.HTTPException) as raised:
                cohort_routes.cohort_author_metrics_json("nope")

        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
