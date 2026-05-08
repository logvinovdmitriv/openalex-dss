from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
from statistics import NormalDist
from pathlib import Path
from typing import Any

from app.core.paths import DATA
from app.services import cohorts, custom_metrics, warehouse
from app.services.analysis_filters import clean_analysis_filters


DEFAULT_SCIENTOMETRIC_METRICS = (
    "p",
    "c",
    "c_frac",
    "h",
    "i10",
    "g",
    "m_local",
    "top1_share",
    "iupv",
    "islv",
    "lrdi",
)
SCIENTOMETRIC_ANALYSIS_SCHEMA = "scientometric_analysis"
SCIENTOMETRIC_FINDINGS_SCHEMA = "scientometric_findings"
SCIENTOMETRIC_CONCLUSION_SCHEMA = "scientometric_conclusion"
FINDING_THRESHOLDS = {
    "heavy_tail_skewness_medium": 1.0,
    "heavy_tail_skewness_high": 2.0,
    "heavy_tail_kurtosis_medium": 3.0,
    "heavy_tail_kurtosis_high": 10.0,
    "normality_p_medium": 0.05,
    "normality_p_high": 0.01,
    "zero_rate": 0.30,
    "tie_rate": 0.30,
    "publication_dependence": 0.70,
    "citation_dependence": 0.80,
    "top1_dependence": 0.50,
    "rank_instability_share": 0.20,
    "rank_instability_jaccard": 0.50,
    "rank_agreement_spearman": 0.90,
    "rank_agreement_jaccard": 0.70,
}
DEFAULT_OVERLAP_CUTS = (10, 20, 50)
KENDALL_MAX_EXACT_N = 1000
ANALYSIS_CACHE_KEEP = 24
SCORECARD_FACTORS = {
    "publication_volume_dependence": "p",
    "citation_volume_dependence": "c",
    "fractional_citation_dependence": "c_frac",
    "top1_dominance_dependence": "top1_share",
    "collaboration_size_dependence": "mean_authors_per_work",
}
_NORMAL = NormalDist()


def build_scientometric_analysis(
    *,
    fraction_mode: str,
    metrics: list[str] | tuple[str, ...] | None = None,
    baseline_metric: str = "h",
    filters: dict[str, Any] | None = None,
    run_id: str = "",
    dump_id: str = "",
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
    top_n: int = 100,
    data_filters: dict[str, Any] | None = None,
    data_search: str = "",
    author_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = 0,
    custom_metric_defs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    cache_path = _analysis_cache_path(
        fraction_mode=fraction_mode,
        metrics=metrics,
        baseline_metric=baseline_metric,
        filters=filters,
        run_id=run_id,
        dump_id=dump_id,
        cohort_id=cohort_id,
        cohort_filter_policy=cohort_filter_policy,
        top_n=top_n,
        data_filters=data_filters,
        data_search=data_search,
        author_ids=author_ids,
        data_sort=data_sort,
        data_direction=data_direction,
        data_limit=data_limit,
        custom_metric_defs=custom_metric_defs,
    )
    if cache_path:
        cached = _read_analysis_cache(cache_path)
        if cached:
            return cached

    context = _analysis_context(
        fraction_mode=fraction_mode,
        metrics=metrics,
        baseline_metric=baseline_metric,
        filters=filters,
        run_id=run_id,
        dump_id=dump_id,
        cohort_id=cohort_id,
        cohort_filter_policy=cohort_filter_policy,
        top_n=top_n,
        data_filters=data_filters,
        data_search=data_search,
        author_ids=author_ids,
        data_sort=data_sort,
        data_direction=data_direction,
        data_limit=data_limit,
        custom_metric_defs=custom_metric_defs,
    )
    selected_metrics = context["metrics"]
    baseline_metric = context["baseline_metric"]
    run_id = context["run_id"]
    dump_id = context["dump_id"]
    fraction_mode = context["fraction_mode"]
    resolved_filters = context["filters"]
    cohort_context = context["cohort_context"]
    cohort_filter_policy = context["cohort_filter_policy"]
    rank_top_n = context["rank_top_n"]
    rows = context["rows"]

    vector_metrics = _unique_preserve_order([*selected_metrics, *SCORECARD_FACTORS.values()])
    value_vectors = _metric_value_vectors(rows, vector_metrics)
    rank_vectors = _rank_vectors({metric: value_vectors.get(metric, []) for metric in vector_metrics})
    descriptive = _describe_metrics_from_vectors(len(rows), selected_metrics, value_vectors)
    boxplots = _boxplot_metrics_from_vectors(rows, selected_metrics, value_vectors)
    histograms = _histogram_metrics_from_vectors(selected_metrics, value_vectors)
    normality = _normality_metrics_from_vectors(selected_metrics, value_vectors)
    correlations = correlation_matrices(rows, selected_metrics, value_vectors=value_vectors, rank_vectors=rank_vectors)
    rank_comparison_payload = rank_comparisons(
        rows,
        selected_metrics,
        baseline_metric=baseline_metric,
        rank_top_n=min(rank_top_n, len(rows) or rank_top_n),
        value_vectors=value_vectors,
    )
    scorecard = metric_scorecard(rows, selected_metrics, descriptive=descriptive, value_vectors=value_vectors, rank_vectors=rank_vectors)
    warnings = _analysis_warnings(
        rows,
        selected_metrics,
        cohort_filter_policy=cohort_filter_policy,
        rank_top_n=rank_top_n,
        descriptive=descriptive,
        boxplots=boxplots,
        correlations=correlations,
        custom_metric_catalog=context["custom_metrics"],
    )
    findings = interpretation_findings(
        metrics=selected_metrics,
        baseline_metric=baseline_metric,
        rank_top_n=rank_top_n,
        n_authors=len(rows),
        descriptive=descriptive,
        normality=normality,
        correlations=correlations,
        rank_comparisons=rank_comparison_payload["comparisons"],
        metric_scorecard=scorecard,
    )
    summary = finding_summary(findings, metrics=selected_metrics, baseline_metric=baseline_metric)
    analysis_scope = {
        "run_id": run_id,
        "dump_id": dump_id,
        "fraction_mode": fraction_mode,
        "filters": resolved_filters,
        "data_filters": context["data_filters"],
        "data_search": context["data_search"],
        "selected_author_ids": sorted(context["explicit_author_ids"]) if context.get("explicit_author_ids") else [],
        "data_sort": context["data_sort"],
        "data_direction": context["data_direction"],
        "data_limit": context["data_limit"],
        "cohort_id": cohort_id,
        "cohort_filter_policy": cohort_filter_policy,
        "baseline_metric": baseline_metric,
        "analysis_author_scope": "data_page_selection",
        "rank_top_n": rank_top_n,
        "n_authors": len(rows),
        "metric_scope": "filtered_recomputed",
        "percentile_scope": "current filtered author set",
        "custom_metrics": context["custom_metrics"],
    }
    conclusion = conclusion_draft(
        findings=findings,
        finding_summary=summary,
        metrics=selected_metrics,
        baseline_metric=baseline_metric,
        n_authors=len(rows),
        scope=analysis_scope,
    )

    payload = {
        "schema": SCIENTOMETRIC_ANALYSIS_SCHEMA,
        "scope": analysis_scope,
        "cohort_context": cohort_context,
        "metrics": selected_metrics,
        "custom_metrics": context["custom_metrics"],
        "n_authors": len(rows),
        "descriptive": descriptive,
        "boxplots": boxplots,
        "histograms": histograms,
        "normality": normality,
        "correlations": correlations,
        "rank_top_n": rank_top_n,
        "rank_comparisons": rank_comparison_payload["comparisons"],
        "top_overlap": rank_comparison_payload["top_overlap"],
        "outliers": _outlier_table(boxplots),
        "metric_scorecard": scorecard,
        "interpretation": _interpretation(rows, selected_metrics, baseline_metric, scorecard, warnings),
        "findings": findings,
        "finding_summary": summary,
        "finding_thresholds": FINDING_THRESHOLDS,
        "conclusion_draft": conclusion,
        "warnings": warnings,
    }
    if cache_path:
        _write_analysis_cache(cache_path, payload)
    return payload


def _analysis_cache_path(
    *,
    fraction_mode: str,
    metrics: list[str] | tuple[str, ...] | None,
    baseline_metric: str,
    filters: dict[str, Any] | None,
    run_id: str,
    dump_id: str,
    cohort_id: str,
    cohort_filter_policy: str,
    top_n: int,
    data_filters: dict[str, Any] | None,
    data_search: str,
    author_ids: list[str] | set[str] | tuple[str, ...] | None,
    data_sort: str,
    data_direction: str,
    data_limit: int,
    custom_metric_defs: list[dict[str, str]] | None,
) -> Path | None:
    if str(cohort_id or "").strip():
        return None
    try:
        selected_metrics = _select_metrics(metrics, custom_metric_defs)
        baseline_metric = str(baseline_metric or "h").strip() or "h"
        if baseline_metric not in selected_metrics:
            selected_metrics = [baseline_metric, *selected_metrics]
        scope = warehouse.resolve_analysis_scope(run_id=run_id, dump_id=dump_id)
        scoped_run_id = scope["run_id"]
        scoped_dump_id = scope["dump_id"]
        indices_path = warehouse.resolve_scoped_table_path("indices", run_id=scoped_run_id, dump_id=scoped_dump_id)
        if not indices_path or not indices_path.is_file() or not scoped_run_id:
            return None
        stat = indices_path.stat()
        data_direction = "asc" if str(data_direction or "").strip().lower() == "asc" else "desc"
        data_limit_value = max(0, min(_int_value(data_limit, 0), 500_000))
        data_sort_value = str(data_sort or "").strip() if data_limit_value > 0 else ""
        data_direction_value = data_direction if data_sort_value else "desc"
        key_payload = {
            "schema": SCIENTOMETRIC_ANALYSIS_SCHEMA,
            "run_id": scoped_run_id,
            "dump_id": scoped_dump_id,
            "fraction_mode": str(fraction_mode or "strict_authors_count"),
            "metrics": selected_metrics,
            "baseline_metric": baseline_metric,
            "filters": clean_analysis_filters(filters or {}),
            "top_n": max(0, min(_int_value(top_n, 100), 500_000)),
            "data_filters": warehouse.parse_column_filters(data_filters),
            "data_search": str(data_search or "").strip(),
            "author_ids": sorted(_clean_author_ids(author_ids) or []),
            "data_sort": data_sort_value,
            "data_direction": data_direction_value,
            "data_limit": data_limit_value,
            "custom_metric_defs": custom_metric_defs or [],
            "cohort_filter_policy": str(cohort_filter_policy or "membership"),
            "indices": {
                "path": str(indices_path),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            },
        }
        digest = hashlib.sha256(json.dumps(key_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:32]
        return DATA / "runs" / _safe_segment(scoped_run_id) / "analytics" / f"scientometrics_{digest}.json"
    except Exception:
        return None


def _safe_segment(value: str) -> str:
    cleaned = "".join(ch for ch in str(value or "") if ch.isalnum() or ch in {"_", "-"})
    return cleaned or "run"


def _read_analysis_cache(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict) and payload.get("schema") == SCIENTOMETRIC_ANALYSIS_SCHEMA:
        return payload
    return None


def _write_analysis_cache(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        _prune_analysis_cache(path.parent)
    except OSError:
        return


def _prune_analysis_cache(cache_dir: Path, keep: int = ANALYSIS_CACHE_KEEP) -> None:
    if keep <= 0:
        return
    try:
        files = [path for path in cache_dir.glob("scientometrics_*.json") if path.is_file()]
        files.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    except OSError:
        return
    for stale in files[keep:]:
        try:
            stale.unlink()
        except OSError:
            continue


def describe_metrics(rows: list[dict[str, Any]], metrics: list[str] | tuple[str, ...]) -> dict[str, Any]:
    return _describe_metrics_from_vectors(len(rows), metrics, _metric_value_vectors(rows, metrics))


def _describe_metrics_from_vectors(
    n_total: int,
    metrics: list[str] | tuple[str, ...],
    value_vectors: dict[str, list[float | None]],
) -> dict[str, Any]:
    return {
        metric: _describe_values([value for value in value_vectors.get(metric, []) if value is not None], n_total)
        for metric in metrics
    }


def boxplot_metrics(rows: list[dict[str, Any]], metrics: list[str] | tuple[str, ...]) -> dict[str, Any]:
    return _boxplot_metrics_from_vectors(rows, metrics, _metric_value_vectors(rows, metrics))


def _boxplot_metrics_from_vectors(
    rows: list[dict[str, Any]],
    metrics: list[str] | tuple[str, ...],
    value_vectors: dict[str, list[float | None]],
) -> dict[str, Any]:
    return {metric: _boxplot_values(rows, value_vectors.get(metric, [])) for metric in metrics}


def histogram_metrics(rows: list[dict[str, Any]], metrics: list[str] | tuple[str, ...], *, bins: int = 12) -> dict[str, Any]:
    return _histogram_metrics_from_vectors(metrics, _metric_value_vectors(rows, metrics), bins=bins)


def _histogram_metrics_from_vectors(
    metrics: list[str] | tuple[str, ...],
    value_vectors: dict[str, list[float | None]],
    *,
    bins: int = 12,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for metric in metrics:
        values = [value for value in value_vectors.get(metric, []) if value is not None]
        payload[metric] = {
            "raw": _histogram(values, bins=bins),
            "log1p": _histogram([math.log1p(max(0.0, value)) for value in values], bins=bins),
        }
    return payload


def normality_metrics(rows: list[dict[str, Any]], metrics: list[str] | tuple[str, ...]) -> dict[str, Any]:
    return _normality_metrics_from_vectors(metrics, _metric_value_vectors(rows, metrics))


def _normality_metrics_from_vectors(
    metrics: list[str] | tuple[str, ...],
    value_vectors: dict[str, list[float | None]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for metric in metrics:
        values = [value for value in value_vectors.get(metric, []) if value is not None]
        log_values = [math.log1p(max(0.0, value)) for value in values]
        payload[metric] = {
            "raw": _normality_for_values(values),
            "log1p": _normality_for_values(log_values),
        }
    return payload


def correlation_matrices(
    rows: list[dict[str, Any]],
    metrics: list[str] | tuple[str, ...],
    *,
    value_vectors: dict[str, list[float | None]] | None = None,
    rank_vectors: dict[str, list[float | None]] | None = None,
) -> dict[str, Any]:
    selected = list(metrics)
    if value_vectors is None or any(metric not in value_vectors for metric in selected):
        value_vectors = _metric_value_vectors(rows, selected)
    log_vectors = {
        metric: [math.log1p(max(0.0, value)) if value is not None else None for value in values]
        for metric, values in value_vectors.items()
        if metric in selected
    }
    if rank_vectors is None or any(metric not in rank_vectors for metric in selected):
        rank_vectors = _rank_vectors({metric: value_vectors.get(metric, []) for metric in selected})
    return {
        "pearson_log1p": _correlation_matrix_from_vectors(selected, log_vectors),
        "spearman": _correlation_matrix_from_vectors(selected, rank_vectors),
        "kendall_tau_b": _kendall_tau_b_matrix_from_vectors(selected, value_vectors),
    }


def rank_comparisons(
    rows: list[dict[str, Any]],
    metrics: list[str] | tuple[str, ...],
    *,
    baseline_metric: str = "h",
    rank_top_n: int = 100,
    top_n: int | None = None,
    value_vectors: dict[str, list[float | None]] | None = None,
) -> dict[str, Any]:
    if top_n is not None:
        rank_top_n = top_n
    selected = list(metrics)
    author_ids = _row_author_ids(rows)
    if value_vectors is None or any(metric not in value_vectors for metric in selected):
        ranks = {metric: _competition_ranks(rows, metric) for metric in selected}
    else:
        ranks = {metric: _competition_ranks_from_vectors(author_ids, value_vectors.get(metric, [])) for metric in selected}
    overlap_cuts = _overlap_cuts(rank_top_n)
    top_limit = max([rank_top_n, *overlap_cuts], default=rank_top_n)
    ordered_authors = {
        metric: _ordered_top_authors(metric_ranks, top_limit)
        for metric, metric_ranks in ranks.items()
    }
    top_overlap = _top_overlap_matrix_from_ordered(ordered_authors, overlap_cuts)
    author_names = {
        str(row.get("author_id") or ""): str(row.get("author_display_name") or row.get("display_name") or "")
        for row in rows
        if str(row.get("author_id") or "").strip()
    }
    comparisons: dict[str, Any] = {}
    baseline_ranks = ranks.get(baseline_metric, {})
    top_base = set((ordered_authors.get(baseline_metric) or [])[:rank_top_n])
    for metric in selected:
        if metric == baseline_metric:
            continue
        metric_ranks = ranks.get(metric, {})
        common_author_ids = set(baseline_ranks) & set(metric_ranks)
        abs_values: list[float] = []
        largest_shifts_heap: list[tuple[int, str, int, dict[str, Any]]] = []
        for candidate_index, author_id in enumerate(common_author_ids):
            rank_delta = metric_ranks[author_id] - baseline_ranks[author_id]
            abs_delta = abs(rank_delta)
            abs_values.append(float(abs_delta))
            candidate = {
                "baseline_metric": baseline_metric,
                "compare_metric": metric,
                "author_id": author_id,
                "author_display_name": author_names.get(author_id, ""),
                "baseline_rank": baseline_ranks[author_id],
                "metric_rank": metric_ranks[author_id],
                "rank_delta": rank_delta,
                "abs_rank_delta": abs_delta,
            }
            heap_item = (int(abs_delta), str(author_id), candidate_index, candidate)
            if len(largest_shifts_heap) < 20:
                heapq.heappush(largest_shifts_heap, heap_item)
            elif heap_item[:2] > largest_shifts_heap[0][:2]:
                heapq.heapreplace(largest_shifts_heap, heap_item)
        top_metric = set((ordered_authors.get(metric) or [])[:rank_top_n])
        top_overlap_exact = len(top_base & top_metric)
        jaccard_exact = _jaccard(top_base, top_metric)
        ordered_abs_values = sorted(abs_values)
        comparisons[metric] = {
            "baseline_metric": baseline_metric,
            "metric": metric,
            "n_common_authors": len(common_author_ids),
            "median_abs_delta": _quantile_sorted(ordered_abs_values, 0.5) if ordered_abs_values else None,
            "p90_abs_delta": _quantile_sorted(ordered_abs_values, 0.9) if ordered_abs_values else None,
            "max_abs_delta": max(abs_values) if abs_values else None,
            "share_abs_delta_le_5": _share(abs_values, lambda value: value <= 5.0),
            "top_overlap_exact": top_overlap_exact,
            "top_overlap": top_overlap_exact,
            "jaccard_top_n_exact": jaccard_exact,
            "jaccard_top_n": jaccard_exact,
            "largest_shifts": sorted((item[3] for item in largest_shifts_heap), key=lambda item: (-int(item["abs_rank_delta"]), str(item["author_id"]))),
        }
    return {"comparisons": comparisons, "top_overlap": top_overlap}


def _ordered_top_authors(metric_ranks: dict[str, int], limit: int) -> list[str]:
    if limit <= 0 or not metric_ranks:
        return []
    key = lambda item: (item[1], item[0])
    if limit >= len(metric_ranks):
        return [author_id for author_id, _ in sorted(metric_ranks.items(), key=key)]
    return [author_id for author_id, _ in heapq.nsmallest(limit, metric_ranks.items(), key=key)]


def build_outlier_export_rows(
    *,
    fraction_mode: str,
    metrics: list[str] | tuple[str, ...] | None = None,
    baseline_metric: str = "h",
    filters: dict[str, Any] | None = None,
    run_id: str = "",
    dump_id: str = "",
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
    top_n: int = 100,
    data_filters: dict[str, Any] | None = None,
    data_search: str = "",
    author_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = 0,
    custom_metric_defs: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    context = _analysis_context(
        fraction_mode=fraction_mode,
        metrics=metrics,
        baseline_metric=baseline_metric,
        filters=filters,
        run_id=run_id,
        dump_id=dump_id,
        cohort_id=cohort_id,
        cohort_filter_policy=cohort_filter_policy,
        top_n=top_n,
        data_filters=data_filters,
        data_search=data_search,
        author_ids=author_ids,
        data_sort=data_sort,
        data_direction=data_direction,
        data_limit=data_limit,
        custom_metric_defs=custom_metric_defs,
    )
    return outlier_rows(context["rows"], context["metrics"])


def outlier_rows(rows: list[dict[str, Any]], metrics: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for metric in metrics:
        payload.extend(_metric_outlier_rows(rows, metric))
    return sorted(payload, key=lambda item: (str(item["metric"]), -float(item["value"]), str(item["author_id"])))


def metric_scorecard(
    rows: list[dict[str, Any]],
    metrics: list[str] | tuple[str, ...],
    *,
    descriptive: dict[str, Any] | None = None,
    value_vectors: dict[str, list[float | None]] | None = None,
    rank_vectors: dict[str, list[float | None]] | None = None,
) -> dict[str, Any]:
    descriptive = descriptive or describe_metrics(rows, metrics)
    factors = SCORECARD_FACTORS
    vector_metrics = _unique_preserve_order([*metrics, *factors.values()])
    if value_vectors is None or any(metric not in value_vectors for metric in vector_metrics):
        value_vectors = _metric_value_vectors(rows, vector_metrics)
    if rank_vectors is None or any(metric not in rank_vectors for metric in vector_metrics):
        rank_vectors = _rank_vectors({metric: value_vectors.get(metric, []) for metric in vector_metrics})
    payload: dict[str, Any] = {}
    for metric in metrics:
        metric_payload = {
            label: _dependence_payload(_pearson_paired_vectors(rank_vectors.get(metric, []), rank_vectors.get(factor, [])))
            for label, factor in factors.items()
            if metric != factor
        }
        summary = descriptive.get(metric) or {}
        metric_payload.update(
            {
                "tie_rate": summary.get("tie_rate"),
                "zero_rate": summary.get("zero_rate"),
                "outlier_share_iqr": summary.get("outlier_share_iqr"),
                "coefficient_of_variation": summary.get("coefficient_of_variation"),
            }
        )
        payload[metric] = metric_payload
    return payload


def interpretation_findings(
    *,
    metrics: list[str],
    baseline_metric: str,
    n_authors: int,
    descriptive: dict[str, Any],
    normality: dict[str, Any],
    correlations: dict[str, Any],
    rank_comparisons: dict[str, Any],
    metric_scorecard: dict[str, Any],
    rank_top_n: int = 100,
) -> list[dict[str, Any]]:
    if n_authors <= 0:
        return []
    findings: list[dict[str, Any]] = []
    findings.extend(_distribution_findings(metrics, descriptive, normality))
    findings.extend(_scorecard_findings(metrics, metric_scorecard))
    findings.extend(_metric_identity_findings(metrics))
    findings.extend(_rank_findings(metrics, baseline_metric, n_authors, correlations, rank_comparisons, rank_top_n=rank_top_n))
    findings.extend(_candidate_metric_findings(metrics, metric_scorecard, n_authors=n_authors))
    return sorted(findings, key=_finding_sort_key)


def finding_summary(findings: list[dict[str, Any]], *, metrics: list[str], baseline_metric: str) -> dict[str, Any]:
    has_candidate = any(finding.get("type") == "balanced_candidate_metric" for finding in findings)
    limitations = [
        {
            "id": finding.get("id"),
            "type": finding.get("type"),
            "metric": finding.get("metric"),
            "baseline_metric": finding.get("baseline_metric"),
            "severity": finding.get("severity"),
        }
        for finding in findings
        if finding.get("severity") in {"high", "medium"} and finding.get("type") != "balanced_candidate_metric"
    ][:8]
    discussion_points = []
    if any(finding.get("type") == "heavy_tail_distribution" for finding in findings):
        discussion_points.append("Обсудить тяжелые хвосты распределений и использовать ранговые/логарифмические сравнения.")
    if any(finding.get("type") == "high_tie_rate" for finding in findings):
        discussion_points.append("Отдельно указать индексы с высокой долей совпадающих значений.")
    if any(finding.get("type") == "top1_dominance_dependence" for finding in findings):
        discussion_points.append("Проверить влияние одной сверхцитируемой работы через долю цитирований самой цитируемой работы.")
    if any(finding.get("type") == "rank_instability" for finding in findings):
        discussion_points.append(f"Разобрать крупнейшие сдвиги рангов относительно {_metric_label(baseline_metric)}.")
    if has_candidate:
        discussion_points.append("Описывать сбалансированный индекс локального вклада как дополнительный исследовательский показатель, а не как автоматически лучший индекс.")
    return {
        "schema": SCIENTOMETRIC_FINDINGS_SCHEMA,
        "n_findings": len(findings),
        "high_count": sum(1 for finding in findings if finding.get("severity") == "high"),
        "medium_count": sum(1 for finding in findings if finding.get("severity") == "medium"),
        "candidate_metric": "islv" if has_candidate else None,
        "candidate_metric_claim": "balanced_candidate_not_proven_best" if has_candidate else None,
        "primary_limitations": limitations,
        "recommended_discussion_points": discussion_points,
        "notes": [
            "Findings are descriptive and scoped to the resolved local author set.",
            "Findings do not replace expert research assessment.",
        ],
    }


def conclusion_draft(
    *,
    findings: list[dict[str, Any]],
    finding_summary: dict[str, Any],
    metrics: list[str],
    baseline_metric: str,
    n_authors: int,
    scope: dict[str, Any],
) -> dict[str, Any]:
    baseline_label = _metric_label(baseline_metric)
    paragraphs: list[dict[str, Any]] = [
        {
            "role": "scope",
            "text": (
                f"Анализ выполнен для локально зафиксированной области анализа: {n_authors} авторов, "
                f"режим дробления {scope.get('fraction_mode') or 'не указан'}, базовый индекс {baseline_label}. "
                "Все показатели являются локальными и рассчитаны по выбранному срезу, а не по глобальному профилю автора."
            ),
            "evidence_finding_ids": [],
            "evidence_metrics": [],
        }
    ]
    if n_authors <= 0:
        paragraphs.append(
            {
                "role": "no_data",
                "text": "В текущей области анализа нет авторов; содержательные статистические выводы не формируются.",
                "evidence_finding_ids": [],
                "evidence_metrics": [],
            }
        )

    heavy_tail_metrics = _finding_metrics(findings, "heavy_tail_distribution")
    if heavy_tail_metrics:
        paragraphs.append(
            {
                "role": "distribution_limits",
                "text": (
                    f"В выборке выявлены тяжелохвостые или асимметричные распределения по метрикам {_metric_list_text(heavy_tail_metrics)}. "
                    "Это ограничивает интерпретацию средних значений и прямого ранжирования; для сравнения предпочтительны ранговые показатели и графики распределения."
                ),
                "evidence_finding_ids": _finding_ids(findings, "heavy_tail_distribution"),
                "evidence_metrics": heavy_tail_metrics,
            }
        )

    weak_differentiation = _unique_preserve_order(
        [*_finding_metrics(findings, "high_tie_rate"), *_finding_metrics(findings, "zero_inflation")]
    )
    if weak_differentiation:
        paragraphs.append(
            {
                "role": "index_limitations",
                "text": (
                    f"Для метрик {_metric_list_text(weak_differentiation)} обнаружена высокая доля одинаковых или нулевых значений. "
                    "Такие показатели полезны как простые и устойчивые индикаторы, но хуже различают авторов внутри близких групп."
                ),
                "evidence_finding_ids": [
                    *_finding_ids(findings, "high_tie_rate"),
                    *_finding_ids(findings, "zero_inflation"),
                ],
                "evidence_metrics": weak_differentiation,
            }
        )

    positive_top1 = [
        finding
        for finding in findings
        if finding.get("type") == "top1_dominance_dependence"
        and str((finding.get("evidence") or {}).get("direction") or "").strip().lower() != "negative"
    ]
    negative_top1 = [
        finding
        for finding in findings
        if finding.get("type") == "top1_dominance_dependence"
        and str((finding.get("evidence") or {}).get("direction") or "").strip().lower() == "negative"
    ]
    dependence_metrics = _unique_preserve_order(
        [
            *_finding_metrics(findings, "publication_volume_dependence"),
            *_finding_metrics(findings, "citation_volume_dependence"),
            *[str(finding.get("metric") or "") for finding in positive_top1],
        ]
    )
    if dependence_metrics:
        paragraphs.append(
            {
                "role": "dependence_limits",
                "text": (
                    f"Для метрик {_metric_list_text(dependence_metrics)} выявлена существенная связь с числом публикаций, общим цитированием или концентрацией цитирований в одной работе. "
                    "Это показывает, что отдельный индекс не должен использоваться как единственный критерий сравнения."
                ),
                "evidence_finding_ids": [
                    *_finding_ids(findings, "publication_volume_dependence"),
                    *_finding_ids(findings, "citation_volume_dependence"),
                    *[str(finding.get("id") or "") for finding in positive_top1 if finding.get("id")],
                ],
                "evidence_metrics": dependence_metrics,
            }
        )

    correction_metrics = _unique_preserve_order([str(finding.get("metric") or "") for finding in negative_top1])
    if correction_metrics:
        paragraphs.append(
            {
                "role": "correction_effects",
                "text": (
                    f"Для метрик {_metric_list_text(correction_metrics)} выявлена обратная связь с долей цитирований самой цитируемой работы. "
                    "Для индексов со встроенным штрафом концентрации это может указывать на корректирующий эффект; результат следует проверять через изменения мест относительно цитирований и индекса Хирша."
                ),
                "evidence_finding_ids": [str(finding.get("id") or "") for finding in negative_top1 if finding.get("id")],
                "evidence_metrics": correction_metrics,
            }
        )

    unstable = _finding_metrics(findings, "rank_instability")
    agreement = _finding_metrics(findings, "rank_agreement")
    if unstable or agreement:
        details: list[str] = []
        if unstable:
            details.append(f"изменяют позиции относительно {baseline_label}: {_metric_list_text(unstable)}")
        if agreement:
            details.append(f"близки к {baseline_label}: {_metric_list_text(agreement)}")
        paragraphs.append(
            {
                "role": "rank_comparison",
                "text": (
                    "Ранговые сравнения показывают, какие индексы фактически дублируют базовый индекс, а какие меняют состав первых N авторов: "
                    + "; ".join(details)
                    + ". Для метрик с крупными сдвигами требуется отдельно проверить таблицы изменений мест."
                ),
                "evidence_finding_ids": [
                    *_finding_ids(findings, "rank_instability"),
                    *_finding_ids(findings, "rank_agreement"),
                ],
                "evidence_metrics": _unique_preserve_order([*unstable, *agreement]),
            }
        )

    if any(finding.get("type") == "balanced_candidate_metric" for finding in findings):
        paragraphs.append(
            {
                "role": "candidate_metric",
                "text": (
                    "Сбалансированный индекс локального вклада может рассматриваться как дополнительная исследовательская модификация, поскольку объединяет процентильные компоненты, дробное цитирование и штраф концентрации в одной сверхцитируемой работе. "
                    "Его преимущество следует формулировать только в пределах текущего среза и по указанным критериям, а не как универсальное превосходство."
                ),
                "evidence_finding_ids": _finding_ids(findings, "balanced_candidate_metric"),
                "evidence_metrics": _finding_metrics(findings, "balanced_candidate_metric"),
            }
        )

    paragraphs.append(
        {
            "role": "final_caution",
            "text": "Полученные выводы являются описательными и не заменяют экспертную оценку исследователей.",
            "evidence_finding_ids": [],
            "evidence_metrics": [],
        }
    )

    return {
        "schema": SCIENTOMETRIC_CONCLUSION_SCHEMA,
        "title": "Вывод по сравнению наукометрических индексов",
        "paragraphs": paragraphs,
        "limitations": [
            "Вывод действителен только в пределах текущего локального среза и выбранной группы авторов.",
            "Метрики не заменяют экспертную оценку.",
            "OpenAlex-метаданные могут содержать ошибки авторской дизамбигуации и неполноту.",
        ],
        "source": {
            "analysis_schema": SCIENTOMETRIC_ANALYSIS_SCHEMA,
            "findings_schema": finding_summary.get("schema"),
            "conclusion_schema": SCIENTOMETRIC_CONCLUSION_SCHEMA,
            "n_findings": finding_summary.get("n_findings", len(findings)),
            "baseline_metric": baseline_metric,
            "metrics": metrics,
        },
    }


def scientometric_conclusion_markdown(payload: dict[str, Any]) -> str:
    conclusion = payload.get("conclusion_draft") or {}
    title = str(conclusion.get("title") or "Вывод по сравнению наукометрических индексов").strip()
    lines = [f"# {title or 'Вывод по сравнению наукометрических индексов'}", ""]
    for paragraph in conclusion.get("paragraphs") or []:
        if not isinstance(paragraph, dict):
            continue
        role = str(paragraph.get("role") or "paragraph")
        text = str(paragraph.get("text") or "").strip()
        lines.extend([f"## {_conclusion_role_label(role)}", "", text or "Нет текста.", ""])
        evidence_ids = [str(item) for item in paragraph.get("evidence_finding_ids") or [] if str(item).strip()]
        evidence_metrics = [str(item) for item in paragraph.get("evidence_metrics") or [] if str(item).strip()]
        if evidence_ids:
            lines.extend([f"Основания: {', '.join(evidence_ids)}", ""])
        if evidence_metrics:
            lines.extend([f"Метрики: {', '.join(_metric_label(metric) for metric in evidence_metrics)}", ""])
    limitations = [str(item) for item in conclusion.get("limitations") or [] if str(item).strip()]
    if limitations:
        lines.extend(["## Ограничения вывода", ""])
        lines.extend([f"- {item}" for item in limitations])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _conclusion_role_label(role: str) -> str:
    labels = {
        "scope": "Область анализа",
        "distribution_limits": "Распределения",
        "index_limitations": "Различающая способность",
        "dependence_limits": "Зависимости индексов",
        "correction_effects": "Корректирующие эффекты",
        "rank_comparison": "Сравнение рангов",
        "candidate_metric": "Кандидатная формула",
        "no_data": "Нет данных",
        "final_caution": "Ограничение интерпретации",
    }
    return labels.get(role, role.replace("_", " ").strip().title() or "Абзац")


def _distribution_findings(metrics: list[str], descriptive: dict[str, Any], normality: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for metric in metrics:
        summary = descriptive.get(metric) or {}
        normality_raw = (normality.get(metric) or {}).get("raw") or {}
        skewness = _number(normality_raw.get("skewness"))
        if skewness is None:
            skewness = _number(summary.get("skewness"))
        kurtosis = _number(normality_raw.get("excess_kurtosis"))
        if kurtosis is None:
            kurtosis = _number(summary.get("excess_kurtosis"))
        p_value = _number(normality_raw.get("jarque_bera_p_approx"))
        if _is_heavy_tail(skewness, kurtosis, p_value):
            high = (
                (skewness is not None and abs(skewness) >= FINDING_THRESHOLDS["heavy_tail_skewness_high"])
                or (kurtosis is not None and kurtosis >= FINDING_THRESHOLDS["heavy_tail_kurtosis_high"])
                or (p_value is not None and p_value < FINDING_THRESHOLDS["normality_p_high"])
            )
            findings.append(
                _finding(
                    id=f"heavy_tail:{metric}",
                    type="heavy_tail_distribution",
                    metric=metric,
                    severity="high" if high else "medium",
                    evidence={
                        "skewness": skewness,
                        "excess_kurtosis": kurtosis,
                        "jarque_bera_p_approx": p_value,
                        "thresholds": {
                            "abs_skewness": FINDING_THRESHOLDS["heavy_tail_skewness_medium"],
                            "excess_kurtosis": FINDING_THRESHOLDS["heavy_tail_kurtosis_medium"],
                            "jarque_bera_p_approx": FINDING_THRESHOLDS["normality_p_medium"],
                        },
                    },
                    text=f"Метрика {metric} имеет выраженное асимметричное или тяжелохвостое распределение; raw-сравнение и средние значения чувствительны к выбросам.",
                    recommendation="Использовать ранговые сравнения, графики распределения и проверять таблицу выделяющихся значений.",
                )
            )

        zero_rate = _number(summary.get("zero_rate"))
        if zero_rate is not None and zero_rate >= FINDING_THRESHOLDS["zero_rate"]:
            findings.append(
                _finding(
                    id=f"zero_inflation:{metric}",
                    type="zero_inflation",
                    metric=metric,
                    severity="high" if zero_rate >= 0.60 else "medium",
                    evidence={"zero_rate": zero_rate, "threshold": FINDING_THRESHOLDS["zero_rate"]},
                    text=f"Метрика {metric} имеет высокую долю нулевых значений; она слабо различает нижнюю часть выборки.",
                    recommendation="Не использовать этот показатель как единственный критерий тонкого ранжирования.",
                )
            )

        tie_rate = _number(summary.get("tie_rate"))
        if tie_rate is not None and tie_rate >= FINDING_THRESHOLDS["tie_rate"]:
            findings.append(
                _finding(
                    id=f"tie_rate:{metric}",
                    type="high_tie_rate",
                    metric=metric,
                    severity="high" if tie_rate >= 0.60 else "medium",
                    evidence={"tie_rate": tie_rate, "threshold": FINDING_THRESHOLDS["tie_rate"]},
                    text=f"Метрика {metric} дает много одинаковых значений; она полезна как грубый показатель, но хуже подходит для тонкого ранжирования.",
                    recommendation="Сопоставлять с более непрерывными индексами и матрицей связи показателей.",
                )
            )
    return findings


def _scorecard_findings(metrics: list[str], metric_scorecard: dict[str, Any]) -> list[dict[str, Any]]:
    specs = [
        (
            "publication_volume_dependence",
            "publication_volume_dependence",
            FINDING_THRESHOLDS["publication_dependence"],
            0.85,
            "Индекс сильно связан с числом публикаций P; он может отражать продуктивность больше, чем цитатное влияние.",
            "Интерпретировать вместе с цитатными и дробными показателями.",
        ),
        (
            "citation_volume_dependence",
            "citation_volume_dependence",
            FINDING_THRESHOLDS["citation_dependence"],
            0.90,
            "Индекс близко следует общему цитированию; это упрощает интерпретацию влияния, но повышает чувствительность к выбросам.",
            "Проверять heavy-tail диагностику и outliers.csv.",
        ),
        (
            "top1_dominance_dependence",
            "top1_dominance_dependence",
            FINDING_THRESHOLDS["top1_dependence"],
            0.70,
            "Индекс чувствителен к концентрации цитирований в одной работе; позиция автора может быть обусловлена единичным публикационным событием.",
            "Использовать вместе с top1_share, c_frac и индексами со штрафом концентрации.",
        ),
    ]
    findings: list[dict[str, Any]] = []
    for metric in metrics:
        scorecard = metric_scorecard.get(metric) or {}
        for finding_type, dependency_key, threshold, high_threshold, text, recommendation in specs:
            dependency = scorecard.get(dependency_key) or {}
            abs_rho = _number(dependency.get("abs_spearman_rho"))
            if abs_rho is None or abs_rho < threshold:
                continue
            direction = str(dependency.get("direction") or "").strip().lower()
            finding_text = text
            finding_recommendation = recommendation
            if dependency_key == "top1_dominance_dependence" and direction == "negative":
                finding_text = "Индекс обратно связан с top1_share; это указывает на корректирующее действие штрафа концентрации, а не на завышение авторов одной сверхцитируемой работой."
                finding_recommendation = "Использовать как корректирующий показатель и проверять связь мест относительно цитирований и индекса Хирша."
            findings.append(
                _finding(
                    id=f"{finding_type}:{metric}",
                    type=finding_type,
                    metric=metric,
                    severity="high" if abs_rho >= high_threshold else "medium",
                    evidence={
                        "abs_spearman_rho": abs_rho,
                        "spearman_rho": dependency.get("spearman_rho"),
                        "direction": dependency.get("direction"),
                        "threshold": threshold,
                    },
                    text=f"Метрика {metric}: {finding_text}",
                    recommendation=finding_recommendation,
                )
            )
    return findings


def _metric_identity_findings(metrics: list[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if "p" in metrics:
        findings.append(
            _finding(
                id="metric_identity:p",
                type="productivity_metric",
                metric="p",
                severity="informational",
                evidence={"metric_role": "publication_volume", "measures_publication_count": True},
                text="P отражает публикационную продуктивность и не является самостоятельной мерой цитатного влияния.",
                recommendation="Использовать P как контекст объема публикаций, а не как единственный показатель научного влияния.",
            )
        )
    if "c" in metrics:
        findings.append(
            _finding(
                id="metric_identity:c",
                type="citation_volume_metric",
                metric="c",
                severity="informational",
                evidence={"metric_role": "citation_volume", "requires_heavy_tail_and_top1_checks": True},
                text="C отражает общий объем цитирования и легко интерпретируется, но требует проверки heavy-tail диагностики и top1_share.",
                recommendation="Сопоставлять C с C_frac, h/g и показателями концентрации цитирований.",
            )
        )
    return findings


def _finding_metrics(findings: list[dict[str, Any]], finding_type: str) -> list[str]:
    return _unique_preserve_order(
        [str(finding.get("metric") or "").strip() for finding in findings if finding.get("type") == finding_type and finding.get("metric")]
    )


def _finding_ids(findings: list[dict[str, Any]], finding_type: str) -> list[str]:
    return _unique_preserve_order(
        [str(finding.get("id") or "").strip() for finding in findings if finding.get("type") == finding_type and finding.get("id")]
    )


def _unique_preserve_order(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _metric_list_text(metrics: list[str]) -> str:
    if not metrics:
        return "нет"
    labels = [_metric_label(metric) for metric in metrics]
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} и {labels[1]}"
    return ", ".join(labels[:-1]) + f" и {labels[-1]}"


def _metric_list_text_for_catalog(metrics: list[str], custom_metric_catalog: list[dict[str, Any]] | None = None) -> str:
    if not metrics:
        return "нет"
    labels = [_metric_label_for_catalog(metric, custom_metric_catalog) for metric in metrics]
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} и {labels[1]}"
    return ", ".join(labels[:-1]) + f" и {labels[-1]}"


def _metric_label_for_catalog(metric: str, custom_metric_catalog: list[dict[str, Any]] | None = None) -> str:
    for item in custom_metric_catalog or []:
        if str(item.get("value") or item.get("id") or "") == metric:
            return str(item.get("label") or metric)
    return _metric_label(metric)


def _metric_label(metric: str) -> str:
    labels = {
        "p": "Публикации",
        "c": "Цитирования",
        "c_frac": "Цитирования с долевым учетом",
        "cpp": "Средняя цитируемость",
        "h": "Индекс Хирша",
        "i10": "Работы с 10+ цитированиями",
        "g": "Индекс g",
        "m_local": "Индекс m внутри среза",
        "top1_share": "Доля цитирований самой цитируемой работы",
        "f5": "Индекс Полянина f5",
        "fm5": "Долевой индекс Полянина fm5",
        "iupv": "Собственный интегральный индекс",
        "islv": "Собственный сбалансированный индекс",
        "lrdi": "Индекс устойчивости результата",
    }
    return labels.get(metric, metric)


def _rank_findings(
    metrics: list[str],
    baseline_metric: str,
    n_authors: int,
    correlations: dict[str, Any],
    rank_comparisons: dict[str, Any],
    *,
    rank_top_n: int,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    spearman_matrix = correlations.get("spearman") or {}
    baseline_spearman = spearman_matrix.get(baseline_metric) or {}
    instability_delta_threshold = max(5.0, FINDING_THRESHOLDS["rank_instability_share"] * float(n_authors or 0))
    for metric in metrics:
        if metric == baseline_metric:
            continue
        comparison = rank_comparisons.get(metric) or {}
        p90_abs_delta = _number(comparison.get("p90_abs_delta"))
        jaccard = _number(comparison.get("jaccard_top_n_exact"))
        if jaccard is None:
            jaccard = _number(comparison.get("jaccard_top_n"))
        spearman = _number((baseline_spearman or {}).get(metric))

        unstable = (
            (p90_abs_delta is not None and p90_abs_delta >= instability_delta_threshold)
            or (jaccard is not None and jaccard < FINDING_THRESHOLDS["rank_instability_jaccard"])
        )
        if unstable:
            high = (
                (p90_abs_delta is not None and p90_abs_delta >= max(10.0, 0.40 * float(n_authors or 0)))
                or (jaccard is not None and jaccard < 0.30)
            )
            findings.append(
                _finding(
                    id=f"rank_instability:{baseline_metric}:{metric}",
                    type="rank_instability",
                    metric=metric,
                    baseline_metric=baseline_metric,
                    severity="high" if high else "medium",
                    evidence={
                        "median_abs_delta": comparison.get("median_abs_delta"),
                        "p90_abs_delta": p90_abs_delta,
                        "jaccard_top_n_exact": jaccard,
                        "rank_top_n": rank_top_n,
                        "n_authors": n_authors,
                        "p90_threshold": instability_delta_threshold,
                    },
                    text=f"Переход от {baseline_metric} к {metric} существенно меняет позиции части авторов; индекс отражает другой аспект публикационного профиля.",
                    recommendation="Проверить матрицу связи показателей и решить, нужен ли этот индекс как отдельная перспектива ранжирования.",
                )
            )

        if (
            spearman is not None
            and spearman >= FINDING_THRESHOLDS["rank_agreement_spearman"]
            and jaccard is not None
            and jaccard >= FINDING_THRESHOLDS["rank_agreement_jaccard"]
        ):
            findings.append(
                _finding(
                    id=f"rank_agreement:{baseline_metric}:{metric}",
                    type="rank_agreement",
                    metric=metric,
                    baseline_metric=baseline_metric,
                    severity="informational",
                    evidence={
                        "spearman": spearman,
                        "jaccard_top_n_exact": jaccard,
                        "rank_top_n": rank_top_n,
                        "spearman_threshold": FINDING_THRESHOLDS["rank_agreement_spearman"],
                        "jaccard_threshold": FINDING_THRESHOLDS["rank_agreement_jaccard"],
                    },
                    text=f"Метрика {metric} дает близкое ранжирование к {baseline_metric}; ее добавление может быть менее информативным, если нужна альтернативная перспектива.",
                    recommendation="Использовать как подтверждающий, а не обязательно независимый показатель.",
                )
            )
    return findings


def _candidate_metric_findings(metrics: list[str], metric_scorecard: dict[str, Any], *, n_authors: int) -> list[dict[str, Any]]:
    if n_authors <= 0 or "islv" not in metrics:
        return []
    scorecard = metric_scorecard.get("islv") or {}
    return [
        _finding(
            id="balanced_candidate:islv",
            type="balanced_candidate_metric",
            metric="islv",
            severity="informational",
            evidence={
                "uses_percentile_components": True,
                "uses_fractional_citations": True,
                "uses_top1_penalty": True,
                "publication_dependence_abs": ((scorecard.get("publication_volume_dependence") or {}).get("abs_spearman_rho")),
                "citation_dependence_abs": ((scorecard.get("citation_volume_dependence") or {}).get("abs_spearman_rho")),
                "top1_dependence_abs": ((scorecard.get("top1_dominance_dependence") or {}).get("abs_spearman_rho")),
            },
            text="Сбалансированный индекс локального вклада рассматривается как дополнительная исследовательская модификация рейтинга внутри текущего среза, а не как автоматически доказанный лучший индекс.",
            recommendation="Обосновывать его через сводную оценку, изменения мест и сравнение с индексом Хирша, цитированиями, долевыми цитированиями и индексом g.",
        )
    ]


def _finding(
    *,
    id: str,
    type: str,
    metric: str,
    severity: str,
    evidence: dict[str, Any],
    text: str,
    recommendation: str,
    baseline_metric: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "type": type,
        "metric": metric,
        "baseline_metric": baseline_metric,
        "severity": severity,
        "evidence": evidence,
        "text": text,
        "recommendation": recommendation,
    }


def _finding_sort_key(finding: dict[str, Any]) -> tuple[int, str, str, str]:
    severity_order = {"high": 0, "medium": 1, "low": 2, "informational": 3}
    return (
        severity_order.get(str(finding.get("severity") or ""), 9),
        str(finding.get("type") or ""),
        str(finding.get("metric") or ""),
        str(finding.get("id") or ""),
    )


def _is_heavy_tail(skewness: float | None, kurtosis: float | None, p_value: float | None) -> bool:
    return (
        (skewness is not None and abs(skewness) >= FINDING_THRESHOLDS["heavy_tail_skewness_medium"])
        or (kurtosis is not None and kurtosis >= FINDING_THRESHOLDS["heavy_tail_kurtosis_medium"])
        or (p_value is not None and p_value < FINDING_THRESHOLDS["normality_p_medium"])
    )


def _analysis_context(
    *,
    fraction_mode: str,
    metrics: list[str] | tuple[str, ...] | None = None,
    baseline_metric: str = "h",
    filters: dict[str, Any] | None = None,
    run_id: str = "",
    dump_id: str = "",
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
    top_n: int = 100,
    data_filters: dict[str, Any] | None = None,
    data_search: str = "",
    author_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = 0,
    custom_metric_defs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    selected_metrics = _select_metrics(metrics, custom_metric_defs)
    baseline_metric = str(baseline_metric or "h").strip() or "h"
    if baseline_metric not in warehouse.INDEX_NUMERIC_FIELDS and baseline_metric not in {item["id"] for item in custom_metric_defs or []}:
        raise ValueError(f"Unsupported baseline_metric: {baseline_metric}")
    if baseline_metric not in selected_metrics:
        selected_metrics = [baseline_metric, *selected_metrics]

    request_filters = clean_analysis_filters(filters or {})
    scoped_author_ids = None
    cohort_context = None
    if cohort_id:
        ctx = cohorts.resolve_cohort_context(
            cohort_id,
            run_id=run_id,
            dump_id=dump_id,
            fraction_mode=fraction_mode,
            filters=request_filters,
            filter_policy=cohort_filter_policy,
        )
        run_id = str(ctx.get("run_id") or "")
        dump_id = str(ctx.get("dump_id") or "")
        fraction_mode = str(ctx.get("fraction_mode") or fraction_mode or "strict_authors_count")
        resolved_filters = clean_analysis_filters(ctx.get("filters") or {})
        scoped_author_ids = ctx.get("author_ids")
        cohort_context = cohorts.cohort_context_summary(ctx)
        cohort_filter_policy = str(ctx.get("filter_policy") or cohort_filter_policy or "membership")
    else:
        scope = warehouse.resolve_analysis_scope(run_id=run_id, dump_id=dump_id)
        run_id = scope["run_id"]
        dump_id = scope["dump_id"]
        fraction_mode = str(fraction_mode or "strict_authors_count")
        resolved_filters = request_filters

    if not (str(run_id or "").strip() or str(dump_id or "").strip()):
        raise ValueError("run_id or dump_id is required for scientometric analysis.")

    requested_rank_top_n = max(0, min(int(top_n or 0), 500_000))
    explicit_author_ids = _clean_author_ids(author_ids)
    if explicit_author_ids is not None:
        scoped_author_ids = explicit_author_ids if scoped_author_ids is None else set(scoped_author_ids).intersection(explicit_author_ids)

    parsed_data_filters = warehouse.parse_column_filters(data_filters)
    data_search = str(data_search or "").strip()
    data_limit = max(0, min(_int_value(data_limit, 0), 500_000))
    data_sort = str(data_sort or "").strip() if data_limit > 0 else ""
    data_direction = "asc" if data_sort and str(data_direction or "").strip().lower() == "asc" else "desc"
    required_row_fields = {
        "author_id",
        "author_display_name",
        baseline_metric,
        *selected_metrics,
        *SCORECARD_FACTORS.values(),
        *custom_metrics.referenced_base_fields(custom_metric_defs),
    }
    rows = warehouse.selected_index_rows(
        fraction_mode,
        resolved_filters,
        run_id=run_id,
        dump_id=dump_id,
        author_ids=scoped_author_ids,
        data_filters=parsed_data_filters,
        data_search=data_search,
        data_sort=data_sort,
        data_direction=data_direction,
        data_limit=data_limit,
        custom_metric_defs=custom_metric_defs,
        select_fields=required_row_fields,
    )
    rank_top_n = requested_rank_top_n if requested_rank_top_n > 0 else max(1, len(rows))
    custom_ids = {item["id"] for item in custom_metric_defs or []}
    selected_metrics = [metric for metric in selected_metrics if metric in warehouse.INDEX_NUMERIC_FIELDS or metric in custom_ids]
    return {
        "metrics": selected_metrics,
        "baseline_metric": baseline_metric,
        "run_id": run_id,
        "dump_id": dump_id,
        "fraction_mode": fraction_mode,
        "filters": resolved_filters,
        "data_filters": parsed_data_filters,
        "data_search": data_search,
        "explicit_author_ids": explicit_author_ids or set(),
        "data_sort": data_sort,
        "data_direction": data_direction,
        "data_limit": data_limit,
        "cohort_context": cohort_context,
        "cohort_filter_policy": cohort_filter_policy,
        "rank_top_n": rank_top_n,
        "rows": rows,
        "custom_metrics": custom_metrics.metric_catalog(custom_metric_defs),
    }


def _select_metrics(metrics: list[str] | tuple[str, ...] | None, custom_metric_defs: list[dict[str, str]] | None = None) -> list[str]:
    requested = [str(metric).strip() for metric in (metrics or DEFAULT_SCIENTOMETRIC_METRICS) if str(metric).strip()]
    if not requested:
        requested = list(DEFAULT_SCIENTOMETRIC_METRICS)
    custom_ids = {item["id"] for item in custom_metric_defs or []}
    unsupported = [metric for metric in requested if metric not in warehouse.INDEX_NUMERIC_FIELDS and metric not in custom_ids]
    if unsupported:
        raise ValueError(f"Unsupported scientometric metrics: {', '.join(unsupported)}")
    out: list[str] = []
    for metric in requested:
        if metric not in out:
            out.append(metric)
    return out


def _clean_author_ids(author_ids: list[str] | set[str] | tuple[str, ...] | None) -> set[str] | None:
    if author_ids is None:
        return None
    clean = {str(author_id).strip() for author_id in author_ids if str(author_id).strip()}
    return clean or None


def _analysis_warnings(
    rows: list[dict[str, Any]],
    metrics: list[str],
    *,
    cohort_filter_policy: str,
    rank_top_n: int,
    descriptive: dict[str, Any],
    boxplots: dict[str, Any],
    correlations: dict[str, Any],
    custom_metric_catalog: list[dict[str, Any]] | None = None,
) -> list[str]:
    warnings: list[str] = []
    if not rows:
        warnings.append("В выбранной области анализа нет авторов.")
    elif len(rows) < 5:
        warnings.append("В выборке меньше 5 авторов; корреляции и проверки распределений нестабильны.")
    elif len(rows) < 20:
        warnings.append("В выборке меньше 20 авторов; выводы о распределениях нужно трактовать осторожно.")
    if rows and len(rows) > rank_top_n:
        warnings.append("Ограничение числа авторов влияет на сравнение мест; описательная статистика считается по текущей выборке со страницы «Данные».")
    missing_metrics = [metric for metric in metrics if int((descriptive.get(metric) or {}).get("n") or 0) <= 0]
    if missing_metrics and rows:
        warnings.append(f"Для показателей нет числовых значений: {_metric_list_text_for_catalog(missing_metrics, custom_metric_catalog)}.")
    iqr_zero_metrics = [
        metric
        for metric, payload in boxplots.items()
        if (payload or {}).get("outlier_rule") == "iqr_zero_no_outlier_fence"
    ]
    if iqr_zero_metrics:
        warnings.append(f"Для показателей {_metric_list_text_for_catalog(iqr_zero_metrics, custom_metric_catalog)} межквартильный размах равен нулю; правило выделяющихся значений по ящику с усами здесь неинформативно.")
    skipped_kendall = ((correlations.get("kendall_tau_b") or {}).get("skipped") or [])
    if skipped_kendall:
        warnings.append(f"Расчет коэффициента Кендалла пропущен для {len(skipped_kendall)} пар показателей: слишком много наблюдений для точного расчета.")
    return warnings


def _interpretation(
    rows: list[dict[str, Any]],
    metrics: list[str],
    baseline_metric: str,
    scorecard: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    notes = [
        "Все диагностики считаются внутри выбранного локального среза и группы авторов.",
        "Ранговые и корреляционные диагностики являются описательными и не заменяют экспертную оценку.",
    ]
    candidate_basis: list[str] = []
    if "islv" in metrics:
        notes.append("Сбалансированный индекс локального вклада интерпретируется как локальный показатель на основе процентильных компонентов и штрафа за концентрацию цитирований в одной работе.")
        candidate_basis = [
            "использует процентильные компоненты внутри локального среза",
            "учитывает долевой вклад цитирований",
            "использует штраф за концентрацию цитирований в одной работе",
            "является кандидатным показателем, а не автоматически доказанным лучшим индексом",
        ]
    if "c" in metrics:
        top1_dependence = ((scorecard.get("c") or {}).get("top1_dominance_dependence") or {}).get("abs_spearman_rho")
        if top1_dependence is not None and top1_dependence > 0.5:
            notes.append("Суммарные цитирования заметно связаны с долей самой цитируемой работы, поэтому одна очень цитируемая публикация может сильно влиять на места.")
    return {
        "candidate_balanced_metric": "islv" if rows and "islv" in metrics else None,
        "candidate_balanced_metric_basis": candidate_basis if rows and "islv" in metrics else [],
        "baseline_metric": baseline_metric,
        "warnings": warnings,
        "notes": notes,
    }


def _describe_values(values: list[float], n_total: int) -> dict[str, Any]:
    values = sorted(value for value in values if math.isfinite(value))
    n = len(values)
    missing_count = n_total - n
    if not values:
        return {
            "n": 0,
            "missing_count": missing_count,
            "zero_count": 0,
            "zero_rate": None,
            "min": None,
            "q1": None,
            "median": None,
            "q3": None,
            "max": None,
            "mean": None,
            "stddev": None,
            "coefficient_of_variation": None,
            "iqr": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "skewness": None,
            "excess_kurtosis": None,
            "tie_rate": None,
            "unique_count": 0,
            "outlier_count_iqr": 0,
            "outlier_share_iqr": None,
        }
    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / n
    stddev = math.sqrt(variance)
    q1 = _quantile_sorted(values, 0.25)
    median = _quantile_sorted(values, 0.5)
    q3 = _quantile_sorted(values, 0.75)
    iqr = q3 - q1
    zero_count = sum(1 for value in values if value == 0.0)
    unique_count = len(set(values))
    outlier_count = 0
    if iqr != 0.0:
        low = q1 - 1.5 * iqr
        high = q3 + 1.5 * iqr
        outlier_count = sum(1 for value in values if value < low or value > high)
    return {
        "n": n,
        "missing_count": missing_count,
        "zero_count": zero_count,
        "zero_rate": zero_count / n if n else None,
        "min": values[0],
        "q1": q1,
        "median": median,
        "q3": q3,
        "max": values[-1],
        "mean": mean,
        "stddev": stddev,
        "coefficient_of_variation": (stddev / mean) if mean else None,
        "iqr": iqr,
        "p90": _quantile_sorted(values, 0.9),
        "p95": _quantile_sorted(values, 0.95),
        "p99": _quantile_sorted(values, 0.99),
        "skewness": _skewness(values, mean, stddev),
        "excess_kurtosis": _excess_kurtosis(values, mean, stddev),
        "tie_rate": (n - unique_count) / n if n else None,
        "unique_count": unique_count,
        "outlier_count_iqr": outlier_count,
        "outlier_share_iqr": outlier_count / n if n else None,
    }


def _boxplot_values(rows: list[dict[str, Any]], raw_values: list[float | None]) -> dict[str, Any]:
    pairs = [(row, value) for row, value in zip(rows, raw_values) if value is not None and math.isfinite(value)]
    values = sorted(value for _, value in pairs)
    if not values:
        return {
            "min_whisker": None,
            "q1": None,
            "median": None,
            "q3": None,
            "max_whisker": None,
            "iqr": None,
            "outliers": [],
        }
    q1 = _quantile_sorted(values, 0.25)
    median = _quantile_sorted(values, 0.5)
    q3 = _quantile_sorted(values, 0.75)
    iqr = q3 - q1
    if iqr == 0.0:
        return {
            "min_whisker": values[0],
            "q1": q1,
            "median": median,
            "q3": q3,
            "max_whisker": values[-1],
            "iqr": iqr,
            "lower_fence": None,
            "upper_fence": None,
            "outliers": [],
            "outlier_count": 0,
            "outlier_rule": "iqr_zero_no_outlier_fence",
            "outlier_rule_unstable": True,
            "warning": "Межквартильный размах равен нулю; правило выделяющихся значений по ящику с усами для этого показателя неинформативно.",
        }
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    inner = [value for value in values if low <= value <= high]
    outliers = [
        {
            "author_id": str(row.get("author_id") or ""),
            "author_display_name": row.get("author_display_name") or row.get("display_name") or "",
            "value": value,
        }
        for row, value in pairs
        if value < low or value > high
    ]
    outliers.sort(key=lambda item: (-float(item["value"]), str(item["author_id"])))
    return {
        "min_whisker": min(inner) if inner else values[0],
        "q1": q1,
        "median": median,
        "q3": q3,
        "max_whisker": max(inner) if inner else values[-1],
        "iqr": iqr,
        "lower_fence": low,
        "upper_fence": high,
        "outliers": outliers[:10],
        "outlier_count": len(outliers),
    }


def _histogram(values: list[float], *, bins: int = 12) -> list[dict[str, Any]]:
    values = [value for value in values if math.isfinite(value)]
    if not values:
        return []
    bins = max(1, min(int(bins or 12), 50))
    low = min(values)
    high = max(values)
    if low == high:
        return [{"lo": low, "hi": high, "count": len(values)}]
    width = (high - low) / bins
    counts = [0 for _ in range(bins)]
    for value in values:
        index = min(bins - 1, int((value - low) / width))
        counts[index] += 1
    return [
        {"lo": low + index * width, "hi": low + (index + 1) * width, "count": count}
        for index, count in enumerate(counts)
    ]


def _normality_for_values(values: list[float]) -> dict[str, Any]:
    values = sorted(value for value in values if math.isfinite(value))
    n = len(values)
    if n < 3:
        return {
            "n": n,
            "skewness": None,
            "excess_kurtosis": None,
            "jarque_bera": None,
            "jarque_bera_p_approx": None,
            "qq": _qq_points(values, presorted=True),
            "note": "Для оценки асимметрии и критерия Жарка-Бера нужны как минимум 3 наблюдения.",
        }
    mean = sum(values) / n
    stddev = math.sqrt(sum((value - mean) ** 2 for value in values) / n)
    skewness = _skewness(values, mean, stddev)
    kurtosis = _excess_kurtosis(values, mean, stddev)
    if skewness is None or kurtosis is None:
        jb = None
        p_value = None
    else:
        jb = n / 6.0 * (skewness**2 + (kurtosis**2) / 4.0)
        p_value = math.exp(-jb / 2.0)
    return {
        "n": n,
        "skewness": skewness,
        "excess_kurtosis": kurtosis,
        "jarque_bera": jb,
        "jarque_bera_p_approx": p_value,
        "qq": _qq_points(values, presorted=True),
        "note": "p-значение критерия Жарка-Бера рассчитано по приближению хи-квадрат с 2 степенями свободы.",
    }


def _qq_points(values: list[float], *, max_points: int = 101, presorted: bool = False) -> list[dict[str, float]]:
    if not presorted:
        values = sorted(value for value in values if math.isfinite(value))
    n = len(values)
    if not values:
        return []
    if n <= max_points:
        indices = list(range(n))
    else:
        indices = sorted({round(index * (n - 1) / (max_points - 1)) for index in range(max_points)})
    return [
        {
            "theoretical": _NORMAL.inv_cdf((index + 0.5) / n),
            "observed": values[index],
        }
        for index in indices
    ]


def _correlation_matrix_from_vectors(metrics: list[str], vectors: dict[str, list[float | None]]) -> dict[str, dict[str, float | None]]:
    matrix: dict[str, dict[str, float | None]] = {metric: {} for metric in metrics}
    for left in metrics:
        left_values = vectors.get(left, [])
        for right in metrics:
            matrix[left][right] = _pearson_paired_vectors(left_values, vectors.get(right, []))
    return matrix


def _kendall_tau_b_matrix_from_vectors(metrics: list[str], value_vectors: dict[str, list[float | None]]) -> dict[str, Any]:
    matrix: dict[str, dict[str, float | None]] = {metric: {} for metric in metrics}
    skipped: list[dict[str, Any]] = []
    for left in metrics:
        left_values = value_vectors.get(left, [])
        for right in metrics:
            right_values = value_vectors.get(right, [])
            paired_count = _paired_count_vectors(left_values, right_values)
            if left == right:
                matrix[left][right] = 1.0 if paired_count >= 2 else None
                continue
            if paired_count > KENDALL_MAX_EXACT_N:
                matrix[left][right] = None
                skipped.append(
                    {
                        "left": left,
                        "right": right,
                        "n": paired_count,
                        "reason": f"Точный коэффициент Кендалла не рассчитывается при числе пар больше {KENDALL_MAX_EXACT_N}.",
                    }
                )
            else:
                matrix[left][right] = _kendall_tau_b(_paired_values_from_vectors(left_values, right_values))
    return {
        "matrix": matrix,
        "method": "exact_tau_b_skipped_above_limit",
        "max_exact_n": KENDALL_MAX_EXACT_N,
        "skipped": skipped,
    }


def _metric_value_vectors(rows: list[dict[str, Any]], metrics: list[str] | tuple[str, ...]) -> dict[str, list[float | None]]:
    vectors = {metric: [] for metric in metrics}
    for row in rows:
        for metric in metrics:
            vectors[metric].append(_number(row.get(metric)))
    return vectors


def _rank_vectors(vectors: dict[str, list[float | None]]) -> dict[str, list[float | None]]:
    return {metric: _average_rank_vector(values) for metric, values in vectors.items()}


def _average_rank_vector(values: list[float | None]) -> list[float | None]:
    valid = sorted((value, index) for index, value in enumerate(values) if value is not None)
    ranks: list[float | None] = [None for _ in values]
    position = 0
    while position < len(valid):
        end = position
        while end + 1 < len(valid) and valid[end + 1][0] == valid[position][0]:
            end += 1
        average_rank = (position + 1 + end + 1) / 2.0
        for offset in range(position, end + 1):
            ranks[valid[offset][1]] = average_rank
        position = end + 1
    return ranks


def _pearson_paired_vectors(left_values: list[float | None], right_values: list[float | None]) -> float | None:
    n = 0
    sum_x = 0.0
    sum_y = 0.0
    sum_x2 = 0.0
    sum_y2 = 0.0
    sum_xy = 0.0
    for left, right in zip(left_values, right_values):
        if left is None or right is None:
            continue
        n += 1
        sum_x += left
        sum_y += right
        sum_x2 += left * left
        sum_y2 += right * right
        sum_xy += left * right
    if n < 2:
        return None
    numerator = n * sum_xy - sum_x * sum_y
    x_denominator = n * sum_x2 - sum_x * sum_x
    y_denominator = n * sum_y2 - sum_y * sum_y
    if x_denominator <= 0.0 or y_denominator <= 0.0:
        return None
    return numerator / math.sqrt(x_denominator * y_denominator)


def _paired_count_vectors(left_values: list[float | None], right_values: list[float | None]) -> int:
    return sum(1 for left, right in zip(left_values, right_values) if left is not None and right is not None)


def _paired_values_from_vectors(left_values: list[float | None], right_values: list[float | None]) -> list[tuple[float, float]]:
    return [
        (left, right)
        for left, right in zip(left_values, right_values)
        if left is not None and right is not None
    ]


def _pearson(x_values: list[float], y_values: list[float]) -> float | None:
    n = len(x_values)
    if n < 2 or n != len(y_values):
        return None
    x_mean = sum(x_values) / n
    y_mean = sum(y_values) / n
    x_ss = sum((value - x_mean) ** 2 for value in x_values)
    y_ss = sum((value - y_mean) ** 2 for value in y_values)
    if x_ss == 0.0 or y_ss == 0.0:
        return None
    return sum((x_values[index] - x_mean) * (y_values[index] - y_mean) for index in range(n)) / math.sqrt(x_ss * y_ss)


def _kendall_tau_b(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 2:
        return None
    concordant = 0
    discordant = 0
    ties_x = 0
    ties_y = 0
    for i in range(len(pairs) - 1):
        x1, y1 = pairs[i]
        for j in range(i + 1, len(pairs)):
            x2, y2 = pairs[j]
            dx = _sign(x1 - x2)
            dy = _sign(y1 - y2)
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                ties_x += 1
            elif dy == 0:
                ties_y += 1
            elif dx == dy:
                concordant += 1
            else:
                discordant += 1
    denominator = math.sqrt((concordant + discordant + ties_x) * (concordant + discordant + ties_y))
    if denominator == 0.0:
        return None
    return (concordant - discordant) / denominator


def _competition_ranks(rows: list[dict[str, Any]], metric: str) -> dict[str, int]:
    items = []
    for row in rows:
        author_id = str(row.get("author_id") or "").strip()
        value = _number(row.get(metric))
        if author_id and value is not None:
            items.append((author_id, value))
    items.sort(key=lambda item: (-item[1], item[0]))
    ranks: dict[str, int] = {}
    current_rank = 0
    previous_value = None
    for index, (author_id, value) in enumerate(items, start=1):
        if previous_value is None or value != previous_value:
            current_rank = index
            previous_value = value
        ranks[author_id] = current_rank
    return ranks


def _row_author_ids(rows: list[dict[str, Any]]) -> list[str]:
    return [str(row.get("author_id") or "").strip() for row in rows]


def _competition_ranks_from_vectors(author_ids: list[str], values: list[float | None]) -> dict[str, int]:
    items = [
        (author_id, value)
        for author_id, value in zip(author_ids, values)
        if author_id and value is not None
    ]
    items.sort(key=lambda item: (-item[1], item[0]))
    ranks: dict[str, int] = {}
    current_rank = 0
    previous_value = None
    for index, (author_id, value) in enumerate(items, start=1):
        if previous_value is None or value != previous_value:
            current_rank = index
            previous_value = value
        ranks[author_id] = current_rank
    return ranks


def _top_overlap_matrix_from_ordered(ordered_authors: dict[str, list[str]], cuts: list[int]) -> dict[str, Any]:
    metrics = list(ordered_authors.keys())
    top_sets = {metric: {cut: set(authors[:cut]) for cut in cuts} for metric, authors in ordered_authors.items()}
    payload: dict[str, Any] = {}
    for left in metrics:
        payload[left] = {}
        for right in metrics:
            by_cut = {}
            for cut in cuts:
                left_top = top_sets[left].get(cut, set())
                right_top = top_sets[right].get(cut, set())
                by_cut[str(cut)] = {
                    "overlap": len(left_top & right_top),
                    "jaccard": _jaccard(left_top, right_top),
                    "left_n": len(left_top),
                    "right_n": len(right_top),
                }
            payload[left][right] = by_cut
    return {
        "mode": "exact_n_by_competition_rank_then_author_id",
        "cuts": cuts,
        "matrix": payload,
    }


def _overlap_cuts(top_n: int) -> list[int]:
    cuts = sorted({cut for cut in (*DEFAULT_OVERLAP_CUTS, top_n) if cut > 0})
    return cuts


def _outlier_table(boxplots: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {metric: list((payload or {}).get("outliers") or []) for metric, payload in boxplots.items()}


def _metric_outlier_rows(rows: list[dict[str, Any]], metric: str) -> list[dict[str, Any]]:
    pairs = _metric_pairs(rows, metric)
    values = sorted(value for _, value in pairs)
    if not values:
        return []
    q1 = _quantile(values, 0.25)
    q3 = _quantile(values, 0.75)
    iqr = q3 - q1
    if iqr == 0.0:
        return []
    lower_fence = q1 - 1.5 * iqr
    upper_fence = q3 + 1.5 * iqr
    payload = [
        {
            "metric": metric,
            "author_id": str(row.get("author_id") or ""),
            "author_display_name": row.get("author_display_name") or row.get("display_name") or "",
            "value": value,
            "rule": "iqr_1_5",
            "lower_fence": lower_fence,
            "upper_fence": upper_fence,
        }
        for row, value in pairs
        if value < lower_fence or value > upper_fence
    ]
    return sorted(payload, key=lambda item: (-float(item["value"]), str(item["author_id"])))


def _metric_pairs(rows: list[dict[str, Any]], metric: str) -> list[tuple[dict[str, Any], float]]:
    pairs: list[tuple[dict[str, Any], float]] = []
    for row in rows:
        value = _number(row.get(metric))
        if value is not None:
            pairs.append((row, value))
    return pairs


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return _quantile_sorted(ordered, q)


def _quantile_sorted(ordered: list[float], q: float) -> float:
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return ordered[int(pos)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (pos - lower)


def _skewness(values: list[float], mean: float, stddev: float) -> float | None:
    if not values or stddev == 0.0:
        return None
    n = len(values)
    return sum(((value - mean) / stddev) ** 3 for value in values) / n


def _excess_kurtosis(values: list[float], mean: float, stddev: float) -> float | None:
    if not values or stddev == 0.0:
        return None
    n = len(values)
    return sum(((value - mean) / stddev) ** 4 for value in values) / n - 3.0


def _dependence_payload(value: float | None) -> dict[str, Any]:
    if value is None:
        return {"spearman_rho": None, "abs_spearman_rho": None, "direction": "undefined"}
    if value > 0:
        direction = "positive"
    elif value < 0:
        direction = "negative"
    else:
        direction = "zero"
    return {
        "spearman_rho": value,
        "abs_spearman_rho": abs(value),
        "direction": direction,
    }


def _share(values: list[float], predicate: Any) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if predicate(value)) / len(values)


def _jaccard(left: set[str], right: set[str]) -> float | None:
    union = left | right
    if not union:
        return None
    return len(left & right) / len(union)


def _author_name(rows: list[dict[str, Any]], author_id: str) -> str:
    for row in rows:
        if str(row.get("author_id") or "") == author_id:
            return str(row.get("author_display_name") or row.get("display_name") or "")
    return ""


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0
