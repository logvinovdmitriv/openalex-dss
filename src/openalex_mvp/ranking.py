from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .io_utils import as_float, as_int, read_table_dicts, write_csv_dicts, write_parquet_dicts

CORE_METRICS = ("p", "c", "c_frac", "cpp", "h", "i10", "g", "m_local")
EXPERIMENTAL_METRICS = ("f5", "fm5", "iupv", "islv", "lrdi")
METRICS = (*CORE_METRICS, *EXPERIMENTAL_METRICS)
DEFAULT_TIE_BREAKERS = ("c", "p", "author_id")

RATING_FIELDS = [
    "run_id",
    "fraction_mode",
    "metric_name",
    "author_id",
    "author_display_name",
    "score",
    "rank_competition",
    "rank_dense",
    "tie_break_c",
    "tie_break_p",
    "tie_break_author_id",
]


def build_ratings(
    indices_path: str | Path = "data/runs/local/tables/indices.csv",
    out_path: str | Path = "data/runs/local/tables/ratings.csv",
    metrics: tuple[str, ...] = METRICS,
) -> list[dict[str, Any]]:
    rows = read_table_dicts(indices_path)
    by_run_mode: defaultdict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_run_mode[(row["run_id"], row["fraction_mode"])].append(row)

    out_rows: list[dict[str, Any]] = []
    for (run_id, mode), group in by_run_mode.items():
        for metric in metrics:
            ranked = sort_metric_rows(group, metric)
            previous_score = None
            competition_rank = 0
            dense_rank = 0
            for pos, row in enumerate(ranked, start=1):
                score = as_float(row.get(metric))
                if previous_score is None or score != previous_score:
                    competition_rank = pos
                    dense_rank += 1
                    previous_score = score
                out_rows.append(
                    {
                        "run_id": run_id,
                        "fraction_mode": mode,
                        "metric_name": metric,
                        "author_id": row["author_id"],
                        "author_display_name": row.get("author_display_name"),
                        "score": score,
                        "rank_competition": competition_rank,
                        "rank_dense": dense_rank,
                        "tie_break_c": as_float(row.get("c")),
                        "tie_break_p": as_int(row.get("p")),
                        "tie_break_author_id": row["author_id"],
                    }
                )

    out_rows.sort(key=lambda row: (row["fraction_mode"], row["metric_name"], int(row["rank_competition"]), row["author_id"]))
    write_csv_dicts(out_path, out_rows, RATING_FIELDS)
    write_parquet_dicts(Path(out_path).with_suffix(".parquet"), out_rows, RATING_FIELDS)
    return out_rows


def sort_metric_rows(rows: list[dict[str, Any]], metric: str) -> list[dict[str, Any]]:
    """Sort author metric rows with the single reproducible ranking profile.

    The same rule is used by generated `ratings.csv` and by the
    interactive API views, so equal metric values resolve identically across
    exports and UI.
    """
    return sorted(rows, key=lambda row: ranking_sort_key(row, metric))


def ranking_sort_key(row: dict[str, Any], metric: str) -> tuple[float, float, int, str]:
    return (
        -as_float(row.get(metric)),
        -as_float(row.get("c")),
        -as_int(row.get("p")),
        str(row.get("author_id") or ""),
    )
