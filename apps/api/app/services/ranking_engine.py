from __future__ import annotations

import sys
from typing import Any

from app.core.paths import SRC

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_dss.ranking import sort_metric_rows


def build_metric_ranking_rows(
    rows: list[dict[str, Any]],
    metric: str,
    visible_metrics: list[str],
    *,
    limit: int,
    max_limit: int,
    direction: str = "desc",
) -> tuple[list[dict[str, Any]], int]:
    ranked: list[dict[str, Any]] = []
    sorted_rows = sort_metric_rows(rows, metric)
    if str(direction or "desc").strip().lower() == "asc":
        sorted_rows = list(reversed(sorted_rows))
    for row in sorted_rows:
        item = {
            "author_id": row["author_id"],
            "author_display_name": row["author_display_name"],
            "score": _as_float(row.get(metric)),
        }
        for field in visible_metrics:
            item[field] = row.get(field)
        ranked.append(item)
    assign_competition_rank(ranked, "score", "rank_competition")
    requested_limit = max(0, min(int(limit or 0), max(1, int(max_limit))))
    visible_rows = ranked if requested_limit <= 0 else ranked[:requested_limit]
    return visible_rows, len(ranked)


def assign_competition_rank(rows: list[dict[str, Any]], score_field: str, rank_field: str) -> None:
    previous_score: float | None = None
    previous_rank = 0
    for index, row in enumerate(rows, start=1):
        score = _as_float(row.get(score_field))
        if previous_score is None or score != previous_score:
            previous_rank = index
            previous_score = score
        row[rank_field] = previous_rank


def _as_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return number
