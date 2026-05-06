from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

from app.services import cohorts, warehouse
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
SCIENTOMETRIC_ANALYSIS_VERSION = "scientometrics_v1"
DEFAULT_OVERLAP_CUTS = (10, 20, 50)
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
) -> dict[str, Any]:
    selected_metrics = _select_metrics(metrics)
    baseline_metric = str(baseline_metric or "h").strip() or "h"
    if baseline_metric not in warehouse.INDEX_NUMERIC_FIELDS:
        raise ValueError(f"Unsupported baseline_metric: {baseline_metric}")
    if baseline_metric not in selected_metrics:
        selected_metrics = [baseline_metric, *selected_metrics]

    request_filters = clean_analysis_filters(filters or {})
    author_ids = None
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
        author_ids = ctx.get("author_ids")
        cohort_context = cohorts.cohort_context_summary(ctx)
        cohort_filter_policy = str(ctx.get("filter_policy") or cohort_filter_policy or "membership")
    else:
        scope = warehouse.resolve_analysis_scope(run_id=run_id, dump_id=dump_id)
        run_id = scope["run_id"]
        dump_id = scope["dump_id"]
        fraction_mode = str(fraction_mode or "strict_authors_count")
        resolved_filters = request_filters

    top_n = max(1, min(int(top_n or 100), 1000))
    rows = warehouse.filtered_author_indices(fraction_mode, resolved_filters, run_id=run_id, dump_id=dump_id)
    rows = warehouse.filter_rows_by_author_ids(rows, author_ids)
    selected_metrics = [metric for metric in selected_metrics if _has_metric_data(rows, metric) or metric in warehouse.INDEX_NUMERIC_FIELDS]

    descriptive = describe_metrics(rows, selected_metrics)
    boxplots = boxplot_metrics(rows, selected_metrics)
    histograms = histogram_metrics(rows, selected_metrics)
    normality = normality_metrics(rows, selected_metrics)
    correlations = correlation_matrices(rows, selected_metrics)
    rank_comparison_payload = rank_comparisons(rows, selected_metrics, baseline_metric=baseline_metric, top_n=top_n)
    scorecard = metric_scorecard(rows, selected_metrics, descriptive=descriptive)
    warnings = _analysis_warnings(rows, selected_metrics, cohort_filter_policy=cohort_filter_policy)

    return {
        "analysis_version": SCIENTOMETRIC_ANALYSIS_VERSION,
        "scope": {
            "run_id": run_id,
            "dump_id": dump_id,
            "fraction_mode": fraction_mode,
            "filters": resolved_filters,
            "cohort_id": cohort_id,
            "cohort_filter_policy": cohort_filter_policy,
            "baseline_metric": baseline_metric,
            "top_n": top_n,
            "n_authors": len(rows),
            "metric_scope": "filtered_recomputed",
            "percentile_scope": "current filtered author set",
        },
        "cohort_context": cohort_context,
        "metrics": selected_metrics,
        "n_authors": len(rows),
        "descriptive": descriptive,
        "boxplots": boxplots,
        "histograms": histograms,
        "normality": normality,
        "correlations": correlations,
        "rank_comparisons": rank_comparison_payload["comparisons"],
        "top_overlap": rank_comparison_payload["top_overlap"],
        "outliers": _outlier_table(boxplots),
        "metric_scorecard": scorecard,
        "interpretation": _interpretation(rows, selected_metrics, baseline_metric, scorecard, warnings),
        "warnings": warnings,
    }


def describe_metrics(rows: list[dict[str, Any]], metrics: list[str] | tuple[str, ...]) -> dict[str, Any]:
    return {metric: _describe_metric(rows, metric) for metric in metrics}


def boxplot_metrics(rows: list[dict[str, Any]], metrics: list[str] | tuple[str, ...]) -> dict[str, Any]:
    return {metric: _boxplot_metric(rows, metric) for metric in metrics}


def histogram_metrics(rows: list[dict[str, Any]], metrics: list[str] | tuple[str, ...], *, bins: int = 12) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for metric in metrics:
        values = _metric_values(rows, metric)
        payload[metric] = {
            "raw": _histogram(values, bins=bins),
            "log1p": _histogram([math.log1p(max(0.0, value)) for value in values], bins=bins),
        }
    return payload


def normality_metrics(rows: list[dict[str, Any]], metrics: list[str] | tuple[str, ...]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for metric in metrics:
        values = _metric_values(rows, metric)
        log_values = [math.log1p(max(0.0, value)) for value in values]
        payload[metric] = {
            "raw": _normality_for_values(values),
            "log1p": _normality_for_values(log_values),
        }
    return payload


def correlation_matrices(rows: list[dict[str, Any]], metrics: list[str] | tuple[str, ...]) -> dict[str, Any]:
    selected = list(metrics)
    return {
        "pearson_log1p": _correlation_matrix(rows, selected, method="pearson_log1p"),
        "spearman": _correlation_matrix(rows, selected, method="spearman"),
        "kendall_tau_b": _correlation_matrix(rows, selected, method="kendall_tau_b"),
    }


def rank_comparisons(
    rows: list[dict[str, Any]],
    metrics: list[str] | tuple[str, ...],
    *,
    baseline_metric: str = "h",
    top_n: int = 100,
) -> dict[str, Any]:
    selected = list(metrics)
    ranks = {metric: _competition_ranks(rows, metric) for metric in selected}
    overlap_cuts = _overlap_cuts(top_n)
    top_overlap = _top_overlap_matrix(ranks, overlap_cuts)
    baseline_ranks = ranks.get(baseline_metric, {})
    comparisons: dict[str, Any] = {}
    for metric in selected:
        if metric == baseline_metric:
            continue
        metric_ranks = ranks.get(metric, {})
        common = sorted(set(baseline_ranks) & set(metric_ranks))
        deltas = [
            {
                "author_id": author_id,
                "author_display_name": _author_name(rows, author_id),
                "baseline_rank": baseline_ranks[author_id],
                "metric_rank": metric_ranks[author_id],
                "rank_delta": metric_ranks[author_id] - baseline_ranks[author_id],
                "abs_rank_delta": abs(metric_ranks[author_id] - baseline_ranks[author_id]),
            }
            for author_id in common
        ]
        abs_values = [float(item["abs_rank_delta"]) for item in deltas]
        top_base = _top_set(baseline_ranks, top_n)
        top_metric = _top_set(metric_ranks, top_n)
        comparisons[metric] = {
            "baseline_metric": baseline_metric,
            "metric": metric,
            "n_common_authors": len(common),
            "median_abs_delta": _quantile(abs_values, 0.5) if abs_values else None,
            "p90_abs_delta": _quantile(abs_values, 0.9) if abs_values else None,
            "max_abs_delta": max(abs_values) if abs_values else None,
            "share_abs_delta_le_5": _share(abs_values, lambda value: value <= 5.0),
            "top_overlap": len(top_base & top_metric),
            "jaccard_top_n": _jaccard(top_base, top_metric),
            "largest_shifts": sorted(deltas, key=lambda item: (-item["abs_rank_delta"], item["author_id"]))[:20],
        }
    return {"comparisons": comparisons, "top_overlap": top_overlap}


def metric_scorecard(
    rows: list[dict[str, Any]],
    metrics: list[str] | tuple[str, ...],
    *,
    descriptive: dict[str, Any] | None = None,
) -> dict[str, Any]:
    descriptive = descriptive or describe_metrics(rows, metrics)
    factors = {
        "publication_volume_dependence": "p",
        "citation_volume_dependence": "c",
        "fractional_citation_dependence": "c_frac",
        "top1_dominance_dependence": "top1_share",
        "collaboration_size_dependence": "mean_authors_per_work",
    }
    payload: dict[str, Any] = {}
    for metric in metrics:
        metric_payload = {
            label: _spearman_for_metrics(rows, metric, factor)
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


def _select_metrics(metrics: list[str] | tuple[str, ...] | None) -> list[str]:
    requested = [str(metric).strip() for metric in (metrics or DEFAULT_SCIENTOMETRIC_METRICS) if str(metric).strip()]
    if not requested:
        requested = list(DEFAULT_SCIENTOMETRIC_METRICS)
    unsupported = [metric for metric in requested if metric not in warehouse.INDEX_NUMERIC_FIELDS]
    if unsupported:
        raise ValueError(f"Unsupported scientometric metrics: {', '.join(unsupported)}")
    out: list[str] = []
    for metric in requested:
        if metric not in out:
            out.append(metric)
    return out


def _analysis_warnings(rows: list[dict[str, Any]], metrics: list[str], *, cohort_filter_policy: str) -> list[str]:
    warnings: list[str] = []
    if not rows:
        warnings.append("No authors matched the resolved scientometric analysis scope.")
    elif len(rows) < 5:
        warnings.append("The author set is very small; correlation and normality diagnostics are unstable.")
    if cohort_filter_policy == "auto":
        warnings.append("cohort_filter_policy=auto is a legacy compatibility mode and should not be used for final analysis.")
    missing_metrics = [metric for metric in metrics if not _metric_values(rows, metric)]
    if missing_metrics and rows:
        warnings.append(f"No numeric values were available for metrics: {', '.join(missing_metrics)}.")
    return warnings


def _interpretation(
    rows: list[dict[str, Any]],
    metrics: list[str],
    baseline_metric: str,
    scorecard: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    notes = [
        "All diagnostics are computed inside the resolved local run/dump/cohort scope.",
        "Rank and correlation diagnostics are descriptive; they do not replace expert assessment.",
    ]
    if "islv" in metrics:
        notes.append("ISLV is interpreted as a local balanced visibility indicator based on percentile components and a top1 concentration penalty.")
    if "c" in metrics:
        top1_dependence = (scorecard.get("c") or {}).get("top1_dominance_dependence")
        if top1_dependence is not None and top1_dependence > 0.5:
            notes.append("Total citations show elevated association with top1_share, so one highly cited work may strongly affect rank positions.")
    best_balanced = "islv" if "islv" in metrics else baseline_metric
    return {
        "best_balanced_metric": best_balanced if rows else None,
        "baseline_metric": baseline_metric,
        "warnings": warnings,
        "notes": notes,
    }


def _describe_metric(rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    values = sorted(_metric_values(rows, metric))
    n_total = len(rows)
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
    q1 = _quantile(values, 0.25)
    median = _quantile(values, 0.5)
    q3 = _quantile(values, 0.75)
    iqr = q3 - q1
    zero_count = sum(1 for value in values if value == 0.0)
    unique_count = len(set(values))
    outliers = _iqr_outlier_values(values)
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
        "p90": _quantile(values, 0.9),
        "p95": _quantile(values, 0.95),
        "p99": _quantile(values, 0.99),
        "skewness": _skewness(values, mean, stddev),
        "excess_kurtosis": _excess_kurtosis(values, mean, stddev),
        "tie_rate": (n - unique_count) / n if n else None,
        "unique_count": unique_count,
        "outlier_count_iqr": len(outliers),
        "outlier_share_iqr": len(outliers) / n if n else None,
    }


def _boxplot_metric(rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    pairs = _metric_pairs(rows, metric)
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
    q1 = _quantile(values, 0.25)
    median = _quantile(values, 0.5)
    q3 = _quantile(values, 0.75)
    iqr = q3 - q1
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
            "qq": _qq_points(values),
            "note": "At least 3 observations are required for skewness and Jarque-Bera diagnostics.",
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
        "qq": _qq_points(values),
        "note": "Jarque-Bera p-value uses the chi-square df=2 survival approximation exp(-JB/2).",
    }


def _qq_points(values: list[float], *, max_points: int = 101) -> list[dict[str, float]]:
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


def _correlation_matrix(rows: list[dict[str, Any]], metrics: list[str], *, method: str) -> dict[str, dict[str, float | None]]:
    matrix: dict[str, dict[str, float | None]] = {metric: {} for metric in metrics}
    for left in metrics:
        for right in metrics:
            pairs = _paired_values(rows, left, right)
            if method == "pearson_log1p":
                x_values = [math.log1p(max(0.0, pair[0])) for pair in pairs]
                y_values = [math.log1p(max(0.0, pair[1])) for pair in pairs]
                value = _pearson(x_values, y_values)
            elif method == "spearman":
                value = _spearman_pairs(pairs)
            else:
                value = _kendall_tau_b(pairs)
            matrix[left][right] = value
    return matrix


def _spearman_for_metrics(rows: list[dict[str, Any]], left: str, right: str) -> float | None:
    return _spearman_pairs(_paired_values(rows, left, right))


def _paired_values(rows: list[dict[str, Any]], left: str, right: str) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        left_value = _number(row.get(left))
        right_value = _number(row.get(right))
        if left_value is not None and right_value is not None:
            pairs.append((left_value, right_value))
    return pairs


def _spearman_pairs(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 2:
        return None
    x_ranks = _average_ranks([pair[0] for pair in pairs])
    y_ranks = _average_ranks([pair[1] for pair in pairs])
    return _pearson(x_ranks, y_ranks)


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
    pairs = pairs[:1000]
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


def _top_overlap_matrix(ranks: dict[str, dict[str, int]], cuts: list[int]) -> dict[str, Any]:
    metrics = list(ranks.keys())
    payload: dict[str, Any] = {}
    for left in metrics:
        payload[left] = {}
        for right in metrics:
            by_cut = {}
            for cut in cuts:
                left_top = _top_set(ranks[left], cut)
                right_top = _top_set(ranks[right], cut)
                by_cut[str(cut)] = {
                    "overlap": len(left_top & right_top),
                    "jaccard": _jaccard(left_top, right_top),
                    "left_n": len(left_top),
                    "right_n": len(right_top),
                }
            payload[left][right] = by_cut
    return payload


def _top_set(ranks: dict[str, int], n: int) -> set[str]:
    return {author_id for author_id, rank in ranks.items() if rank <= n}


def _overlap_cuts(top_n: int) -> list[int]:
    cuts = sorted({cut for cut in (*DEFAULT_OVERLAP_CUTS, top_n) if cut > 0})
    return cuts


def _outlier_table(boxplots: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {metric: list((payload or {}).get("outliers") or []) for metric, payload in boxplots.items()}


def _metric_values(rows: list[dict[str, Any]], metric: str) -> list[float]:
    return [value for _, value in _metric_pairs(rows, metric)]


def _metric_pairs(rows: list[dict[str, Any]], metric: str) -> list[tuple[dict[str, Any], float]]:
    pairs: list[tuple[dict[str, Any], float]] = []
    for row in rows:
        value = _number(row.get(metric))
        if value is not None:
            pairs.append((row, value))
    return pairs


def _has_metric_data(rows: list[dict[str, Any]], metric: str) -> bool:
    return any(_number(row.get(metric)) is not None for row in rows)


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
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


def _iqr_outlier_values(values: list[float]) -> list[float]:
    if not values:
        return []
    q1 = _quantile(values, 0.25)
    q3 = _quantile(values, 0.75)
    iqr = q3 - q1
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    return [value for value in values if value < low or value > high]


def _average_ranks(values: list[float]) -> list[float]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    ranks = [0.0 for _ in values]
    position = 0
    while position < len(ordered):
        end = position
        while end + 1 < len(ordered) and ordered[end + 1][0] == ordered[position][0]:
            end += 1
        average_rank = (position + 1 + end + 1) / 2.0
        for offset in range(position, end + 1):
            ranks[ordered[offset][1]] = average_rank
        position = end + 1
    return ranks


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
