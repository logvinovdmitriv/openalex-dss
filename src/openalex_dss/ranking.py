from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .duckdb_io import copy_query, sql_literal, table_expression
from .io_utils import as_float, as_int, read_table_dicts, write_csv_dicts, write_parquet_dicts

CORE_METRICS = ("p", "c", "c_frac", "h", "i10", "g")
SUPPORT_METRICS = ("cpp", "m_local", "top1_share", "rfi_log_frac")
EXPERIMENTAL_METRICS = ("f5", "fm5", "pci", "iupv", "iupv_s", "iupv_sb", "islv", "lrdi")
METRICS = (*CORE_METRICS, *SUPPORT_METRICS, *EXPERIMENTAL_METRICS)
DEFAULT_TIE_BREAKERS = ("c", "p", "author_id")

RATING_FIELDS = [
    "run_id",
    "fraction_mode",
    "metric_name",
    "author_id",
    "author_display_name",
    "score",
    "position",
    "rank_ordinal",
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
    *,
    return_rows: bool = True,
) -> list[dict[str, Any]]:
    if not return_rows:
        try:
            _build_ratings_duckdb(indices_path, out_path, metrics)
        except ImportError:
            _build_ratings_python(indices_path, out_path, metrics)
        return []
    return _build_ratings_python(indices_path, out_path, metrics)


def _build_ratings_python(
    indices_path: str | Path,
    out_path: str | Path,
    metrics: tuple[str, ...],
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
                        "position": pos,
                        "rank_ordinal": pos,
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


def _build_ratings_duckdb(
    indices_path: str | Path,
    out_path: str | Path,
    metrics: tuple[str, ...],
) -> None:
    if not metrics:
        write_csv_dicts(out_path, [], RATING_FIELDS)
        write_parquet_dicts(Path(out_path).with_suffix(".parquet"), [], RATING_FIELDS)
        return
    relation = table_expression(indices_path)
    metric_parts = [
        f"""
        SELECT
            CAST(run_id AS VARCHAR) AS run_id,
            CAST(fraction_mode AS VARCHAR) AS fraction_mode,
            {sql_literal(metric)} AS metric_name,
            CAST(author_id AS VARCHAR) AS author_id,
            CAST(author_display_name AS VARCHAR) AS author_display_name,
            COALESCE(TRY_CAST({metric} AS DOUBLE), 0.0) AS score,
            COALESCE(TRY_CAST(c AS DOUBLE), 0.0) AS tie_break_c,
            COALESCE(TRY_CAST(p AS BIGINT), 0) AS tie_break_p,
            CAST(author_id AS VARCHAR) AS tie_break_author_id
        FROM {relation}
        """
        for metric in metrics
    ]
    query = f"""
WITH metric_rows AS (
    {" UNION ALL ".join(metric_parts)}
),
ranked AS (
    SELECT
        *,
        RANK() OVER (
            PARTITION BY run_id, fraction_mode, metric_name
            ORDER BY score DESC
        ) AS rank_competition,
        DENSE_RANK() OVER (
            PARTITION BY run_id, fraction_mode, metric_name
            ORDER BY score DESC
        ) AS rank_dense,
        ROW_NUMBER() OVER (
            PARTITION BY run_id, fraction_mode, metric_name
            ORDER BY score DESC, tie_break_c DESC, tie_break_p DESC, author_id ASC
        ) AS position,
        ROW_NUMBER() OVER (
            PARTITION BY run_id, fraction_mode, metric_name
            ORDER BY score DESC, tie_break_c DESC, tie_break_p DESC, author_id ASC
        ) AS rank_ordinal
    FROM metric_rows
)
SELECT {", ".join(RATING_FIELDS)}
FROM ranked
ORDER BY fraction_mode, metric_name, position
"""
    copy_query(query, out_path, Path(out_path).with_suffix(".parquet"))


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
