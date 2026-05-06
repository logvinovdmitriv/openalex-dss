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

from app.services import scientometrics  # noqa: E402


class ScientometricServiceTests(unittest.TestCase):
    def test_describe_metrics_counts_distribution_shape(self) -> None:
        rows = [
            {"author_id": "A1", "h": 0},
            {"author_id": "A2", "h": 0},
            {"author_id": "A3", "h": 1},
            {"author_id": "A4", "h": 2},
            {"author_id": "A5", "h": 100},
        ]

        summary = scientometrics.describe_metrics(rows, ["h"])["h"]

        self.assertEqual(summary["n"], 5)
        self.assertEqual(summary["zero_count"], 2)
        self.assertAlmostEqual(summary["zero_rate"], 0.4)
        self.assertEqual(summary["median"], 1.0)
        self.assertGreater(summary["tie_rate"], 0)
        self.assertEqual(summary["outlier_count_iqr"], 1)

    def test_boxplot_metrics_keeps_top_outliers(self) -> None:
        rows = [
            {"author_id": "A1", "author_display_name": "One", "c": 1},
            {"author_id": "A2", "author_display_name": "Two", "c": 2},
            {"author_id": "A3", "author_display_name": "Three", "c": 3},
            {"author_id": "A4", "author_display_name": "Four", "c": 4},
            {"author_id": "A5", "author_display_name": "Five", "c": 200},
        ]

        boxplot = scientometrics.boxplot_metrics(rows, ["c"])["c"]

        self.assertEqual(boxplot["outlier_count"], 1)
        self.assertEqual(boxplot["outliers"][0]["author_id"], "A5")
        self.assertEqual(boxplot["outliers"][0]["value"], 200.0)

    def test_histogram_metrics_returns_raw_and_log1p_bins(self) -> None:
        rows = [{"author_id": f"A{index}", "c": value} for index, value in enumerate([0, 1, 2, 8, 16], start=1)]

        histograms = scientometrics.histogram_metrics(rows, ["c"], bins=4)["c"]

        self.assertEqual(sum(bucket["count"] for bucket in histograms["raw"]), 5)
        self.assertEqual(sum(bucket["count"] for bucket in histograms["log1p"]), 5)
        self.assertLessEqual(len(histograms["raw"]), 4)

    def test_correlations_and_rank_comparisons_are_metric_scoped(self) -> None:
        rows = [
            {"author_id": "A1", "author_display_name": "A One", "h": 5, "g": 10, "c_frac": 50},
            {"author_id": "A2", "author_display_name": "A Two", "h": 4, "g": 8, "c_frac": 40},
            {"author_id": "A3", "author_display_name": "A Three", "h": 3, "g": 6, "c_frac": 500},
            {"author_id": "A4", "author_display_name": "A Four", "h": 1, "g": 2, "c_frac": 10},
        ]

        correlations = scientometrics.correlation_matrices(rows, ["h", "g", "c_frac"])
        rank_payload = scientometrics.rank_comparisons(rows, ["h", "g", "c_frac"], baseline_metric="h", top_n=2)

        self.assertAlmostEqual(correlations["spearman"]["h"]["g"], 1.0)
        self.assertIn("c_frac", rank_payload["comparisons"])
        self.assertGreater(rank_payload["comparisons"]["c_frac"]["max_abs_delta"], 0)
        self.assertEqual(rank_payload["top_overlap"]["matrix"]["h"]["g"]["2"]["overlap"], 2)

    def test_iqr_zero_boxplot_does_not_create_false_outliers(self) -> None:
        rows = [
            {"author_id": "A1", "h": 1},
            {"author_id": "A2", "h": 1},
            {"author_id": "A3", "h": 1},
            {"author_id": "A4", "h": 1},
            {"author_id": "A5", "h": 2},
        ]

        summary = scientometrics.describe_metrics(rows, ["h"])["h"]
        boxplot = scientometrics.boxplot_metrics(rows, ["h"])["h"]

        self.assertEqual(summary["iqr"], 0.0)
        self.assertEqual(summary["outlier_count_iqr"], 0)
        self.assertEqual(boxplot["outliers"], [])
        self.assertEqual(boxplot["outlier_rule"], "iqr_zero_no_outlier_fence")

    def test_top_overlap_exact_n_does_not_expand_tied_rank_cut(self) -> None:
        rows = [
            {"author_id": "A1", "h": 10, "c": 10},
            {"author_id": "A2", "h": 1, "c": 9},
            {"author_id": "A3", "h": 1, "c": 8},
            {"author_id": "A4", "h": 1, "c": 7},
        ]

        payload = scientometrics.rank_comparisons(rows, ["h", "c"], baseline_metric="h", rank_top_n=2)
        overlap = payload["top_overlap"]["matrix"]["h"]["c"]["2"]

        self.assertEqual(payload["top_overlap"]["mode"], "exact_n_by_competition_rank_then_author_id")
        self.assertEqual(overlap["left_n"], 2)
        self.assertEqual(overlap["right_n"], 2)
        self.assertLessEqual(overlap["overlap"], 2)

    def test_kendall_tau_b_skips_large_inputs_instead_of_truncating_silently(self) -> None:
        rows = [{"author_id": f"A{index}", "h": index, "g": index} for index in range(1001)]

        correlations = scientometrics.correlation_matrices(rows, ["h", "g"])
        kendall = correlations["kendall_tau_b"]

        self.assertIsNone(kendall["matrix"]["h"]["g"])
        self.assertTrue(kendall["skipped"])
        self.assertEqual(kendall["max_exact_n"], 1000)

    def test_scorecard_dependence_keeps_signed_and_absolute_correlation(self) -> None:
        rows = [
            {"author_id": "A1", "islv": 3, "top1_share": 0.0},
            {"author_id": "A2", "islv": 2, "top1_share": 0.5},
            {"author_id": "A3", "islv": 1, "top1_share": 1.0},
        ]

        scorecard = scientometrics.metric_scorecard(rows, ["islv"])
        dependence = scorecard["islv"]["top1_dominance_dependence"]

        self.assertEqual(dependence["direction"], "negative")
        self.assertLess(dependence["spearman_rho"], 0)
        self.assertEqual(dependence["abs_spearman_rho"], abs(dependence["spearman_rho"]))

    def test_build_analysis_applies_cohort_scope_and_policy(self) -> None:
        captured: dict[str, object] = {}
        cohort_ctx = {
            "cohort": {
                "cohort_id": "cohort_a",
                "name": "Cohort A",
                "source": "top_n",
                "metric": "h",
                "fraction_mode": "integer",
                "n_authors": 1,
                "checksum": "sha",
            },
            "author_ids": {"A2"},
            "run_id": "run_a",
            "dump_id": "dump_a",
            "fraction_mode": "integer",
            "filters": {"country_code": "DE"},
            "analysis_filters": {"country_code": "DE"},
            "membership_filters": {"country_code": "RU"},
            "filter_policy": "current",
            "resolved_filter_mode": "analysis_override",
            "filter_mode": "analysis_override",
        }

        def fake_filtered(fraction_mode: str, filters: dict[str, object], **kwargs: object) -> list[dict[str, object]]:
            captured["fraction_mode"] = fraction_mode
            captured["filters"] = filters
            captured["kwargs"] = kwargs
            return [
                {"author_id": "A1", "h": 5, "c": 50, "c_frac": 25, "g": 8, "i10": 2, "islv": 80},
                {"author_id": "A2", "h": 3, "c": 30, "c_frac": 20, "g": 6, "i10": 1, "islv": 60},
            ]

        with (
            patch.object(scientometrics.cohorts, "resolve_cohort_context", return_value=cohort_ctx),
            patch.object(scientometrics.warehouse, "filtered_author_indices", side_effect=fake_filtered),
        ):
            payload = scientometrics.build_scientometric_analysis(
                fraction_mode="integer",
                metrics=["h", "c", "islv"],
                baseline_metric="h",
                filters={"country_code": "DE"},
                run_id="run_a",
                cohort_id="cohort_a",
                cohort_filter_policy="current",
                top_n=10,
            )

        self.assertEqual(captured["fraction_mode"], "integer")
        self.assertEqual(captured["filters"], {"country_code": "DE"})
        self.assertEqual(captured["kwargs"], {"run_id": "run_a", "dump_id": "dump_a"})
        self.assertEqual(payload["n_authors"], 1)
        self.assertEqual(payload["scope"]["cohort_filter_policy"], "current")
        self.assertEqual(payload["scope"]["analysis_author_scope"], "all_resolved_authors")
        self.assertEqual(payload["scope"]["rank_top_n"], 10)
        self.assertEqual(payload["cohort_context"]["analysis_filters"], {"country_code": "DE"})

    def test_empty_analysis_returns_warning_without_crashing(self) -> None:
        with patch.object(scientometrics.warehouse, "filtered_author_indices", return_value=[]):
            payload = scientometrics.build_scientometric_analysis(
                fraction_mode="integer",
                metrics=["h", "g"],
                baseline_metric="h",
                run_id="run_empty",
            )

        self.assertEqual(payload["n_authors"], 0)
        self.assertEqual(payload["descriptive"]["h"]["n"], 0)
        self.assertTrue(payload["warnings"])
        self.assertIsNone(payload["interpretation"]["candidate_balanced_metric"])
        self.assertNotIn("best_balanced_metric", payload["interpretation"])


if __name__ == "__main__":
    unittest.main()
