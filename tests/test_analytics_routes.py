from __future__ import annotations

import asyncio
import sys
import tempfile
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


def _response_text(response: object) -> str:
    body_iterator = getattr(response, "body_iterator", None)
    if body_iterator is None:
        return getattr(response, "body").decode("utf-8")

    async def collect() -> bytes:
        chunks: list[bytes] = []
        async for chunk in body_iterator:
            chunks.append(chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8"))
        return b"".join(chunks)

    return asyncio.run(collect()).decode("utf-8")


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
        self.assertEqual(
            captured["kwargs"],
            {"limit": 25, "max_limit": analytics_routes.JSON_RESULT_MAX_ROWS, "run_id": "run_a", "dump_id": "dump_a", "author_ids": None, "custom_metric_defs": []},
        )
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

    def test_ranking_csv_keeps_export_scale_limit(self) -> None:
        captured: dict[str, object] = {}

        def fake_stream(fraction_mode: str, metric: str, filters: dict[str, str], **kwargs: object) -> list[str]:
            captured["kwargs"] = kwargs
            return ["author_id,score\n", "A1,1\n"]

        with (
            patch.object(analytics_routes.warehouse, "iter_metric_ranking_csv", side_effect=fake_stream),
            patch.object(analytics_routes.warehouse, "analysis_filter_warnings", return_value=[]),
        ):
            response = analytics_routes.ranking_csv(run_id="run_a", dump_id="dump_a", metric="h", limit=100_000)

        self.assertIn("A1", _response_text(response))
        self.assertEqual(captured["kwargs"]["max_limit"], analytics_routes.EXPORT_RESULT_MAX_ROWS)
        self.assertEqual(captured["kwargs"]["limit"], 100_000)

    def test_ranking_json_without_scope_requires_scope(self) -> None:
        with (
            patch.object(
                analytics_routes.warehouse,
                "metric_ranking",
                return_value={"fields": ["author_id", "score"], "rows": [], "total": 0, "run_id": "", "dump_id": ""},
            ) as metric_ranking,
            patch.object(analytics_routes.warehouse, "analysis_filter_warnings", return_value=[]),
        ):
            with self.assertRaises(analytics_routes.HTTPException) as raised:
                analytics_routes.ranking_json(fraction_mode="integer", metric="h", limit=100)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("run_id or dump_id is required", str(raised.exception.detail))
        metric_ranking.assert_not_called()

    def test_ranking_json_rejects_unrequested_resolved_scope(self) -> None:
        with (
            patch.object(
                analytics_routes.warehouse,
                "metric_ranking",
                return_value={"fields": ["author_id", "score"], "rows": [], "total": 0, "run_id": "run_resolved", "dump_id": "dump_resolved"},
            ),
            patch.object(analytics_routes.warehouse, "analysis_filter_warnings", return_value=[]),
        ):
            with self.assertRaises(analytics_routes.HTTPException) as raised:
                analytics_routes.ranking_json(fraction_mode="integer", metric="h", limit=100)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("run_id or dump_id is required", str(raised.exception.detail))

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
        self.assertEqual(payload["warnings"], [])

    def test_ranking_json_forwards_data_selection_contract(self) -> None:
        captured: dict[str, object] = {}

        def fake_ranking(fraction_mode: str, metric: str, filters: dict[str, str], **kwargs: object) -> dict[str, object]:
            del fraction_mode, metric, filters
            captured.update(kwargs)
            return {"fields": ["author_id", "score"], "rows": [], "total": 0, "run_id": "run_a", "dump_id": "dump_a"}

        with (
            patch.object(analytics_routes.warehouse, "metric_ranking", side_effect=fake_ranking),
            patch.object(analytics_routes.warehouse, "analysis_filter_warnings", return_value=[]),
        ):
            analytics_routes.ranking_json(
                run_id="run_a",
                dump_id="dump_a",
                fraction_mode="integer",
                metric="h",
                data_filters='{"h":{"min":"3"}}',
                data_sort="h",
                data_direction="asc",
                data_limit=25,
                limit=100,
            )

        self.assertEqual(captured["data_filters"], {"h": {"min": "3"}})
        self.assertEqual(captured["data_sort"], "h")
        self.assertEqual(captured["data_direction"], "asc")
        self.assertEqual(captured["data_limit"], 25)

    def test_analytics_accepts_zero_limit_for_all_rows(self) -> None:
        captured: dict[str, object] = {}

        def fake_bundle(fraction_mode: str, metric: str, filters: dict[str, str], **kwargs: object) -> dict[str, object]:
            del fraction_mode, metric, filters
            captured.update(kwargs)
            table = {"fields": ["author_id", "score"], "rows": [], "total": 0, "run_id": "run_a", "dump_id": "dump_a"}
            return {"distribution": {"run_id": "run_a", "dump_id": "dump_a"}, "ranking": table, "line_series": {"rows": []}}

        with (
            patch.object(analytics_routes.warehouse, "metric_bundle", side_effect=fake_bundle),
            patch.object(analytics_routes.warehouse, "analysis_filter_warnings", return_value=[]),
        ):
            payload = analytics_routes.analytics(run_id="run_a", dump_id="dump_a", fraction_mode="integer", metric="h", limit=0)

        self.assertEqual(captured["limit"], 0)
        self.assertEqual(payload["scope_status"], "explicit_scope")

    def test_distribution_without_scope_requires_scope(self) -> None:
        with (
            patch.object(
                analytics_routes.warehouse,
                "metric_distribution",
                return_value={"histogram": [], "run_id": "", "dump_id": ""},
            ) as metric_distribution,
            patch.object(analytics_routes.warehouse, "analysis_filter_warnings", return_value=[]),
        ):
            with self.assertRaises(analytics_routes.HTTPException) as raised:
                analytics_routes.distribution(fraction_mode="integer", metric="h")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("run_id or dump_id is required", str(raised.exception.detail))
        metric_distribution.assert_not_called()

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
            patch.object(analytics_routes.warehouse, "iter_metric_ranking_csv", return_value=["author_id,score\n"]),
            patch.object(analytics_routes.warehouse, "analysis_filter_warnings", return_value=[]),
        ):
            response = analytics_routes.ranking_csv(cohort_id="cohort_empty", fraction_mode="integer", metric="h", limit=100)

        self.assertEqual(_response_text(response).strip(), "author_id,score")
        self.assertEqual(response.headers["X-OpenAlex-DSS-Scope-Status"], "cohort_resolved_scope")
        self.assertEqual(response.headers["X-OpenAlex-DSS-Reproducible"], "true")

    def test_ranking_csv_without_scope_requires_scope(self) -> None:
        with (
            patch.object(
                analytics_routes.warehouse,
                "metric_ranking",
                return_value={"fields": ["author_id", "score"], "rows": [], "total": 0, "run_id": "", "dump_id": ""},
            ),
            patch.object(analytics_routes.warehouse, "analysis_filter_warnings", return_value=[]),
        ):
            with self.assertRaises(analytics_routes.HTTPException) as raised:
                analytics_routes.ranking_csv(fraction_mode="integer", metric="h", limit=100)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("run_id or dump_id is required", str(raised.exception.detail))

    def test_custom_metric_models_can_be_saved_listed_and_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(analytics_routes.custom_metrics, "DATA", Path(tmp)):
                saved = analytics_routes.save_custom_metric_model(
                    {
                        "run_id": "run_a",
                        "id": "my_rating",
                        "label": "Мой рейтинг",
                        "description": "Проверочная формула",
                        "expression": "100 * pr_h",
                    }
                )
                listed = analytics_routes.list_custom_metric_models(run_id="run_a")
                deleted = analytics_routes.delete_custom_metric_model("custom_my_rating", run_id="run_a")

        self.assertEqual(saved["model"]["id"], "custom_my_rating")
        self.assertEqual(listed["models"][0]["label"], "Мой рейтинг")
        self.assertTrue(deleted["deleted"])

    def test_custom_metric_model_invalid_formula_returns_controlled_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(analytics_routes.custom_metrics, "DATA", Path(tmp)):
            with self.assertRaises(analytics_routes.HTTPException) as raised:
                analytics_routes.save_custom_metric_model({"run_id": "run_a", "label": "Bad", "expression": "unknown + 1"})

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Неизвестное поле", str(raised.exception.detail))

    def test_unknown_cohort_returns_controlled_error(self) -> None:
        with patch.object(analytics_routes.cohorts, "resolve_cohort_context", side_effect=analytics_routes.cohorts.CohortNotFound("Unknown cohort_id: nope")):
            with self.assertRaises(analytics_routes.HTTPException) as raised:
                analytics_routes.ranking_json(cohort_id="nope", fraction_mode="integer", metric="h", limit=100)

        self.assertEqual(raised.exception.status_code, 404)

    def test_scientometric_analysis_route_forwards_scope_filters_and_metrics(self) -> None:
        captured: dict[str, object] = {}

        def fake_analysis(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {"schema": "scientometric_analysis", "n_authors": 2}

        with patch.object(analytics_routes.scientometric_workflow, "build_scientometric_analysis", side_effect=fake_analysis):
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

        self.assertEqual(payload["schema"], "scientometric_analysis")
        self.assertEqual(captured["run_id"], "run_a")
        self.assertEqual(captured["dump_id"], "dump_a")
        self.assertEqual(captured["cohort_id"], "cohort_a")
        self.assertEqual(captured["cohort_filter_policy"], "none")
        self.assertEqual(captured["fraction_mode"], "integer")
        self.assertEqual(captured["metrics"], ["h", "g", "islv"])
        self.assertEqual(captured["baseline_metric"], "h")
        self.assertEqual(captured["top_n"], 50)
        self.assertEqual(captured["filters"], {"country_code": "RU", "filter_mode": "search", "text_search_query": "ergodesign", "work_type": "article"})

    def test_scientometric_analysis_without_scope_requires_scope(self) -> None:
        payload = {
            "schema": "scientometric_analysis",
            "scope": {"run_id": "", "dump_id": ""},
            "warnings": [],
            "n_authors": 0,
        }
        with patch.object(analytics_routes.scientometric_workflow, "build_scientometric_analysis", return_value=payload):
            with self.assertRaises(analytics_routes.HTTPException) as raised:
                analytics_routes.scientometric_analysis(fraction_mode="integer", metrics="h", baseline_metric="h", top_n=100)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("run_id or dump_id is required", str(raised.exception.detail))

    def test_scientometric_export_routes_return_csv_artifacts(self) -> None:
        payload = {
            "schema": "scientometric_analysis",
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
            patch.object(analytics_routes.scientometric_workflow, "build_scientometric_analysis", return_value=payload),
            patch.object(analytics_routes.scientometric_workflow, "build_outlier_export_rows", return_value=full_outlier_rows),
        ):
            descriptive = analytics_routes.scientometric_descriptive_csv(_request(run_id="run_a", dump_id="dump_a", metrics="h,g", baseline_metric="h", top_n=20))
            correlations = analytics_routes.scientometric_correlations_csv(_request(run_id="run_a", dump_id="dump_a", metrics="h,g"))
            outliers = analytics_routes.scientometric_outliers_csv(_request(run_id="run_a", dump_id="dump_a", metrics="h,c"))
            top_outliers = analytics_routes.scientometric_top_outliers_csv(_request(run_id="run_a", dump_id="dump_a", metrics="h,c"))
            findings = analytics_routes.scientometric_findings_csv(_request(run_id="run_a", dump_id="dump_a", metrics="h,c"))
            conclusion = analytics_routes.scientometric_conclusion_markdown(_request(run_id="run_a", dump_id="dump_a", metrics="h,c"))

        self.assertIn("metric,n,missing_count", descriptive.body.decode("utf-8"))
        self.assertEqual(descriptive.headers["X-OpenAlex-DSS-Scope-Status"], "explicit_scope")
        self.assertIn("h,2,0", descriptive.body.decode("utf-8"))
        self.assertIn("method,left_metric,right_metric,value", correlations.body.decode("utf-8"))
        self.assertIn("kendall_tau_b,h,g,0.4", correlations.body.decode("utf-8"))
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
        self.assertIn("Метрики: Цитирования", conclusion_text)
        self.assertIn("- Метрики не заменяют экспертную оценку.", conclusion_text)
        self.assertEqual(conclusion.headers["X-OpenAlex-DSS-Scope-Status"], "explicit_scope")

    def test_scientometric_export_without_scope_requires_scope(self) -> None:
        payload = {
            "schema": "scientometric_analysis",
            "scope": {"run_id": "", "dump_id": ""},
            "descriptive": {},
            "warnings": [],
        }
        with patch.object(analytics_routes.scientometric_workflow, "build_scientometric_analysis", return_value=payload):
            with self.assertRaises(analytics_routes.HTTPException) as raised:
                analytics_routes.scientometric_descriptive_csv(_request(metrics="h"))

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("run_id or dump_id is required", str(raised.exception.detail))

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
