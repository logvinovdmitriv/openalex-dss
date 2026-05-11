from __future__ import annotations

import os
import sys
import tempfile
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
        self.assertEqual(rank_payload["top_overlap"]["matrix"]["h"]["g"]["2"]["overlap_rate"], 1.0)

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
        self.assertEqual(boxplot["min_whisker"], 1.0)
        self.assertEqual(boxplot["max_whisker"], 1.0)
        self.assertEqual(boxplot["display_outlier_count"], 1)
        self.assertEqual(boxplot["display_outliers"][0]["author_id"], "A5")
        self.assertEqual(boxplot["outlier_rule"], "iqr_zero_no_outlier_fence")
        self.assertIn("views", boxplot)
        self.assertEqual(boxplot["views"]["nonzero"]["n"], 5)
        self.assertEqual(boxplot["views"]["central_95"]["n"], 4)

    def test_boxplot_metrics_exposes_nonzero_view_for_zero_inflated_metrics(self) -> None:
        rows = [
            {"author_id": "A1", "c": 0},
            {"author_id": "A2", "c": 0},
            {"author_id": "A3", "c": 1},
            {"author_id": "A4", "c": 2},
            {"author_id": "A5", "c": 10},
        ]

        boxplot = scientometrics.boxplot_metrics(rows, ["c"])["c"]

        self.assertEqual(boxplot["median"], 1.0)
        self.assertEqual(boxplot["views"]["nonzero"]["n"], 3)
        self.assertGreater(boxplot["views"]["nonzero"]["median"], 1.0)

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
        self.assertEqual(overlap["overlap_denominator"], 2)
        self.assertLessEqual(overlap["overlap"], 2)

    def test_metric_rank_summary_and_pairwise_table_are_exposed(self) -> None:
        rows = [
            {"author_id": "A1", "author_display_name": "A One", "h": 5, "g": 10, "c": 30},
            {"author_id": "A2", "author_display_name": "A Two", "h": 4, "g": 8, "c": 20},
            {"author_id": "A3", "author_display_name": "A Three", "h": 1, "g": 2, "c": 100},
        ]
        with patch.object(scientometrics.warehouse, "selected_index_rows", return_value=rows):
            payload = scientometrics.build_scientometric_analysis(
                fraction_mode="integer",
                metrics=["h", "g", "c"],
                baseline_metric="h",
                run_id="run_pairwise",
            )

        self.assertEqual(payload["analysis_protocol"]["protocol_id"], "baseline_core_protocol")
        self.assertEqual(payload["metric_groups"]["core"], ["h", "g", "c"])
        self.assertTrue(any(row["metric"] == "h" and row["metric_group"] == "core" for row in payload["metric_rank_summary"]))
        self.assertTrue(any(row["metric_a"] == "h" and row["metric_b"] == "g" for row in payload["pairwise_metric_comparison"]))

    def test_rank_comparisons_keep_largest_rank_changes_bounded(self) -> None:
        rows = [
            {"author_id": f"A{index:02d}", "author_display_name": f"Author {index}", "h": index, "g": 40 - index}
            for index in range(25)
        ]

        payload = scientometrics.rank_comparisons(rows, ["h", "g"], baseline_metric="h", rank_top_n=10)

        self.assertEqual(payload["comparisons"]["g"]["n_common_authors"], 25)
        self.assertEqual(len(payload["comparisons"]["g"]["largest_shifts"]), 20)
        self.assertEqual(payload["comparisons"]["g"]["largest_shifts"][0]["baseline_metric"], "h")
        self.assertEqual(payload["comparisons"]["g"]["largest_shifts"][0]["compare_metric"], "g")

    def test_outlier_rows_export_all_iqr_outliers_while_boxplot_keeps_top_subset(self) -> None:
        rows = (
            [{"author_id": f"A{index:02d}", "author_display_name": f"Base {index}", "c": 0} for index in range(30)]
            + [{"author_id": f"B{index:02d}", "author_display_name": f"Middle {index}", "c": 1} for index in range(15)]
            + [{"author_id": f"C{index:02d}", "author_display_name": f"High {index}", "c": 100 + index} for index in range(12)]
        )

        boxplot = scientometrics.boxplot_metrics(rows, ["c"])["c"]
        export_rows = scientometrics.outlier_rows(rows, ["c"])

        self.assertEqual(boxplot["outlier_count"], 12)
        self.assertEqual(len(boxplot["outliers"]), 10)
        self.assertEqual(len(export_rows), 12)
        self.assertEqual(export_rows[0]["metric"], "c")
        self.assertEqual(export_rows[0]["rule"], "iqr_1_5")
        self.assertIn("upper_fence", export_rows[0])

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

    def test_interpretation_findings_detect_distribution_limits(self) -> None:
        findings = scientometrics.interpretation_findings(
            metrics=["c", "h", "i10"],
            baseline_metric="h",
            n_authors=10,
            descriptive={
                "c": {"zero_rate": 0.0, "tie_rate": 0.0},
                "h": {"zero_rate": 0.0, "tie_rate": 0.5},
                "i10": {"zero_rate": 0.4, "tie_rate": 0.0},
            },
            normality={"c": {"raw": {"skewness": 2.5, "excess_kurtosis": 11.0, "jarque_bera_p_approx": 0.001}}},
            correlations={"spearman": {}},
            rank_comparisons={},
            metric_scorecard={},
        )
        by_type_metric = {(finding["type"], finding["metric"]): finding for finding in findings}

        self.assertEqual(by_type_metric[("heavy_tail_distribution", "c")]["severity"], "high")
        self.assertEqual(by_type_metric[("high_tie_rate", "h")]["severity"], "medium")
        self.assertEqual(by_type_metric[("zero_inflation", "i10")]["severity"], "medium")

    def test_interpretation_findings_detect_dependence_and_rank_relationships(self) -> None:
        scorecard = {
            "p": {"publication_volume_dependence": {"abs_spearman_rho": 0.75, "spearman_rho": 0.75, "direction": "positive"}},
            "c": {"top1_dominance_dependence": {"abs_spearman_rho": 0.72, "spearman_rho": 0.72, "direction": "positive"}},
            "g": {"citation_volume_dependence": {"abs_spearman_rho": 0.92, "spearman_rho": 0.92, "direction": "positive"}},
        }
        findings = scientometrics.interpretation_findings(
            metrics=["h", "p", "c", "g", "islv"],
            baseline_metric="h",
            n_authors=100,
            descriptive={},
            normality={},
            correlations={"spearman": {"h": {"g": 0.95, "islv": 0.4}}},
            rank_comparisons={
                "g": {"p90_abs_delta": 3, "jaccard_top_n_exact": 0.8},
                "islv": {"median_abs_delta": 4, "p90_abs_delta": 25, "jaccard_top_n_exact": 0.4},
            },
            metric_scorecard=scorecard,
            rank_top_n=50,
        )
        by_type_metric = {(finding["type"], finding["metric"]): finding for finding in findings}

        self.assertIn(("publication_volume_dependence", "p"), by_type_metric)
        self.assertIn(("top1_dominance_dependence", "c"), by_type_metric)
        self.assertEqual(by_type_metric[("citation_volume_dependence", "g")]["severity"], "high")
        self.assertIn(("rank_instability", "islv"), by_type_metric)
        self.assertIn(("rank_agreement", "g"), by_type_metric)
        self.assertIn(("productivity_metric", "p"), by_type_metric)
        self.assertIn(("citation_volume_metric", "c"), by_type_metric)

    def test_negative_top1_dependence_is_described_as_correction(self) -> None:
        findings = scientometrics.interpretation_findings(
            metrics=["islv"],
            baseline_metric="h",
            n_authors=20,
            descriptive={},
            normality={},
            correlations={"spearman": {}},
            rank_comparisons={},
            metric_scorecard={
                "islv": {
                    "top1_dominance_dependence": {
                        "abs_spearman_rho": 0.65,
                        "spearman_rho": -0.65,
                        "direction": "negative",
                    }
                }
            },
        )
        top1 = next(finding for finding in findings if finding["type"] == "top1_dominance_dependence")

        self.assertIn("корректирующее", top1["text"])
        self.assertIn("negative", top1["evidence"]["direction"])

    def test_islv_finding_is_candidate_not_best_metric_claim(self) -> None:
        findings = scientometrics.interpretation_findings(
            metrics=["h", "islv"],
            baseline_metric="h",
            n_authors=20,
            descriptive={},
            normality={},
            correlations={"spearman": {}},
            rank_comparisons={},
            metric_scorecard={"islv": {}},
        )
        candidate = next(finding for finding in findings if finding["type"] == "balanced_candidate_metric")

        self.assertEqual(candidate["severity"], "informational")
        self.assertEqual(candidate["evidence"]["uses_fractional_citations"], True)
        self.assertNotIn("best metric", str(candidate["text"]).lower())
        self.assertNotIn("best metric", str(candidate["recommendation"]).lower())

    def test_iupv_s_finding_is_candidate_not_best_metric_claim(self) -> None:
        findings = scientometrics.interpretation_findings(
            metrics=["h", "iupv_s"],
            baseline_metric="h",
            n_authors=20,
            descriptive={},
            normality={},
            correlations={"spearman": {}},
            rank_comparisons={},
            metric_scorecard={"iupv_s": {}},
        )
        candidate = next(finding for finding in findings if finding["id"] == "balanced_candidate:iupv_s")
        summary = scientometrics.finding_summary(findings, metrics=["h", "iupv_s"], baseline_metric="h")

        self.assertEqual(candidate["severity"], "informational")
        self.assertEqual(candidate["evidence"]["uses_rfi_log_fractional_impact"], True)
        self.assertEqual(candidate["evidence"]["uses_positive_only_percentile_scale"], True)
        self.assertEqual(summary["candidate_metric"], "iupv_s")
        self.assertIn("iupv_s", summary["candidate_metrics"])
        self.assertNotIn("best metric", str(candidate["text"]).lower())
        self.assertNotIn("best metric", str(candidate["recommendation"]).lower())

    def test_empty_analysis_does_not_produce_candidate_finding_or_claim(self) -> None:
        findings = scientometrics.interpretation_findings(
            metrics=["h", "islv"],
            baseline_metric="h",
            n_authors=0,
            descriptive={},
            normality={},
            correlations={"spearman": {}},
            rank_comparisons={},
            metric_scorecard={"islv": {}},
        )
        summary = scientometrics.finding_summary(findings, metrics=["h", "islv"], baseline_metric="h")

        self.assertEqual(findings, [])
        self.assertIsNone(summary["candidate_metric"])
        self.assertIsNone(summary["candidate_metric_claim"])

    def test_conclusion_draft_uses_findings_without_claiming_best_metric(self) -> None:
        findings = [
            {
                "id": "heavy_tail:c",
                "type": "heavy_tail_distribution",
                "metric": "c",
                "severity": "high",
                "evidence": {},
                "text": "",
                "recommendation": "",
            },
            {
                "id": "tie_rate:h",
                "type": "high_tie_rate",
                "metric": "h",
                "severity": "medium",
                "evidence": {},
                "text": "",
                "recommendation": "",
            },
            {
                "id": "balanced_candidate:islv",
                "type": "balanced_candidate_metric",
                "metric": "islv",
                "severity": "informational",
                "evidence": {},
                "text": "",
                "recommendation": "",
            },
        ]
        summary = scientometrics.finding_summary(findings, metrics=["c", "h", "islv"], baseline_metric="h")

        draft = scientometrics.conclusion_draft(
            findings=findings,
            finding_summary=summary,
            metrics=["c", "h", "islv"],
            baseline_metric="h",
            n_authors=42,
            scope={"fraction_mode": "integer"},
        )
        roles = [paragraph["role"] for paragraph in draft["paragraphs"]]
        text = " ".join(paragraph["text"] for paragraph in draft["paragraphs"])
        distribution = next(paragraph for paragraph in draft["paragraphs"] if paragraph["role"] == "distribution_limits")
        candidate = next(paragraph for paragraph in draft["paragraphs"] if paragraph["role"] == "candidate_metric")

        self.assertEqual(draft["schema"], "scientometric_conclusion")
        self.assertIn("distribution_limits", roles)
        self.assertIn("index_limitations", roles)
        self.assertIn("candidate_metric", roles)
        self.assertEqual(distribution["evidence_finding_ids"], ["heavy_tail:c"])
        self.assertEqual(distribution["evidence_metrics"], ["c"])
        self.assertEqual(candidate["evidence_finding_ids"], ["balanced_candidate:islv"])
        self.assertIn("Цитирования", distribution["text"])
        self.assertIn("базовый индекс Индекс Хирша", text)
        self.assertNotIn("лучший индекс", text.lower())
        self.assertIn("не заменяют экспертную оценку", " ".join(draft["limitations"]).lower())

    def test_scientometric_conclusion_markdown_contains_traceable_evidence(self) -> None:
        payload = {
            "conclusion_draft": {
                "title": "Вывод по сравнению наукометрических индексов",
                "paragraphs": [
                    {
                        "role": "distribution_limits",
                        "text": "Метрика C имеет тяжелый хвост.",
                        "evidence_finding_ids": ["heavy_tail:c"],
                        "evidence_metrics": ["c"],
                    },
                    {
                        "role": "candidate_metric",
                        "text": "Сбалансированная рейтинговая формула рассматривается как кандидатная.",
                        "evidence_finding_ids": ["balanced_candidate:islv"],
                        "evidence_metrics": ["islv"],
                    },
                ],
                "limitations": ["Метрики не заменяют экспертную оценку."],
            }
        }

        markdown = scientometrics.scientometric_conclusion_markdown(payload)

        self.assertIn("# Вывод по сравнению наукометрических индексов", markdown)
        self.assertIn("## Распределения", markdown)
        self.assertIn("## Кандидатная формула", markdown)
        self.assertIn("Основания: heavy_tail:c", markdown)
        self.assertIn("Метрики: Цитирования", markdown)
        self.assertIn("Метрики: Процентильная формула: сбалансированный вклад", markdown)
        self.assertIn("## Ограничения вывода", markdown)
        self.assertIn("- Метрики не заменяют экспертную оценку.", markdown)

    def test_conclusion_draft_traces_rank_and_correction_evidence(self) -> None:
        findings = [
            {
                "id": "top1_dominance:islv",
                "type": "top1_dominance_dependence",
                "metric": "islv",
                "severity": "medium",
                "evidence": {"direction": "negative"},
                "text": "",
                "recommendation": "",
            },
            {
                "id": "rank_instability:h:islv",
                "type": "rank_instability",
                "metric": "islv",
                "baseline_metric": "h",
                "severity": "medium",
                "evidence": {},
                "text": "",
                "recommendation": "",
            },
        ]
        summary = scientometrics.finding_summary(findings, metrics=["h", "islv"], baseline_metric="h")

        draft = scientometrics.conclusion_draft(
            findings=findings,
            finding_summary=summary,
            metrics=["h", "islv"],
            baseline_metric="h",
            n_authors=25,
            scope={"fraction_mode": "integer"},
        )
        by_role = {paragraph["role"]: paragraph for paragraph in draft["paragraphs"]}

        self.assertIn("correction_effects", by_role)
        self.assertEqual(by_role["correction_effects"]["evidence_finding_ids"], ["top1_dominance:islv"])
        self.assertEqual(by_role["rank_comparison"]["evidence_finding_ids"], ["rank_instability:h:islv"])

    def test_conclusion_draft_for_empty_findings_keeps_scope_and_limitations(self) -> None:
        draft = scientometrics.conclusion_draft(
            findings=[],
            finding_summary=scientometrics.finding_summary([], metrics=["h"], baseline_metric="h"),
            metrics=["h"],
            baseline_metric="h",
            n_authors=0,
            scope={"fraction_mode": "integer"},
        )

        self.assertEqual([paragraph["role"] for paragraph in draft["paragraphs"]], ["scope", "no_data", "final_caution"])
        self.assertTrue(draft["limitations"])

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
            patch.object(scientometrics.warehouse, "filtered_indices", side_effect=fake_filtered),
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
        self.assertEqual(payload["scope"]["analysis_author_scope"], "cohort_resolved_author_set")
        self.assertEqual(payload["scope"]["data_scope"], "full_filtered_slice")
        self.assertIn("filters_hash", payload["scope"])
        self.assertEqual(payload["scope"]["final_analysis"]["allowed"], False)
        self.assertEqual(payload["scope"]["rank_top_n"], 10)
        self.assertEqual(payload["cohort_context"]["analysis_filters"], {"country_code": "DE"})

    def test_empty_analysis_returns_warning_without_crashing(self) -> None:
        with patch.object(scientometrics.warehouse, "filtered_indices", return_value=[]):
            payload = scientometrics.build_scientometric_analysis(
                fraction_mode="integer",
                metrics=["h", "g"],
                baseline_metric="h",
                run_id="run_empty",
            )

        self.assertEqual(payload["n_authors"], 0)
        self.assertEqual(payload["schema"], "scientometric_analysis")
        self.assertEqual(payload["descriptive"]["h"]["n"], 0)
        self.assertEqual(payload["finding_summary"]["schema"], "scientometric_findings")
        self.assertEqual(payload["conclusion_draft"]["schema"], "scientometric_conclusion")
        self.assertEqual(payload["finding_thresholds"]["tie_rate"], 0.30)
        self.assertTrue(payload["warnings"])
        self.assertIsNone(payload["interpretation"]["candidate_balanced_metric"])
        self.assertNotIn("best_balanced_metric", payload["interpretation"])

    def test_scientometric_analysis_reuses_exact_scoped_cache(self) -> None:
        rows = [
            {"author_id": "A1", "author_display_name": "One", "h": 3, "p": 4, "c": 20, "c_frac": 10, "g": 5},
            {"author_id": "A2", "author_display_name": "Two", "h": 2, "p": 2, "c": 10, "c_frac": 5, "g": 3},
            {"author_id": "A3", "author_display_name": "Three", "h": 1, "p": 1, "c": 2, "c_frac": 1, "g": 1},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            indices = root / "runs" / "run_a" / "tables" / "indices.csv"
            indices.parent.mkdir(parents=True)
            indices.write_text("author_id,h\nA1,3\n", encoding="utf-8")
            with (
                patch.object(scientometrics, "DATA", root),
                patch.object(scientometrics.warehouse, "resolve_analysis_scope", return_value={"run_id": "run_a", "dump_id": "dump_a"}),
                patch.object(scientometrics.warehouse, "resolve_scoped_table_path", return_value=indices),
                patch.object(scientometrics.warehouse, "selected_index_rows", return_value=rows) as selected,
            ):
                first = scientometrics.build_scientometric_analysis(
                    fraction_mode="integer",
                    metrics=["h", "p"],
                    baseline_metric="h",
                    run_id="run_a",
                    data_limit=0,
                )
                second = scientometrics.build_scientometric_analysis(
                    fraction_mode="integer",
                    metrics=["h", "p"],
                    baseline_metric="h",
                    run_id="run_a",
                    data_limit=0,
                )

        self.assertEqual(first["n_authors"], 3)
        self.assertEqual(second["n_authors"], 3)
        self.assertEqual(selected.call_count, 1)

    def test_scientometric_analysis_cache_prunes_old_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            for index in range(30):
                path = cache_dir / f"scientometrics_{index:02d}.json"
                path.write_text("{}\n", encoding="utf-8")
                os.utime(path, (index, index))
            target = cache_dir / "scientometrics_new.json"
            scientometrics._write_analysis_cache(target, {"schema": scientometrics.SCIENTOMETRIC_ANALYSIS_SCHEMA})

            files = sorted(path.name for path in cache_dir.glob("scientometrics_*.json"))

        self.assertIn("scientometrics_new.json", files)
        self.assertLessEqual(len(files), scientometrics.ANALYSIS_CACHE_KEEP)
        self.assertNotIn("scientometrics_00.json", files)


if __name__ == "__main__":
    unittest.main()
