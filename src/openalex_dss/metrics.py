from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .duckdb_io import copy_query, iter_query, sql_literal, table_expression
from .io_utils import as_float, as_int, read_table_dicts, truthy, write_csv_dicts, write_parquet_dicts
from .normalize import DELETED_AUTHOR_ID, NULL_AUTHOR_ID

AUTHOR_WORK_FIELDS = [
    "run_id",
    "fraction_mode",
    "work_id",
    "author_id",
    "author_display_name",
    "publication_year",
    "cited_by_count",
    "authors_count_used",
    "actual_authors_count",
    "authors_count_reported",
    "credit_weight",
    "cited_credit",
    "single_authored_flag",
    "qf_any",
    "qf_authorship_truncated",
    "qf_author_omission",
    "omitted_author_fraction",
]

AUTHOR_INDEX_FIELDS = [
    "run_id",
    "fraction_mode",
    "author_id",
    "author_display_name",
    "p",
    "c",
    "c_frac",
    "cpp",
    "h",
    "i10",
    "g",
    "m_local",
    "top1_share",
    "f5",
    "fm5",
    "pci",
    "iupv",
    "islv",
    "lrdi",
    "mean_authors_per_work",
    "share_single_authored",
    "n_flagged_works",
    "n_truncated_works",
]

def h_index(citations: list[int]) -> int:
    c = sorted((max(0, int(x)) for x in citations), reverse=True)
    h = 0
    for i, value in enumerate(c, start=1):
        if value >= i:
            h = i
        else:
            break
    return h


def i10_index(citations: list[int]) -> int:
    return sum(1 for value in citations if int(value) >= 10)


def g_index(citations: list[int]) -> int:
    c = sorted((max(0, int(x)) for x in citations), reverse=True)
    total = 0
    g = 0
    for i, value in enumerate(c, start=1):
        total += value
        if total >= i * i:
            g = i
    return g


def iupv_from_percentiles(p_pr: float, h_pr: float, c_frac_pr: float) -> float:
    """Rating formula: geometric mean of percentile ranks for P, h and C_frac."""
    if p_pr <= 0 or h_pr <= 0 or c_frac_pr <= 0:
        return 0.0
    return 100.0 * (max(1e-6, p_pr) * max(1e-6, h_pr) * max(1e-6, c_frac_pr)) ** (1.0 / 3.0)


def islv_from_percentiles(
    h_pr: float,
    c_frac_pr: float,
    g_pr: float,
    i10_pr: float,
    p_pr: float,
    top1_share: float,
    *,
    epsilon: float = 0.01,
    tau: float = 0.50,
    penalty_lambda: float = 0.30,
) -> float:
    """Balanced contribution rating with top-1 concentration penalty."""
    def component(value: float) -> float:
        return min(1.0, max(0.0, value) + epsilon)

    weights = (
        (component(h_pr), 0.35),
        (component(c_frac_pr), 0.30),
        (component(g_pr), 0.20),
        (component(i10_pr), 0.10),
        (component(p_pr), 0.05),
    )
    weight_sum = sum(weight for _, weight in weights)
    geometric = math.prod(value**weight for value, weight in weights) ** (1.0 / weight_sum)
    concentration_penalty = 1.0 - penalty_lambda * max(0.0, min(1.0, top1_share) - tau)
    return 100.0 * geometric * max(0.0, min(1.0, concentration_penalty))


def assign_iupv_percentiles(rows: list[dict[str, Any]], group_field: str = "fraction_mode") -> None:
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(group_field) or "")].append(row)

    for group in groups.values():
        percentile_maps = {
            field: _percentile_rank_map(group, field)
            for field in ("p", "h", "c_frac", "g", "i10")
        }
        for row in group:
            if as_float(row.get("p")) <= 0 or as_float(row.get("h")) <= 0 or as_float(row.get("c_frac")) <= 0:
                row["pci"] = 0.0
                row["iupv"] = 0.0
            else:
                row["pci"] = iupv_from_percentiles(
                    percentile_maps["p"][id(row)],
                    percentile_maps["h"][id(row)],
                    percentile_maps["c_frac"][id(row)],
                )
                row["iupv"] = row["pci"]
            row["islv"] = islv_from_percentiles(
                percentile_maps["h"][id(row)],
                percentile_maps["c_frac"][id(row)],
                percentile_maps["g"][id(row)],
                percentile_maps["i10"][id(row)],
                percentile_maps["p"][id(row)],
                as_float(row.get("top1_share")),
            )


def lrdi(
    rows: list[dict[str, str]],
    *,
    analysis_year: int = 2026,
    p0: float = 5.0,
    lam: float = 0.15,
) -> float:
    p = len({row["work_id"] for row in rows})
    if p <= 0:
        return 0.0
    shrinkage = p / (p + p0)
    total = 0.0
    for row in rows:
        citations = max(0.0, as_float(row.get("cited_by_count")))
        denom = max(1.0, as_float(row.get("authors_count_used")))
        year = as_int(row.get("publication_year"))
        age = max(0, analysis_year - year) if year else 0
        total += (math.log1p(citations) / denom) * math.exp(-lam * age)
    return shrinkage * total


def build_author_work_metrics(
    works_path: str | Path = "data/tables/local/works.parquet",
    authorships_path: str | Path = "data/tables/local/authorships.parquet",
    out_path: str | Path = "data/runs/local/tables/author_work.csv",
    fraction_modes: tuple[str, ...] = ("strict_authors_count", "renorm_valid_authors", "integer"),
    run_id: str = "base",
    *,
    return_rows: bool = True,
    exclude_retracted: bool = True,
    exclude_paratext: bool = True,
    include_xpac: bool = False,
    work_types: tuple[str, ...] = (),
    from_publication_date: str = "",
    to_publication_date: str = "",
) -> list[dict[str, Any]]:
    if not return_rows:
        try:
            _build_author_work_metrics_duckdb(
                works_path,
                authorships_path,
                out_path,
                fraction_modes,
                run_id,
                exclude_retracted=exclude_retracted,
                exclude_paratext=exclude_paratext,
                include_xpac=include_xpac,
                work_types=work_types,
                from_publication_date=from_publication_date,
                to_publication_date=to_publication_date,
            )
            return []
        except ImportError:
            _build_author_work_metrics_python(
                works_path,
                authorships_path,
                out_path,
                fraction_modes,
                run_id,
                exclude_retracted=exclude_retracted,
                exclude_paratext=exclude_paratext,
                include_xpac=include_xpac,
                work_types=work_types,
                from_publication_date=from_publication_date,
                to_publication_date=to_publication_date,
            )
            return []
    return _build_author_work_metrics_python(
        works_path,
        authorships_path,
        out_path,
        fraction_modes,
        run_id,
        exclude_retracted=exclude_retracted,
        exclude_paratext=exclude_paratext,
        include_xpac=include_xpac,
        work_types=work_types,
        from_publication_date=from_publication_date,
        to_publication_date=to_publication_date,
    )


def _build_author_work_metrics_python(
    works_path: str | Path,
    authorships_path: str | Path,
    out_path: str | Path,
    fraction_modes: tuple[str, ...],
    run_id: str,
    *,
    exclude_retracted: bool,
    exclude_paratext: bool,
    include_xpac: bool,
    work_types: tuple[str, ...],
    from_publication_date: str,
    to_publication_date: str,
) -> list[dict[str, Any]]:
    works = {row["work_id"]: row for row in read_table_dicts(works_path)}
    authorships = read_table_dicts(authorships_path)
    rows: list[dict[str, Any]] = []
    seen_work_author: set[tuple[str, str]] = set()

    for auth in authorships:
        work_id = auth["work_id"]
        work = works.get(work_id)
        if not work:
            continue
        if _excluded_work(
            work,
            exclude_retracted=exclude_retracted,
            exclude_paratext=exclude_paratext,
            include_xpac=include_xpac,
            work_types=work_types,
            from_publication_date=from_publication_date,
            to_publication_date=to_publication_date,
        ):
            continue
        author_id = auth.get("author_id")
        if not author_id or author_id in {NULL_AUTHOR_ID, DELETED_AUTHOR_ID}:
            continue
        key = (work_id, author_id)
        if key in seen_work_author:
            continue
        seen_work_author.add(key)

        cited_by_count = as_int(work.get("cited_by_count"))
        raw_count = as_int(auth.get("authorships_count_raw"))
        reported_count = as_int(auth.get("authors_count_reported") or work.get("authors_count_reported") or raw_count)
        actual_count = reported_count or raw_count
        valid_count = as_int(auth.get("valid_author_ids_count"))
        is_truncated = truthy(auth.get("qf_authorship_truncated"))
        author_count_mismatch = truthy(auth.get("qf_author_count_mismatch")) or bool(reported_count and raw_count and reported_count != raw_count)
        qf_any = any(
            truthy(auth.get(flag))
            for flag in [
                "qf_null_author_id",
                "qf_deleted_author_id",
                "qf_duplicate_authorship",
                "qf_authorship_truncated",
                "qf_author_count_mismatch",
                "qf_missing_primary_topic",
            ]
        )

        for mode in fraction_modes:
            denom = _denominator(mode, raw_count, valid_count, reported_count)
            if denom <= 0:
                continue
            credit = 1.0 / denom
            omitted = None
            if mode == "strict_authors_count" and raw_count > 0:
                omitted = max(0.0, 1.0 - (valid_count / max(1, actual_count)))
            rows.append(
                {
                    "run_id": run_id,
                    "fraction_mode": mode,
                    "work_id": work_id,
                    "author_id": author_id,
                    "author_display_name": auth.get("author_display_name"),
                    "publication_year": work.get("publication_year"),
                    "cited_by_count": cited_by_count,
                    "authors_count_used": denom,
                    "actual_authors_count": actual_count,
                    "authors_count_reported": reported_count,
                    "credit_weight": credit,
                    "cited_credit": cited_by_count * credit,
                    "single_authored_flag": actual_count == 1,
                    "qf_any": qf_any,
                    "qf_authorship_truncated": is_truncated or bool(reported_count and reported_count > raw_count),
                    "qf_author_omission": bool(omitted and omitted > 0) or author_count_mismatch,
                    "omitted_author_fraction": omitted,
                }
            )

    rows.sort(key=lambda row: (row["fraction_mode"], row["author_id"], row["work_id"]))
    write_csv_dicts(out_path, rows, AUTHOR_WORK_FIELDS)
    write_parquet_dicts(Path(out_path).with_suffix(".parquet"), rows, AUTHOR_WORK_FIELDS)
    return rows


def _build_author_work_metrics_duckdb(
    works_path: str | Path,
    authorships_path: str | Path,
    out_path: str | Path,
    fraction_modes: tuple[str, ...],
    run_id: str,
    *,
    exclude_retracted: bool,
    exclude_paratext: bool,
    include_xpac: bool,
    work_types: tuple[str, ...],
    from_publication_date: str,
    to_publication_date: str,
) -> None:
    if not fraction_modes:
        write_csv_dicts(out_path, [], AUTHOR_WORK_FIELDS)
        write_parquet_dicts(Path(out_path).with_suffix(".parquet"), [], AUTHOR_WORK_FIELDS)
        return
    query = _author_work_query(
        works_path,
        authorships_path,
        fraction_modes,
        run_id,
        exclude_retracted=exclude_retracted,
        exclude_paratext=exclude_paratext,
        include_xpac=include_xpac,
        work_types=work_types,
        from_publication_date=from_publication_date,
        to_publication_date=to_publication_date,
    )
    copy_query(query, out_path, Path(out_path).with_suffix(".parquet"))


def _author_work_query(
    works_path: str | Path,
    authorships_path: str | Path,
    fraction_modes: tuple[str, ...],
    run_id: str,
    *,
    exclude_retracted: bool,
    exclude_paratext: bool,
    include_xpac: bool,
    work_types: tuple[str, ...],
    from_publication_date: str,
    to_publication_date: str,
) -> str:
    works = table_expression(works_path)
    authorships = table_expression(authorships_path)
    works_fields = _table_fields(works_path)
    authorship_fields = _table_fields(authorships_path)
    reported_expr = _coalesce_sql(
        [
            _try_cast_sql("a.authors_count_reported", authorship_fields, "authors_count_reported"),
            _try_cast_sql("w.authors_count_reported", works_fields, "authors_count_reported"),
            _try_cast_sql("a.authorships_count_raw", authorship_fields, "authorships_count_raw"),
        ],
        "0.0",
    )
    qf_author_count_mismatch_expr = _truthy_sql("a.qf_author_count_mismatch") if "qf_author_count_mismatch" in authorship_fields else "false"
    missing_topic_expr = (
        _truthy_sql("a.qf_missing_primary_topic")
        if "qf_missing_primary_topic" in authorship_fields
        else (_truthy_sql("a.qf_missing_required_fields") if "qf_missing_required_fields" in authorship_fields else "false")
    )
    union_parts = [_author_work_mode_query(mode, run_id) for mode in fraction_modes]
    return f"""
WITH joined AS (
    SELECT
        CAST(a.work_id AS VARCHAR) AS work_id,
        COALESCE(TRY_CAST(a.author_seq AS BIGINT), 9223372036854775807) AS author_seq_sort,
        CAST(a.author_seq AS VARCHAR) AS author_seq_text,
        NULLIF(CAST(a.author_id AS VARCHAR), '') AS author_id,
        CAST(a.author_display_name AS VARCHAR) AS author_display_name,
        CAST(w.publication_year AS VARCHAR) AS publication_year,
        COALESCE(TRY_CAST(w.cited_by_count AS DOUBLE), 0.0) AS cited_by_count,
        COALESCE(TRY_CAST(a.authorships_count_raw AS DOUBLE), 0.0) AS raw_count,
        {reported_expr} AS reported_count,
        COALESCE(TRY_CAST(a.valid_author_ids_count AS DOUBLE), 0.0) AS valid_count,
        {_truthy_sql("a.qf_authorship_truncated")} AS is_truncated,
        {qf_author_count_mismatch_expr} AS qf_author_count_mismatch,
        (
            {_truthy_sql("a.qf_null_author_id")}
            OR {_truthy_sql("a.qf_deleted_author_id")}
            OR {_truthy_sql("a.qf_duplicate_authorship")}
            OR {_truthy_sql("a.qf_authorship_truncated")}
            OR {qf_author_count_mismatch_expr}
            OR {missing_topic_expr}
        ) AS qf_any
    FROM {authorships} AS a
    INNER JOIN {works} AS w ON CAST(a.work_id AS VARCHAR) = CAST(w.work_id AS VARCHAR)
    WHERE NULLIF(CAST(a.author_id AS VARCHAR), '') IS NOT NULL
      AND CAST(a.author_id AS VARCHAR) NOT IN ({sql_literal(NULL_AUTHOR_ID)}, {sql_literal(DELETED_AUTHOR_ID)})
      {_work_exclusion_sql(
          works_fields,
          exclude_retracted=exclude_retracted,
          exclude_paratext=exclude_paratext,
          include_xpac=include_xpac,
          work_types=work_types,
          from_publication_date=from_publication_date,
          to_publication_date=to_publication_date,
      )}
),
dedup AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY work_id, author_id
            ORDER BY author_seq_sort, author_seq_text
        ) AS rn
    FROM joined
),
base AS (
    SELECT * FROM dedup WHERE rn = 1
)
SELECT {", ".join(AUTHOR_WORK_FIELDS)}
FROM (
    {" UNION ALL ".join(union_parts)}
) AS author_work
ORDER BY fraction_mode, author_id, work_id
"""


def _author_work_mode_query(mode: str, run_id: str) -> str:
    if mode == "strict_authors_count":
        denominator = "reported_count"
        where = "reported_count > 0"
        omitted = "GREATEST(0.0, 1.0 - (valid_count / NULLIF(reported_count, 0)))"
        qf_author_omission = f"({omitted}) > 0 OR qf_author_count_mismatch"
    elif mode == "renorm_valid_authors":
        denominator = "valid_count"
        where = "valid_count > 0"
        omitted = "NULL"
        qf_author_omission = "false"
    elif mode == "integer":
        denominator = "1.0"
        where = "true"
        omitted = "NULL"
        qf_author_omission = "false"
    else:
        raise ValueError(f"Unsupported fraction mode: {mode}")
    return f"""
SELECT
    {sql_literal(run_id)} AS run_id,
    {sql_literal(mode)} AS fraction_mode,
    work_id,
    author_id,
    author_display_name,
    publication_year,
    cited_by_count,
    {denominator} AS authors_count_used,
    reported_count AS actual_authors_count,
    reported_count AS authors_count_reported,
    1.0 / {denominator} AS credit_weight,
    cited_by_count * (1.0 / {denominator}) AS cited_credit,
    reported_count = 1.0 AS single_authored_flag,
    qf_any,
    (is_truncated OR reported_count > raw_count) AS qf_authorship_truncated,
    {qf_author_omission} AS qf_author_omission,
    {omitted} AS omitted_author_fraction
FROM base
WHERE {where}
"""


def _truthy_sql(expression: str) -> str:
    return f"LOWER(COALESCE(CAST({expression} AS VARCHAR), '')) IN ('true', '1', 'yes', 'y')"


def compute_indices(
    author_work_path: str | Path = "data/runs/local/tables/author_work.csv",
    out_path: str | Path = "data/runs/local/tables/indices.csv",
    lrdi_p0: float = 5.0,
    lrdi_lambda: float = 0.15,
    analysis_year: int = 2026,
    *,
    return_rows: bool = True,
) -> list[dict[str, Any]]:
    if not return_rows:
        try:
            out_rows = _compute_indices_streaming(author_work_path, lrdi_p0=lrdi_p0, lrdi_lambda=lrdi_lambda, analysis_year=analysis_year)
        except ImportError:
            out_rows = _compute_indices_python(
                author_work_path,
                out_path,
                lrdi_p0=lrdi_p0,
                lrdi_lambda=lrdi_lambda,
                analysis_year=analysis_year,
            )
            return []
        assign_iupv_percentiles(out_rows)
        out_rows.sort(key=lambda row: (row["fraction_mode"], row["author_id"]))
        write_csv_dicts(out_path, out_rows, AUTHOR_INDEX_FIELDS)
        write_parquet_dicts(Path(out_path).with_suffix(".parquet"), out_rows, AUTHOR_INDEX_FIELDS)
        return []
    return _compute_indices_python(author_work_path, out_path, lrdi_p0=lrdi_p0, lrdi_lambda=lrdi_lambda, analysis_year=analysis_year)


def _compute_indices_python(
    author_work_path: str | Path,
    out_path: str | Path,
    *,
    lrdi_p0: float,
    lrdi_lambda: float,
    analysis_year: int,
) -> list[dict[str, Any]]:
    rows = read_table_dicts(author_work_path)
    groups: defaultdict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[(row["run_id"], row["fraction_mode"], row["author_id"])].append(row)

    out_rows: list[dict[str, Any]] = []
    for (run_id, mode, author_id), group in groups.items():
        group.sort(key=lambda row: row["work_id"])
        out_rows.append(_index_row(run_id, mode, author_id, group, lrdi_p0=lrdi_p0, lrdi_lambda=lrdi_lambda, analysis_year=analysis_year))

    assign_iupv_percentiles(out_rows)
    out_rows.sort(key=lambda row: (row["fraction_mode"], row["author_id"]))
    write_csv_dicts(out_path, out_rows, AUTHOR_INDEX_FIELDS)
    write_parquet_dicts(Path(out_path).with_suffix(".parquet"), out_rows, AUTHOR_INDEX_FIELDS)
    return out_rows


def _compute_indices_streaming(
    author_work_path: str | Path,
    *,
    lrdi_p0: float,
    lrdi_lambda: float,
    analysis_year: int,
) -> list[dict[str, Any]]:
    relation = table_expression(author_work_path)
    query = f"""
SELECT *
FROM {relation}
ORDER BY run_id, fraction_mode, author_id, work_id
"""
    out_rows: list[dict[str, Any]] = []
    current_key: tuple[str, str, str] | None = None
    group: list[dict[str, Any]] = []
    for row in iter_query(query):
        key = (str(row.get("run_id") or ""), str(row.get("fraction_mode") or ""), str(row.get("author_id") or ""))
        if current_key is not None and key != current_key:
            out_rows.append(
                _index_row(
                    current_key[0],
                    current_key[1],
                    current_key[2],
                    group,
                    lrdi_p0=lrdi_p0,
                    lrdi_lambda=lrdi_lambda,
                    analysis_year=analysis_year,
                )
            )
            group = []
        current_key = key
        group.append(row)
    if current_key is not None:
        out_rows.append(
            _index_row(
                current_key[0],
                current_key[1],
                current_key[2],
                group,
                lrdi_p0=lrdi_p0,
                lrdi_lambda=lrdi_lambda,
                analysis_year=analysis_year,
            )
        )
    return out_rows


def _index_row(
    run_id: str,
    mode: str,
    author_id: str,
    group: list[dict[str, Any]],
    *,
    lrdi_p0: float,
    lrdi_lambda: float,
    analysis_year: int,
) -> dict[str, Any]:
    citations = [as_int(row["cited_by_count"]) for row in group]
    cited_credits = [as_float(row["cited_credit"]) for row in group]
    p = len({row["work_id"] for row in group})
    c = float(sum(citations))
    c_frac = float(sum(cited_credits))
    h = h_index(citations)
    i10 = i10_index(citations)
    g = g_index(citations)
    publication_years = [as_int(row.get("publication_year")) for row in group if as_int(row.get("publication_year")) > 0]
    local_age = max(publication_years) - min(publication_years) + 1 if publication_years else 1
    f5_value = _f5(group)
    fm5_value = _fm5(group)
    return {
        "run_id": run_id,
        "fraction_mode": mode,
        "author_id": author_id,
        "author_display_name": _first_nonempty(row.get("author_display_name") for row in group),
        "p": p,
        "c": c,
        "c_frac": c_frac,
        "cpp": c / p if p else 0.0,
        "h": h,
        "i10": i10,
        "g": g,
        "m_local": h / max(1, local_age),
        "top1_share": (max(citations) / c) if c > 0 and citations else 0.0,
        "f5": f5_value,
        "fm5": fm5_value,
        "pci": 0.0,
        "iupv": 0.0,
        "islv": 0.0,
        "lrdi": lrdi(group, analysis_year=analysis_year, p0=lrdi_p0, lam=lrdi_lambda),
        "mean_authors_per_work": sum(_actual_authors_count(row) for row in group) / len(group),
        "share_single_authored": sum(1 for row in group if truthy(row["single_authored_flag"])) / len(group),
        "n_flagged_works": sum(1 for row in group if truthy(row["qf_any"])),
        "n_truncated_works": sum(1 for row in group if truthy(row["qf_authorship_truncated"])),
    }


def _denominator(mode: str, raw_count: int, valid_count: int, reported_count: int = 0) -> int:
    if mode == "strict_authors_count":
        return reported_count or raw_count
    if mode == "renorm_valid_authors":
        return valid_count
    if mode == "integer":
        return 1
    raise ValueError(f"Unsupported fraction mode: {mode}")


def _f5(group: list[dict[str, str]]) -> float:
    return float(sum(1 for row in group if as_int(row["cited_by_count"]) >= 5))


def _fm5(group: list[dict[str, str]]) -> float:
    return float(sum(as_float(row["credit_weight"]) for row in group if as_int(row["cited_by_count"]) >= 5))


def _actual_authors_count(row: dict[str, Any]) -> float:
    value = as_float(row.get("actual_authors_count"))
    if value > 0:
        return value
    reported = as_float(row.get("authors_count_reported"))
    if reported > 0:
        return reported
    return max(1.0, as_float(row.get("authors_count_used")))


def _percentile_rank_map(rows: list[dict[str, Any]], field: str) -> dict[int, float]:
    if not rows:
        return {}
    ordered = sorted(enumerate(rows), key=lambda item: (as_float(item[1].get(field)), str(item[1].get("author_id") or "")))
    result: dict[int, float] = {}
    n = len(ordered)
    pos = 0
    while pos < n:
        end = pos + 1
        value = as_float(ordered[pos][1].get(field))
        while end < n and as_float(ordered[end][1].get(field)) == value:
            end += 1
        average_rank = ((pos + 1) + end) / 2.0
        percentile = max(1e-6, average_rank / n)
        for _, row in ordered[pos:end]:
            result[id(row)] = percentile
        pos = end
    return result


def _first_nonempty(values: Any) -> str | None:
    for value in values:
        if value:
            return str(value)
    return None


def _excluded_work(
    work: dict[str, Any],
    *,
    exclude_retracted: bool,
    exclude_paratext: bool,
    include_xpac: bool,
    work_types: tuple[str, ...] = (),
    from_publication_date: str = "",
    to_publication_date: str = "",
) -> bool:
    work_type = str(work.get("type") or "").strip()
    allowed_types = {str(item).strip() for item in work_types if str(item).strip()}
    publication_date = str(work.get("publication_date") or "").strip()
    return (
        (exclude_retracted and truthy(work.get("is_retracted")))
        or (exclude_paratext and truthy(work.get("is_paratext")))
        or (not include_xpac and truthy(work.get("is_xpac")))
        or (allowed_types and work_type not in allowed_types)
        or (from_publication_date and (not publication_date or publication_date < from_publication_date))
        or (to_publication_date and (not publication_date or publication_date > to_publication_date))
    )


def _work_exclusion_sql(
    fields: set[str],
    *,
    exclude_retracted: bool,
    exclude_paratext: bool,
    include_xpac: bool,
    work_types: tuple[str, ...] = (),
    from_publication_date: str = "",
    to_publication_date: str = "",
) -> str:
    clauses: list[str] = []
    if exclude_retracted and "is_retracted" in fields:
        clauses.append(f"NOT {_truthy_sql('w.is_retracted')}")
    if exclude_paratext and "is_paratext" in fields:
        clauses.append(f"NOT {_truthy_sql('w.is_paratext')}")
    if not include_xpac and "is_xpac" in fields:
        clauses.append(f"NOT {_truthy_sql('w.is_xpac')}")
    allowed_types = tuple(str(item).strip() for item in work_types if str(item).strip())
    if allowed_types and "type" in fields:
        clauses.append("CAST(w.type AS VARCHAR) IN (" + ", ".join(sql_literal(item) for item in allowed_types) + ")")
    if from_publication_date and "publication_date" in fields:
        clauses.append(f"CAST(w.publication_date AS VARCHAR) >= {sql_literal(from_publication_date)}")
    if to_publication_date and "publication_date" in fields:
        clauses.append(f"CAST(w.publication_date AS VARCHAR) <= {sql_literal(to_publication_date)}")
    return "" if not clauses else " AND " + " AND ".join(clauses)


def _table_fields(path: str | Path) -> set[str]:
    p = Path(path)
    try:
        if p.suffix == ".parquet":
            import polars as pl

            return set(pl.read_parquet_schema(p).names())
        import csv

        with p.open("rt", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            return set(next(reader, []))
    except Exception:
        return set()


def _try_cast_sql(reference: str, fields: set[str], field: str) -> str | None:
    return f"TRY_CAST({reference} AS DOUBLE)" if field in fields else None


def _coalesce_sql(parts: list[str | None], fallback: str) -> str:
    values = [part for part in parts if part]
    return f"COALESCE({', '.join([*values, fallback])})" if values else fallback
