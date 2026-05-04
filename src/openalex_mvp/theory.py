from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .io_utils import as_float, as_int, ensure_dir, read_csv_dicts, write_csv_dicts, write_json
from .metrics import AUTHOR_INDEX_FIELDS, assign_iupv_percentiles, g_index, h_index, i10_index, lrdi
from .ranking import CORE_METRICS, EXPERIMENTAL_METRICS, METRICS
from .stats import spearman_from_ranks, top_n_overlap

THEORY_METRICS = (*CORE_METRICS, *EXPERIMENTAL_METRICS)
ROBUSTNESS_METRICS = ("c", "c_frac", "h", "g", "islv", "lrdi")

SENSITIVITY_FIELDS = [
    "experiment",
    "fraction_mode",
    "metric_name",
    "n_authors",
    "spearman_vs_base",
    "top20_retention",
    "median_abs_rank_delta",
    "p90_abs_rank_delta",
    "share_abs_rank_delta_le_5",
    "mean_abs_score_delta",
]


def analyze_theory(
    author_work_path: str | Path = "data/marts/author_work_metrics.csv",
    indices_path: str | Path = "data/results/author_indices.csv",
    out_json: str | Path = "data/results/theory_validation.json",
    out_dir: str | Path = "data/results",
    n0: float = 5.0,
    lam: float = 0.35,
    lrdi_p0: float = 5.0,
    lrdi_lambda: float = 0.15,
    analysis_year: int = 2026,
    default_mode: str = "strict_authors_count",
) -> dict[str, Any]:
    ensure_dir(out_dir)
    awm = read_csv_dicts(author_work_path)
    indices = read_csv_dicts(indices_path)

    top1_rows, top1_summary = _top1_sensitivity(awm, n0=n0, lam=lam, lrdi_p0=lrdi_p0, lrdi_lambda=lrdi_lambda, analysis_year=analysis_year)
    mode_rows, mode_summary = _fraction_mode_sensitivity(indices)
    concentration = _concentration_summary(indices)
    convergence = _prefix_convergence(awm, default_mode=default_mode, n0=n0, lam=lam, lrdi_p0=lrdi_p0, lrdi_lambda=lrdi_lambda, analysis_year=analysis_year)
    iupv_checks = _iupv_checks(indices)
    islv_checks = _islv_checks(indices)

    write_csv_dicts(Path(out_dir) / "theory_top1_sensitivity.csv", top1_rows, SENSITIVITY_FIELDS)
    write_csv_dicts(Path(out_dir) / "theory_fraction_mode_sensitivity.csv", mode_rows, SENSITIVITY_FIELDS)

    result = {
        "theory_version": "islv_v1_local_balanced_index",
        "default_fraction_mode": default_mode,
        "core_metrics": list(CORE_METRICS),
        "experimental_metrics": list(EXPERIMENTAL_METRICS),
        "iupv_parameters": {
            "formula": "100 * (pr(P) * pr(h) * pr(C_frac)) ** (1/3)",
            "percentile_scope": "current_slice_and_fraction_mode",
            "legacy_n0_lambda_ignored": {"n0": n0, "lambda": lam},
        },
        "islv_parameters": {
            "formula": "100 * weighted_geometric_mean(pr(h), pr(C_frac), pr(g), pr(i10), pr(P)) * concentration_penalty(top1_share)",
            "weights": {"h": 0.35, "c_frac": 0.30, "g": 0.20, "i10": 0.10, "p": 0.05},
            "concentration_penalty": "1 - 0.30 * max(0, top1_share - 0.50)",
            "percentile_scope": "current_slice_and_fraction_mode",
        },
        "lrdi_parameters": {"p0": lrdi_p0, "lambda": lrdi_lambda, "analysis_year": analysis_year},
        "iupv_property_checks": iupv_checks,
        "islv_property_checks": islv_checks,
        "top1_sensitivity": top1_summary,
        "fraction_mode_sensitivity": mode_summary,
        "metric_concentration": concentration,
        "prefix_convergence": convergence,
        "interpretation_notes": [
            "Top-1 sensitivity removes each author's most cited work and recomputes ranks with zero rows retained for authors left without works.",
            "Fraction-mode sensitivity compares strict authorship credit with integer and renormalized valid-author credit.",
            "Concentration estimates how strongly each metric is dominated by the upper tail of authors.",
            "Prefix convergence compares deterministic work prefixes against the full fetched corpus, not the full OpenAlex subfield.",
            "f5/fm5 are operational threshold metrics in this MVP and require primary-source confirmation before dissertation use as Polyanin indices.",
        ],
    }
    write_json(out_json, result)
    return result


def _top1_sensitivity(
    awm: list[dict[str, str]],
    n0: float,
    lam: float,
    lrdi_p0: float,
    lrdi_lambda: float,
    analysis_year: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    modes = sorted({row["fraction_mode"] for row in awm})
    for mode in modes:
        mode_rows = [row for row in awm if row["fraction_mode"] == mode]
        base = _compute_indices_from_awm(mode_rows, mode, n0=n0, lam=lam, lrdi_p0=lrdi_p0, lrdi_lambda=lrdi_lambda, analysis_year=analysis_year)
        trimmed = _remove_top1_per_author(mode_rows)
        after = _compute_indices_from_awm(trimmed, mode, n0=n0, lam=lam, lrdi_p0=lrdi_p0, lrdi_lambda=lrdi_lambda, analysis_year=analysis_year, author_template=base)
        summary[mode] = {}
        for metric in ROBUSTNESS_METRICS:
            report = _compare_index_sets(base, after, metric)
            row = {"experiment": "remove_top1_per_author", "fraction_mode": mode, "metric_name": metric, **report}
            rows_out.append(row)
            summary[mode][metric] = report
    return rows_out, summary


def _fraction_mode_sensitivity(indices: list[dict[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    strict = [row for row in indices if row["fraction_mode"] == "strict_authors_count"]
    if not strict:
        return rows_out, summary
    modes = sorted({row["fraction_mode"] for row in indices if row["fraction_mode"] != "strict_authors_count"})
    for mode in modes:
        mode_rows = [row for row in indices if row["fraction_mode"] == mode]
        summary[mode] = {}
        for metric in ROBUSTNESS_METRICS:
            report = _compare_index_sets(strict, mode_rows, metric)
            row = {"experiment": f"fraction_mode_{mode}_vs_strict", "fraction_mode": mode, "metric_name": metric, **report}
            rows_out.append(row)
            summary[mode][metric] = report
    return rows_out, summary


def _prefix_convergence(
    awm: list[dict[str, str]],
    default_mode: str,
    n0: float,
    lam: float,
    lrdi_p0: float,
    lrdi_lambda: float,
    analysis_year: int,
) -> dict[str, Any]:
    mode_rows = [row for row in awm if row["fraction_mode"] == default_mode]
    works = sorted({row["work_id"] for row in mode_rows}, key=lambda work_id: _work_sort_key(mode_rows, work_id))
    total = len(works)
    if total == 0:
        return {"total_works": 0, "prefixes": {}}
    full = _compute_indices_from_awm(mode_rows, default_mode, n0=n0, lam=lam, lrdi_p0=lrdi_p0, lrdi_lambda=lrdi_lambda, analysis_year=analysis_year)
    candidate_prefixes = [100, 250, 500, 1000, 2000, 5000, total]
    prefixes = sorted({n for n in candidate_prefixes if 0 < n <= total})
    result: dict[str, Any] = {
        "total_works_with_valid_authors": total,
        "prefixes": {},
        "note": "Prefixes are built from works that survived author-level cleaning in the selected fraction mode.",
    }
    for prefix in prefixes:
        selected = set(works[:prefix])
        prefix_rows = [row for row in mode_rows if row["work_id"] in selected]
        prefix_indices = _compute_indices_from_awm(prefix_rows, default_mode, n0=n0, lam=lam, lrdi_p0=lrdi_p0, lrdi_lambda=lrdi_lambda, analysis_year=analysis_year)
        metric_reports = {
            metric: _compare_index_sets(full, prefix_indices, metric)
            for metric in ROBUSTNESS_METRICS
        }
        result["prefixes"][str(prefix)] = {
            "n_works": prefix,
            "n_authors": len(prefix_indices),
            "metrics": metric_reports,
        }
    return result


def _work_sort_key(rows: list[dict[str, str]], work_id: str) -> tuple[int, str]:
    for row in rows:
        if row["work_id"] == work_id:
            return (as_int(row.get("publication_year"), 0), work_id)
    return (0, work_id)


def _concentration_summary(indices: list[dict[str, str]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    modes = sorted({row["fraction_mode"] for row in indices})
    for mode in modes:
        mode_rows = [row for row in indices if row["fraction_mode"] == mode]
        result[mode] = {}
        for metric in ("c", "c_frac", "g", "iupv", "islv", "lrdi"):
            values = [max(0.0, as_float(row.get(metric))) for row in mode_rows]
            result[mode][metric] = {
                "gini": _gini(values),
                "top1_percent_share": _top_share(values, 0.01),
                "top5_percent_share": _top_share(values, 0.05),
                "top10_percent_share": _top_share(values, 0.10),
            }
    return result


def _iupv_checks(indices: list[dict[str, str]]) -> dict[str, Any]:
    values = [as_float(row.get("iupv")) for row in indices]
    return {
        "observed_min": min(values) if values else None,
        "observed_max": max(values) if values else None,
        "observed_within_0_100": all(0.0 <= v <= 100.0 for v in values),
        "component_fields": ["p", "h", "c_frac"],
        "formula": "100 * (pr(P) * pr(h) * pr(C_frac)) ** (1/3)",
        "bounded_formula": "0 <= IUPV <= 100 because percentile ranks are in (0, 1].",
        "interpretation": "Geometric mean penalizes one-sided profiles and avoids direct dependence on raw citation scale.",
    }


def _islv_checks(indices: list[dict[str, str]]) -> dict[str, Any]:
    values = [as_float(row.get("islv")) for row in indices]
    return {
        "observed_min": min(values) if values else None,
        "observed_max": max(values) if values else None,
        "observed_within_0_100": all(0.0 <= value <= 100.0 for value in values),
        "component_fields": ["h", "c_frac", "g", "i10", "p", "top1_share"],
        "formula": "100 * G * K_conc",
        "interpretation": "ISLV keeps a balanced local score and reduces the effect of one highly cited work when top1_share exceeds 0.50.",
    }


def _remove_top1_per_author(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    groups: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row["author_id"]].append(row)
    trimmed: list[dict[str, str]] = []
    for group in groups.values():
        ordered = sorted(group, key=lambda row: (-as_int(row["cited_by_count"]), row["work_id"]))
        trimmed.extend(ordered[1:])
    return trimmed


def _compute_indices_from_awm(
    rows: list[dict[str, str]],
    mode: str,
    n0: float,
    lam: float,
    lrdi_p0: float,
    lrdi_lambda: float,
    analysis_year: int,
    author_template: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    groups: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    author_names: dict[str, str] = {}
    if author_template:
        for row in author_template:
            author_names[row["author_id"]] = row.get("author_display_name") or ""
    for row in rows:
        groups[row["author_id"]].append(row)
        if row.get("author_display_name"):
            author_names[row["author_id"]] = row["author_display_name"]

    author_ids = set(groups)
    if author_template:
        author_ids.update(row["author_id"] for row in author_template)

    out: list[dict[str, Any]] = []
    for author_id in sorted(author_ids):
        group = groups.get(author_id, [])
        citations = [as_int(row["cited_by_count"]) for row in group]
        cited_credits = [as_float(row["cited_credit"]) for row in group]
        p = len({row["work_id"] for row in group})
        c = float(sum(citations))
        c_frac = float(sum(cited_credits))
        h = h_index(citations)
        publication_years = [as_int(row.get("publication_year")) for row in group if as_int(row.get("publication_year")) > 0]
        local_age = max(publication_years) - min(publication_years) + 1 if publication_years else 1
        f5_value = _f5(group)
        fm5_value = _fm5(group)
        out.append(
            {
                "run_id": "theory",
                "fraction_mode": mode,
                "author_id": author_id,
                "author_display_name": author_names.get(author_id, ""),
                "p": p,
                "c": c,
                "c_frac": c_frac,
                "cpp": c / p if p else 0.0,
                "h": h,
                "i10": i10_index(citations),
                "g": g_index(citations),
                "m_local": h / max(1, local_age),
                "top1_share": (max(citations) / c) if c > 0 and citations else 0.0,
                "f5": f5_value,
                "fm5": fm5_value,
                "iupv": 0.0,
                "islv": 0.0,
                "lrdi": lrdi(group, analysis_year=analysis_year, p0=lrdi_p0, lam=lrdi_lambda),
                "mean_authors_per_work": _mean([as_float(row["authors_count_used"]) for row in group]),
                "share_single_authored": _mean([1.0 if str(row.get("single_authored_flag")).lower() == "true" else 0.0 for row in group]),
                "n_flagged_works": sum(1 for row in group if str(row.get("qf_any")).lower() == "true"),
                "n_truncated_works": sum(1 for row in group if str(row.get("qf_authorship_truncated")).lower() == "true"),
            }
        )
    assign_iupv_percentiles(out)
    return out


def _compare_index_sets(base: list[dict[str, Any]], after: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    base_scores = {row["author_id"]: as_float(row.get(metric)) for row in base}
    after_scores = {row["author_id"]: as_float(row.get(metric)) for row in after}
    common = sorted(set(base_scores) & set(after_scores))
    base_ranks = _rank_map(base, metric)
    after_ranks = _rank_map(after, metric)
    rank_deltas = [after_ranks[a] - base_ranks[a] for a in common]
    abs_rank_deltas = sorted(abs(delta) for delta in rank_deltas)
    score_deltas = [after_scores[a] - base_scores[a] for a in common]
    n = len(common)
    return {
        "n_authors": n,
        "spearman_vs_base": spearman_from_ranks(base_ranks, after_ranks),
        "top20_retention": top_n_overlap(base_ranks, after_ranks, 20),
        "median_abs_rank_delta": _quantile(abs_rank_deltas, 0.5),
        "p90_abs_rank_delta": _quantile(abs_rank_deltas, 0.9),
        "share_abs_rank_delta_le_5": (sum(1 for value in abs_rank_deltas if value <= 5) / n) if n else None,
        "mean_abs_score_delta": (sum(abs(value) for value in score_deltas) / n) if n else None,
    }


def _rank_map(rows: list[dict[str, Any]], metric: str) -> dict[str, int]:
    ranked = sorted(
        rows,
        key=lambda row: (
            -as_float(row.get(metric)),
            -as_float(row.get("c")),
            -as_int(row.get("p")),
            row.get("author_id") or "",
        ),
    )
    return {row["author_id"]: pos for pos, row in enumerate(ranked, start=1)}


def _f5(group: list[dict[str, str]]) -> float:
    return float(sum(1 for row in group if as_int(row["cited_by_count"]) >= 5))


def _fm5(group: list[dict[str, str]]) -> float:
    return float(sum(as_float(row["credit_weight"]) for row in group if as_int(row["cited_by_count"]) >= 5))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _quantile(values: list[float | int], q: float) -> float | None:
    if not values:
        return None
    clean = sorted(float(value) for value in values)
    pos = (len(clean) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return clean[lo]
    frac = pos - lo
    return clean[lo] * (1 - frac) + clean[hi] * frac


def _top_share(values: list[float], share: float) -> float | None:
    if not values:
        return None
    total = sum(values)
    if total <= 0:
        return 0.0
    n = max(1, math.ceil(len(values) * share))
    return sum(sorted(values, reverse=True)[:n]) / total


def _gini(values: list[float]) -> float | None:
    clean = sorted(max(0.0, value) for value in values)
    n = len(clean)
    total = sum(clean)
    if n == 0:
        return None
    if total == 0:
        return 0.0
    weighted = sum((2 * i - n - 1) * value for i, value in enumerate(clean, start=1))
    return weighted / (n * total)
