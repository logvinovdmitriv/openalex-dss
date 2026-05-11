from __future__ import annotations

import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from typing import Any

from app.core.paths import DATA
from app.services import pipeline, warehouse
from app.services.internal_payloads import normalize_internal_pipeline_payload
from app.services.scientometrics import build_scientometric_analysis


ANALYSIS_ACTIONS = {"recalculate", "bootstrap_analysis", "permutation_analysis", "convergence_analysis"}


StageProgressCallback = Callable[[int | None, str, dict[str, Any] | None], None]


def recalculate(
    run_id: str,
    payload: dict[str, Any],
    *,
    update_progress_callback: StageProgressCallback | None = None,
) -> dict[str, Any]:
    return pipeline.recalculate(
        normalize_internal_pipeline_payload({**payload, "run_id": run_id}),
        progress_callback=update_progress_callback,
    )


def dispatch(
    run_id: str,
    action: str,
    payload: dict[str, Any],
    *,
    update_progress_callback: StageProgressCallback | None = None,
) -> dict[str, Any]:
    payload = normalize_internal_pipeline_payload(payload)
    if action == "recalculate":
        return recalculate(run_id, payload, update_progress_callback=update_progress_callback)
    if action == "bootstrap_analysis":
        return _long_analysis_job(run_id, action, payload, update_progress_callback=update_progress_callback, mode="bootstrap")
    if action == "permutation_analysis":
        return _long_analysis_job(run_id, action, payload, update_progress_callback=update_progress_callback, mode="permutation")
    if action == "convergence_analysis":
        return _long_analysis_job(run_id, action, payload, update_progress_callback=update_progress_callback, mode="convergence")
    raise ValueError(f"Unsupported analysis job action: {action}")


def _long_analysis_job(
    run_id: str,
    action: str,
    payload: dict[str, Any],
    *,
    update_progress_callback: StageProgressCallback | None,
    mode: str,
) -> dict[str, Any]:
    params = _analysis_params(payload)
    if update_progress_callback:
        update_progress_callback(5, "Подготовка анализа", {"prepare_percent": 5, "analysis_mode": mode})
    analysis = build_scientometric_analysis(**params)
    rows = _rows_for_protocol(params, analysis, payload)
    if update_progress_callback:
        update_progress_callback(75, f"Расчет протокола {mode}", {"compute_percent": 75, "analysis_mode": mode})
    result = _protocol_result(mode, analysis, payload, rows)
    artifact = _write_analysis_artifact(run_id, action, result)
    if update_progress_callback:
        update_progress_callback(100, "Сохранение артефактов анализа", {"write_percent": 100, "artifact_path": str(artifact)})
    return {
        "status": "ok",
        "mode": mode,
        "analysis_scope": analysis.get("scope") or {},
        "artifact_path": str(artifact),
        "artifact": result,
    }


def _analysis_params(payload: dict[str, Any]) -> dict[str, Any]:
    metrics = payload.get("metrics")
    if isinstance(metrics, str):
        metrics = [item.strip() for item in metrics.split(",") if item.strip()]
    elif not isinstance(metrics, (list, tuple)):
        metrics = None
    return {
        "fraction_mode": str(payload.get("fraction_mode") or payload.get("fraction_mode_default") or "strict_authors_count"),
        "metrics": list(metrics) if metrics else None,
        "baseline_metric": str(payload.get("baseline_metric") or "h"),
        "run_id": str(payload.get("analysis_run_id") or payload.get("source_run_id") or "").strip(),
        "dump_id": str(payload.get("dump_id") or "").strip(),
        "top_n": int(payload.get("top_n") or 100),
        "filters": payload.get("filters") if isinstance(payload.get("filters"), dict) else None,
        "data_filters": payload.get("data_filters") if isinstance(payload.get("data_filters"), dict) else None,
        "data_search": str(payload.get("data_search") or ""),
        "data_sort": str(payload.get("data_sort") or ""),
        "data_direction": str(payload.get("data_direction") or "desc"),
        "data_limit": int(payload.get("data_limit") or 0),
    }


def _protocol_result(mode: str, analysis: dict[str, Any], payload: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    iterations = max(10, min(10_000, int(payload.get("iterations") or payload.get("samples") or 200)))
    if mode == "bootstrap":
        return {
            "protocol": "bootstrap_interval_job",
            "iterations_requested": iterations,
            "scope": analysis.get("scope") or {},
            "methodology_checks": _methodology_checks(rows, analysis),
            "summary": _bootstrap_summary(rows, analysis, iterations, payload),
        }
    if mode == "permutation":
        return {
            "protocol": "permutation_overlap_job",
            "iterations_requested": iterations,
            "scope": analysis.get("scope") or {},
            "methodology_checks": _methodology_checks(rows, analysis),
            "summary": _permutation_summary(rows, analysis, iterations, payload),
        }
    return {
        "protocol": "convergence_by_prefix_job",
        "prefix_sizes": _prefix_sizes(payload, int((analysis.get("scope") or {}).get("n_authors") or analysis.get("n_authors") or 0)),
        "scope": analysis.get("scope") or {},
        "methodology_checks": _methodology_checks(rows, analysis),
        "summary": _convergence_summary(rows, analysis, payload),
    }


def _rows_for_protocol(params: dict[str, Any], analysis: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    selected_metrics = list(analysis.get("metrics") or params.get("metrics") or ["p", "c", "c_frac", "h", "i10", "g"])
    select_fields = {"author_id", "author_display_name", "c", "p", *selected_metrics}
    limit = max(0, min(500_000, int(payload.get("protocol_data_limit") or params.get("data_limit") or 0)))
    return warehouse.selected_index_rows(
        str(params.get("fraction_mode") or "strict_authors_count"),
        params.get("filters") if isinstance(params.get("filters"), dict) else None,
        run_id=str(params.get("run_id") or ""),
        dump_id=str(params.get("dump_id") or ""),
        data_filters=params.get("data_filters") if isinstance(params.get("data_filters"), dict) else None,
        data_search=str(params.get("data_search") or ""),
        data_sort=str(params.get("data_sort") or ""),
        data_direction=str(params.get("data_direction") or "desc"),
        data_limit=limit,
        select_fields=select_fields,
    )


def _bootstrap_summary(rows: list[dict[str, Any]], analysis: dict[str, Any], iterations: int, payload: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = list(analysis.get("metrics") or [])
    sample_size = max(2, min(len(rows), int(payload.get("sample_size") or len(rows) or 0)))
    if len(rows) < 3 or sample_size < 3:
        return []
    rng = random.Random(int(payload.get("random_seed") or 20260510))
    pairs = _metric_pairs(metrics)
    samples: dict[tuple[str, str], list[float]] = {pair: [] for pair in pairs}
    for _ in range(iterations):
        sample = [rows[rng.randrange(len(rows))] for _sample_index in range(sample_size)]
        for pair in pairs:
            value = _spearman(sample, pair[0], pair[1])
            if value is not None:
                samples[pair].append(value)
    output: list[dict[str, Any]] = []
    for left, right in pairs:
        if _metric_is_constant(rows, left) or _metric_is_constant(rows, right):
            output.append(
                {
                    "metric_a": left,
                    "metric_b": right,
                    "statistic": "spearman",
                    "status": "constant_metric",
                    "message": "Bootstrap CI не рассчитан: один из показателей не изменяется в выбранном срезе.",
                    "iterations": 0,
                    "sample_size": sample_size,
                    "method": "bootstrap_resampling_authors",
                }
            )
            continue
        values = sorted(samples[(left, right)])
        if not values:
            continue
        output.append(
            {
                "metric_a": left,
                "metric_b": right,
                "statistic": "spearman",
                "estimate": _spearman_from_rows(rows, left, right),
                "ci_low": _quantile(values, 0.025),
                "ci_high": _quantile(values, 0.975),
                "iterations": len(values),
                "sample_size": sample_size,
                "method": "bootstrap_resampling_authors",
                "status": "ok",
            }
        )
    return output


def _permutation_summary(rows: list[dict[str, Any]], analysis: dict[str, Any], iterations: int, payload: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = list(analysis.get("metrics") or [])
    top_n = max(1, min(len(rows), int(payload.get("top_n") or (analysis.get("scope") or {}).get("rank_top_n") or 20)))
    if len(rows) < 2:
        return []
    rng = random.Random(int(payload.get("random_seed") or 20260510))
    author_ids = [str(row.get("author_id") or "") for row in rows if str(row.get("author_id") or "")]
    ranks = {metric: _ordered_authors(rows, metric) for metric in metrics}
    output: list[dict[str, Any]] = []
    for left, right in _metric_pairs(metrics):
        if _metric_is_constant(rows, left) or _metric_is_constant(rows, right):
            output.append(
                {
                    "metric_a": left,
                    "metric_b": right,
                    "top_n": top_n,
                    "status": "constant_metric",
                    "message": "Permutation test не рассчитан: один из показателей не изменяется в выбранном срезе.",
                    "iterations": 0,
                    "null_model": "random_top_n_without_replacement",
                }
            )
            continue
        left_top = set(ranks.get(left, [])[:top_n])
        right_top = set(ranks.get(right, [])[:top_n])
        observed = len(left_top & right_top)
        extreme = 0
        for _ in range(iterations):
            random_top = set(rng.sample(author_ids, min(top_n, len(author_ids))))
            if len(left_top & random_top) >= observed:
                extreme += 1
        denominator = min(top_n, len(author_ids))
        output.append(
            {
                "metric_a": left,
                "metric_b": right,
                "top_n": top_n,
                "observed_overlap": observed,
                "observed_overlap_rate": (observed / denominator) if denominator else None,
                "permutation_p_value": (extreme + 1) / (iterations + 1),
                "iterations": iterations,
                "null_model": "random_top_n_without_replacement",
                "p_value_holm": None,
                "status": "ok",
            }
        )
    _apply_holm_adjustment(output)
    return output


def _convergence_summary(rows: list[dict[str, Any]], analysis: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    n_authors = int((analysis.get("scope") or {}).get("n_authors") or analysis.get("n_authors") or len(rows))
    prefixes = _prefix_sizes(payload, n_authors)
    baseline = str((analysis.get("scope") or {}).get("baseline_metric") or "h")
    full_order = _ordered_authors(rows, baseline)
    full_ranks = {author_id: index + 1 for index, author_id in enumerate(full_order)}
    top_n = max(1, min(len(rows), int(payload.get("top_n") or (analysis.get("scope") or {}).get("rank_top_n") or 20)))
    output: list[dict[str, Any]] = []
    sorted_rows = sorted(rows, key=lambda row: str(row.get("author_id") or ""))
    for size in prefixes:
        prefix_rows = sorted_rows[:size]
        prefix_order = _ordered_authors(prefix_rows, baseline)
        prefix_ranks = {author_id: index + 1 for index, author_id in enumerate(prefix_order)}
        common = [author_id for author_id in prefix_ranks if author_id in full_ranks]
        ratio = (size / n_authors) if n_authors else 0.0
        top_overlap = len(set(prefix_order[:top_n]) & set(full_order[:top_n]))
        output.append(
            {
                "prefix_size": size,
                "full_size": n_authors,
                "coverage_ratio": ratio,
                "spearman_vs_full": _spearman_rank_maps(prefix_ranks, full_ranks, common),
                "top_overlap": top_overlap,
                "top_overlap_rate": top_overlap / min(top_n, len(full_order), max(1, len(prefix_order))),
                "protocol": "author_prefix_convergence",
            }
        )
    return output


def _prefix_sizes(payload: dict[str, Any], n_authors: int) -> list[int]:
    raw = payload.get("prefix_sizes")
    if isinstance(raw, str):
        values = [int(item) for item in raw.split(",") if item.strip().isdigit()]
    elif isinstance(raw, (list, tuple)):
        values = [int(item) for item in raw if str(item).strip().isdigit()]
    else:
        values = [500, 1_000, 2_000, 5_000, n_authors]
    return sorted({value for value in values if value > 0 and (n_authors <= 0 or value <= n_authors)})


def _metric_pairs(metrics: list[str]) -> list[tuple[str, str]]:
    cleaned = [metric for metric in metrics if metric]
    return [(left, right) for index, left in enumerate(cleaned) for right in cleaned[index + 1 :]]


def _methodology_checks(rows: list[dict[str, Any]], analysis: dict[str, Any]) -> dict[str, Any]:
    metrics = list(analysis.get("metrics") or [])
    constant_metrics = [metric for metric in metrics if _metric_is_constant(rows, metric)]
    all_zero_metrics = [metric for metric in metrics if rows and all(_numeric(row.get(metric)) == 0.0 for row in rows)]
    return {
        "n_authors": len(rows),
        "min_rows_for_rank_correlation": 3,
        "min_rows_for_topn_overlap": 2,
        "constant_metrics": constant_metrics,
        "all_zero_metrics": all_zero_metrics,
        "status": "ok" if len(rows) >= 3 and not constant_metrics else "limited",
    }


def _metric_is_constant(rows: list[dict[str, Any]], metric: str) -> bool:
    if len(rows) < 2:
        return True
    values = {round(_numeric(row.get(metric)), 12) for row in rows}
    return len(values) <= 1


def _apply_holm_adjustment(rows: list[dict[str, Any]]) -> None:
    tests = [row for row in rows if row.get("status") == "ok" and isinstance(row.get("permutation_p_value"), (int, float))]
    ordered = sorted(tests, key=lambda row: float(row["permutation_p_value"]))
    m = len(ordered)
    running = 0.0
    for index, row in enumerate(ordered):
        adjusted = min(1.0, float(row["permutation_p_value"]) * (m - index))
        running = max(running, adjusted)
        row["p_value_holm"] = running


def _ordered_authors(rows: list[dict[str, Any]], metric: str) -> list[str]:
    ordered = sorted(
        rows,
        key=lambda row: (
            -_numeric(row.get(metric)),
            -_numeric(row.get("c")),
            -_numeric(row.get("p")),
            str(row.get("author_id") or ""),
        ),
    )
    return [str(row.get("author_id") or "") for row in ordered if str(row.get("author_id") or "")]


def _spearman_from_rows(rows: list[dict[str, Any]], left: str, right: str) -> float | None:
    left_order = _ordered_authors(rows, left)
    right_order = _ordered_authors(rows, right)
    left_ranks = {author_id: index + 1 for index, author_id in enumerate(left_order)}
    right_ranks = {author_id: index + 1 for index, author_id in enumerate(right_order)}
    common = [author_id for author_id in left_ranks if author_id in right_ranks]
    return _spearman_rank_maps(left_ranks, right_ranks, common)


def _spearman(rows: list[dict[str, Any]], left: str, right: str) -> float | None:
    return _spearman_from_rows(rows, left, right)


def _spearman_rank_maps(left_ranks: dict[str, int], right_ranks: dict[str, int], common: list[str]) -> float | None:
    if len(common) < 3:
        return None
    left_values = [float(left_ranks[author_id]) for author_id in common]
    right_values = [float(right_ranks[author_id]) for author_id in common]
    return _pearson(left_values, right_values)


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum((x - mean_left) * (y - mean_right) for x, y in zip(left, right))
    denom_left = math.sqrt(sum((x - mean_left) ** 2 for x in left))
    denom_right = math.sqrt(sum((y - mean_right) ** 2 for y in right))
    denominator = denom_left * denom_right
    if denominator == 0:
        return None
    return numerator / denominator


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    position = max(0.0, min(1.0, q)) * (len(values) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(values[lower])
    fraction = position - lower
    return float(values[lower] * (1.0 - fraction) + values[upper] * fraction)


def _numeric(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return number


def _write_analysis_artifact(run_id: str, action: str, payload: dict[str, Any]) -> Path:
    base = DATA / "runs" / run_id / "analysis_jobs"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{action}.json"
    path.write_text(
        json.dumps(
            {
                "schema": "openalex_dss_analysis_job.v1",
                "action": action,
                "job_run_id": run_id,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                **payload,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path
