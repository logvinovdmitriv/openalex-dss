from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .io_utils import as_float, as_int, ensure_dir, read_table_dicts, write_json
from .ranking import METRICS


def analyze_stats(
    indices_path: str | Path = "data/results/author_indices.csv",
    ratings_path: str | Path = "data/results/rating_positions.csv",
    fig_dir: str | Path = "data/results/figures",
    json_out: str | Path = "data/results/stats_summary.json",
    metrics: tuple[str, ...] = METRICS,
) -> dict[str, Any]:
    indices = read_table_dicts(indices_path)
    ratings = read_table_dicts(ratings_path)
    ensure_dir(fig_dir)
    available_metrics = tuple(metric for metric in metrics if any(metric in row for row in indices))

    summary: dict[str, Any] = {"fraction_modes": {}}
    modes = sorted({row["fraction_mode"] for row in indices})
    for mode in modes:
        mode_indices = [row for row in indices if row["fraction_mode"] == mode]
        mode_ratings = [row for row in ratings if row["fraction_mode"] == mode]
        metric_summary = {
            metric: _describe([as_float(row[metric]) for row in mode_indices])
            for metric in available_metrics
        }
        rank_maps = _rank_maps(mode_ratings, available_metrics)
        spearman = _pairwise_spearman(rank_maps, available_metrics)
        kendall = _pairwise_kendall(rank_maps, available_metrics)
        top_overlap = _top_overlap(rank_maps, ns=(10, 20, 50), metrics=available_metrics)
        rank_shift_c_frac = _rank_shift(rank_maps, "c", "c_frac")
        summary["fraction_modes"][mode] = {
            "authors": len(mode_indices),
            "metrics": metric_summary,
            "spearman_on_competition_ranks": spearman,
            "kendall_tau_b_on_competition_ranks": kendall,
            "top_overlap": top_overlap,
            "rank_shift_c_vs_c_frac": rank_shift_c_frac,
        }
        if available_metrics:
            main_metric = "islv" if "islv" in available_metrics else ("iupv" if "iupv" in available_metrics else available_metrics[0])
            _write_distribution_svg(Path(fig_dir) / f"distribution_{main_metric}_{mode}.svg", mode_indices, main_metric)
        _write_heatmap_svg(Path(fig_dir) / f"spearman_heatmap_{mode}.svg", spearman, available_metrics)

    write_json(json_out, summary)
    return summary


def top_n_overlap(rank_a: dict[str, int], rank_b: dict[str, int], n: int) -> float:
    available = min(n, len(rank_a), len(rank_b))
    if available <= 0:
        return 0.0
    top_a = {author for author, _ in sorted(rank_a.items(), key=lambda item: item[1])[:available]}
    top_b = {author for author, _ in sorted(rank_b.items(), key=lambda item: item[1])[:available]}
    return len(top_a & top_b) / float(available)


def spearman_from_ranks(rank_a: dict[str, int], rank_b: dict[str, int]) -> float | None:
    authors = sorted(set(rank_a) & set(rank_b))
    n = len(authors)
    if n < 2:
        return None
    xs = [float(rank_a[a]) for a in authors]
    ys = [float(rank_b[a]) for a in authors]
    return _pearson(xs, ys)


def kendall_tau_b_from_ranks(rank_a: dict[str, int], rank_b: dict[str, int]) -> float | None:
    authors = sorted(set(rank_a) & set(rank_b))
    n = len(authors)
    if n < 2:
        return None
    concordant = discordant = ties_a = ties_b = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            da = rank_a[authors[i]] - rank_a[authors[j]]
            db = rank_b[authors[i]] - rank_b[authors[j]]
            if da == 0 and db == 0:
                continue
            if da == 0:
                ties_a += 1
            elif db == 0:
                ties_b += 1
            elif da * db > 0:
                concordant += 1
            else:
                discordant += 1
    denom = math.sqrt((concordant + discordant + ties_a) * (concordant + discordant + ties_b))
    if denom == 0:
        return None
    return (concordant - discordant) / denom


def _rank_maps(ratings: list[dict[str, str]], metrics: tuple[str, ...] = METRICS) -> dict[str, dict[str, int]]:
    maps: dict[str, dict[str, int]] = {metric: {} for metric in metrics}
    for row in ratings:
        metric = row["metric_name"]
        if metric in maps:
            maps[metric][row["author_id"]] = as_int(row["rank_competition"])
    return maps


def _pairwise_spearman(rank_maps: dict[str, dict[str, int]], metrics: tuple[str, ...] = METRICS) -> dict[str, dict[str, float | None]]:
    return {
        a: {b: spearman_from_ranks(rank_maps[a], rank_maps[b]) for b in metrics}
        for a in metrics
    }


def _pairwise_kendall(rank_maps: dict[str, dict[str, int]], metrics: tuple[str, ...] = METRICS) -> dict[str, dict[str, float | None]]:
    return {
        a: {b: kendall_tau_b_from_ranks(rank_maps[a], rank_maps[b]) for b in metrics}
        for a in metrics
    }


def _top_overlap(rank_maps: dict[str, dict[str, int]], ns: tuple[int, ...], metrics: tuple[str, ...] = METRICS) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for n in ns:
        result[str(n)] = {
            a: {b: top_n_overlap(rank_maps[a], rank_maps[b], n) for b in metrics}
            for a in metrics
        }
    return result


def _describe(values: list[float]) -> dict[str, float | int | None]:
    clean = sorted(v for v in values if math.isfinite(v))
    n = len(clean)
    if n == 0:
        return {"n": 0, "min": None, "max": None, "mean": None, "median": None}
    mean = sum(clean) / n
    variance = sum((value - mean) ** 2 for value in clean) / (n - 1) if n > 1 else 0.0
    stddev = math.sqrt(variance)
    unique_values = len(set(clean))
    skewness = None
    if n > 2 and stddev > 0:
        skewness = sum(((value - mean) / stddev) ** 3 for value in clean) / n
    q1 = _quantile(clean, 0.25)
    q3 = _quantile(clean, 0.75)
    return {
        "n": n,
        "min": clean[0],
        "max": clean[-1],
        "mean": mean,
        "stddev": stddev,
        "coefficient_of_variation": (stddev / mean) if mean else None,
        "skewness": skewness,
        "p10": _quantile(clean, 0.10),
        "q1": q1,
        "p25": q1,
        "median": _quantile(clean, 0.5),
        "p50": _quantile(clean, 0.5),
        "p75": q3,
        "p90": _quantile(clean, 0.9),
        "p95": _quantile(clean, 0.95),
        "p99": _quantile(clean, 0.99),
        "q3": q3,
        "iqr": q3 - q1,
        "zero_rate": sum(1 for value in clean if value == 0) / n,
        "tie_rate": 1.0 - (unique_values / n),
    }


def _rank_shift(rank_maps: dict[str, dict[str, int]], a: str, b: str) -> dict[str, Any]:
    if a not in rank_maps or b not in rank_maps:
        return {}
    authors = sorted(set(rank_maps[a]) & set(rank_maps[b]))
    deltas = sorted(abs(rank_maps[b][author] - rank_maps[a][author]) for author in authors)
    n = len(deltas)
    return {
        "n_authors": n,
        "median_abs_delta": _quantile(deltas, 0.5) if deltas else None,
        "p90_abs_delta": _quantile(deltas, 0.9) if deltas else None,
        "share_abs_delta_le_5": (sum(1 for value in deltas if value <= 5) / n) if n else None,
    }


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    pos = (len(values) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return values[lo]
    frac = pos - lo
    return values[lo] * (1 - frac) + values[hi] * frac


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    sx = math.sqrt(sum(x * x for x in dx))
    sy = math.sqrt(sum(y * y for y in dy))
    if sx == 0 or sy == 0:
        return None
    return sum(x * y for x, y in zip(dx, dy)) / (sx * sy)


def _write_distribution_svg(path: Path, rows: list[dict[str, str]], metric: str) -> None:
    values = [math.log1p(max(0.0, as_float(row[metric]))) for row in rows]
    bins = [0] * 12
    if values:
        lo, hi = min(values), max(values)
        span = hi - lo or 1.0
        for value in values:
            idx = min(len(bins) - 1, int((value - lo) / span * len(bins)))
            bins[idx] += 1
    max_count = max(bins) if bins else 1
    width, height = 640, 360
    margin = 40
    bar_w = (width - 2 * margin) / len(bins)
    bars = []
    for i, count in enumerate(bins):
        bar_h = 0 if max_count == 0 else (height - 2 * margin) * count / max_count
        x = margin + i * bar_w
        y = height - margin - bar_h
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w - 3:.1f}" height="{bar_h:.1f}" fill="#3b7ea1"/>')
    path.write_text(
        "\n".join(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">',
                f'<text x="40" y="26" font-family="Arial" font-size="18">log1p({metric}) distribution</text>',
                *bars,
                '<line x1="40" y1="320" x2="600" y2="320" stroke="#222"/>',
                "</svg>",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_heatmap_svg(path: Path, matrix: dict[str, dict[str, float | None]], metrics: tuple[str, ...] = METRICS) -> None:
    cell = 48
    margin = 100
    size = margin + cell * max(1, len(metrics)) + 20
    items = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">',
        '<text x="20" y="28" font-family="Arial" font-size="18">Spearman heatmap</text>',
    ]
    for i, a in enumerate(metrics):
        items.append(f'<text x="{margin + i * cell + 10}" y="{margin - 10}" font-family="Arial" font-size="10">{a}</text>')
        items.append(f'<text x="20" y="{margin + i * cell + 29}" font-family="Arial" font-size="10">{a}</text>')
        for j, b in enumerate(metrics):
            value = matrix.get(a, {}).get(b)
            color = _corr_color(value)
            x = margin + j * cell
            y = margin + i * cell
            label = "" if value is None else f"{value:.2f}"
            items.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{color}" stroke="#fff"/>')
            items.append(f'<text x="{x + 8}" y="{y + 28}" font-family="Arial" font-size="10">{label}</text>')
    items.append("</svg>")
    path.write_text("\n".join(items) + "\n", encoding="utf-8")


def _corr_color(value: float | None) -> str:
    if value is None:
        return "#eeeeee"
    value = max(-1.0, min(1.0, value))
    if value >= 0:
        level = int(255 - value * 155)
        return f"rgb({level},{level},255)"
    level = int(255 + value * 155)
    return f"rgb(255,{level},{level})"
