from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from io import StringIO
from pathlib import Path
from typing import Any

import duckdb

from app.core.paths import JSON_FILES, PARQUET_TABLE_FILES, SRC, TABLE_FILES, WAREHOUSE

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_mvp.metrics import assign_iupv_percentiles, g_index, h_index, i10_index  # noqa: E402
from openalex_mvp.ranking import sort_metric_rows  # noqa: E402

INDEX_NUMERIC_FIELDS = {
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
    "iupv",
    "islv",
    "lrdi",
    "mean_authors_per_work",
    "share_single_authored",
    "two_year_mean_citedness",
}

NATIVE_LINE_CHART_METRICS = ("p", "c", "h", "i10", "two_year_mean_citedness")
CORE_LINE_CHART_METRICS = ("p", "c", "c_frac", "cpp", "h", "i10", "g", "m_local")
LEGACY_LINE_CHART_METRICS = (*CORE_LINE_CHART_METRICS, "iupv", "islv", "lrdi")
LINE_CHART_METRICS = LEGACY_LINE_CHART_METRICS


FilterSet = dict[str, Any]


def connect() -> duckdb.DuckDBPyConnection:
    WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(":memory:")
    register_views(conn)
    return conn


def register_views(conn: duckdb.DuckDBPyConnection) -> None:
    for name, path in TABLE_FILES.items():
        table_path = _preferred_table_path(name, path)
        if table_path.exists():
            escaped_path = str(table_path).replace("'", "''")
            reader = "read_parquet" if table_path.suffix.lower() == ".parquet" else "read_csv_auto"
            args = "" if reader == "read_parquet" else ", header=true, ignore_errors=true"
            conn.execute(
                f"""
                CREATE OR REPLACE VIEW {name} AS
                SELECT * FROM {reader}('{escaped_path}'{args})
                """
            )


def list_tables() -> dict[str, Any]:
    return {
        name: {
            "path": str(_preferred_table_path(name, path)),
            "csv_path": str(path),
            "parquet_path": str(PARQUET_TABLE_FILES.get(name, "")),
            "exists": _preferred_table_path(name, path).exists(),
            "rows": count_rows(name),
        }
        for name, path in TABLE_FILES.items()
    }


def count_rows(table: str) -> int:
    if table not in TABLE_FILES:
        return 0
    path = _preferred_table_path(table, TABLE_FILES[table])
    if not path.exists():
        return 0
    if path.suffix.lower() == ".csv":
        return _count_csv_rows(path)
    with connect() as conn:
        return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def _count_csv_rows(path: Path) -> int:
    # Generated CSV artifacts do not contain multiline cells; line counting keeps
    # the UI status endpoint fast without opening DuckDB for every table.
    with path.open("rb") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def table_schema(table: str) -> list[str]:
    if table not in TABLE_FILES or not _preferred_table_path(table, TABLE_FILES[table]).exists():
        return []
    with connect() as conn:
        return [row[1] for row in conn.execute(f"PRAGMA table_info('{table}')").fetchall()]


def query_table(
    table: str,
    *,
    q: str = "",
    fraction_mode: str = "",
    metric: str = "",
    author_id: str = "",
    work_id: str = "",
    sort: str = "",
    direction: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    if table not in TABLE_FILES:
        raise ValueError(f"Unknown table: {table}")
    fields = table_schema(table)
    if not fields:
        return {"table": table, "fields": [], "rows": [], "total": 0, "limit": limit, "offset": offset}

    where: list[str] = []
    args: list[Any] = []
    if q:
        expr = " OR ".join([f"CAST({field} AS VARCHAR) ILIKE ?" for field in fields])
        where.append(f"({expr})")
        args.extend([f"%{q}%"] * len(fields))
    if fraction_mode and "fraction_mode" in fields:
        where.append("fraction_mode = ?")
        args.append(fraction_mode)
    if metric and "metric_name" in fields:
        where.append("metric_name = ?")
        args.append(metric)
    if author_id and "author_id" in fields:
        where.append("author_id = ?")
        args.append(author_id)
    if work_id and "work_id" in fields:
        where.append("work_id = ?")
        args.append(work_id)

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    order_sql = ""
    if sort and sort in fields:
        order_sql = f"ORDER BY {sort} {'DESC' if direction == 'desc' else 'ASC'}"
    limit = max(1, min(1000, int(limit)))
    offset = max(0, int(offset))

    with connect() as conn:
        total = int(conn.execute(f"SELECT count(*) FROM {table} {where_sql}", args).fetchone()[0])
        rel = conn.execute(
            f"SELECT * FROM {table} {where_sql} {order_sql} LIMIT ? OFFSET ?",
            [*args, limit, offset],
        )
        rows = _records(rel)
    return {"table": table, "fields": fields, "rows": rows, "total": total, "limit": limit, "offset": offset}


def export_table(
    table: str,
    *,
    q: str = "",
    fraction_mode: str = "",
    metric: str = "",
    author_id: str = "",
    work_id: str = "",
    sort: str = "",
    direction: str = "desc",
    limit: int = 100_000,
    offset: int = 0,
) -> dict[str, Any]:
    if table not in TABLE_FILES:
        raise ValueError(f"Unknown table: {table}")
    fields = table_schema(table)
    if not fields:
        return {"table": table, "fields": [], "rows": [], "total": 0, "limit": limit, "offset": offset}

    where: list[str] = []
    args: list[Any] = []
    if q:
        expr = " OR ".join([f"CAST({field} AS VARCHAR) ILIKE ?" for field in fields])
        where.append(f"({expr})")
        args.extend([f"%{q}%"] * len(fields))
    if fraction_mode and "fraction_mode" in fields:
        where.append("fraction_mode = ?")
        args.append(fraction_mode)
    if metric and "metric_name" in fields:
        where.append("metric_name = ?")
        args.append(metric)
    if author_id and "author_id" in fields:
        where.append("author_id = ?")
        args.append(author_id)
    if work_id and "work_id" in fields:
        where.append("work_id = ?")
        args.append(work_id)

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    order_sql = ""
    if sort and sort in fields:
        order_sql = f"ORDER BY {sort} {'DESC' if direction == 'desc' else 'ASC'}"
    limit = max(1, min(500_000, int(limit)))
    offset = max(0, int(offset))

    with connect() as conn:
        total = int(conn.execute(f"SELECT count(*) FROM {table} {where_sql}", args).fetchone()[0])
        rows = _records(
            conn.execute(
                f"SELECT * FROM {table} {where_sql} {order_sql} LIMIT ? OFFSET ?",
                [*args, limit, offset],
            )
        )
    return {"table": table, "fields": fields, "rows": rows, "total": total, "limit": limit, "offset": offset}


def export_table_csv(table: str, **kwargs: Any) -> str:
    payload = export_table(table, **kwargs)
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=payload["fields"], extrasaction="ignore")
    writer.writeheader()
    writer.writerows(payload["rows"])
    return output.getvalue()


def filtered_author_indices(fraction_mode: str, filters: FilterSet | None = None) -> list[dict[str, Any]]:
    if (
        fraction_mode == "openalex_native"
        and TABLE_FILES.get("author_profiles")
        and TABLE_FILES["author_profiles"].exists()
        and TABLE_FILES["indices"].exists()
    ):
        return _filtered_native_author_indices(fraction_mode, filters)
    return _filtered_work_author_indices(fraction_mode, filters)


def _filtered_native_author_indices(fraction_mode: str, filters: FilterSet | None = None) -> list[dict[str, Any]]:
    filters = _clean_filters(filters or {})
    where = ["i.fraction_mode = ?"]
    args: list[Any] = [fraction_mode]

    subject_id = filters.get("subject_id")
    if subject_id:
        where.append("(ap.topic_ids_csv ILIKE ? OR ap.topic_share_ids_csv ILIKE ? OR ap.primary_topic_id ILIKE ?)")
        args.extend([f"%{subject_id}%", f"%{subject_id}%", f"%{subject_id}%"])

    country_code = filters.get("country_code")
    if country_code:
        where.append("upper(coalesce(ap.last_known_institution_country_codes_csv, '')) ILIKE ?")
        args.append(f"%{country_code}%")

    author_id = filters.get("author_id")
    if author_id:
        where.append("i.author_id ILIKE ?")
        args.append(f"%{_short_openalex_id(author_id)}%")

    author_name = filters.get("author_display_name")
    if author_name:
        where.append("i.author_display_name ILIKE ?")
        args.append(f"%{author_name}%")

    with connect() as conn:
        rows = _records(
            conn.execute(
                f"""
                SELECT
                  i.*,
                  ap.last_known_institution_country_codes_csv AS country_code,
                  ap.primary_topic_display_name AS subject_name,
                  ap.primary_field_display_name,
                  ap.primary_subfield_display_name,
                  ap.works_api_url
                FROM indices i
                LEFT JOIN author_profiles ap USING(author_id)
                WHERE {" AND ".join(where)}
                """,
                args,
            )
        )
    return sort_metric_rows(rows, "p")


def _filtered_work_author_indices(fraction_mode: str, filters: FilterSet | None = None) -> list[dict[str, Any]]:
    if not TABLE_FILES["author_work"].exists() or not TABLE_FILES["works"].exists() or not TABLE_FILES["authorships"].exists():
        return []

    filters = _clean_filters(filters or {})
    work_fields = set(table_schema("works"))
    where = ["aw.fraction_mode = ?"]
    args: list[Any] = [fraction_mode]

    from_date = filters.get("from_publication_date")
    to_date = filters.get("to_publication_date")
    if from_date:
        where.append("w.publication_date >= ?")
        args.append(from_date)
    if to_date:
        where.append("w.publication_date <= ?")
        args.append(to_date)

    work_type = filters.get("work_type")
    if work_type:
        work_types = [part.strip() for part in str(work_type).split("|") if part.strip()]
        if len(work_types) == 1:
            where.append("w.type = ?")
            args.append(work_types[0])
        elif work_types:
            where.append(f"w.type IN ({', '.join('?' for _ in work_types)})")
            args.extend(work_types)

    subject_id = filters.get("subject_id")
    subject_level = filters.get("subject_level")
    if subject_id:
        filter_mode = filters.get("filter_mode")
        use_topics_any = filter_mode == "topics_any" and TABLE_FILES.get("work_topics") and TABLE_FILES["work_topics"].exists()
        if use_topics_any and subject_level == "field":
            where.append("EXISTS (SELECT 1 FROM work_topics wt WHERE wt.work_id = w.work_id AND wt.field_id ILIKE ?)")
            args.append(f"%/{subject_id}")
        elif use_topics_any and subject_level == "topic":
            where.append("EXISTS (SELECT 1 FROM work_topics wt WHERE wt.work_id = w.work_id AND (wt.topic_id ILIKE ? OR wt.topic_display_name ILIKE ?))")
            args.extend([f"%/{subject_id}", f"%{subject_id}%"])
        elif use_topics_any:
            where.append("EXISTS (SELECT 1 FROM work_topics wt WHERE wt.work_id = w.work_id AND wt.subfield_id ILIKE ?)")
            args.append(f"%/{subject_id}")
        elif subject_level == "field":
            where.append("w.primary_field_id ILIKE ?")
            args.append(f"%/{subject_id}")
        elif subject_level == "topic":
            where.append("(w.primary_topic_id ILIKE ? OR w.primary_topic_display_name ILIKE ?)")
            args.extend([f"%/{subject_id}", f"%{subject_id}%"])
        else:
            where.append("(w.primary_subfield_short_id = ? OR w.primary_subfield_id ILIKE ?)")
            args.extend([subject_id, f"%/{subject_id}"])

    country_code = filters.get("country_code")
    if country_code:
        where.append("upper(coalesce(au.country_codes_csv, '')) ILIKE ?")
        args.append(f"%{country_code}%")

    author_id = filters.get("author_id")
    if author_id:
        where.append("aw.author_id ILIKE ?")
        args.append(f"%{_short_openalex_id(author_id)}%")

    author_name = filters.get("author_display_name")
    if author_name:
        where.append("aw.author_display_name ILIKE ?")
        args.append(f"%{author_name}%")

    institution_id = filters.get("institution_id")
    if institution_id:
        where.append("coalesce(au.institution_ids_csv, '') ILIKE ?")
        args.append(f"%{_short_openalex_id(institution_id)}%")

    source_id = filters.get("source_id")
    if source_id and "source_id" in work_fields:
        where.append("w.source_id ILIKE ?")
        args.append(f"%{_short_openalex_id(source_id)}%")

    source_type = filters.get("source_type")
    if source_type and "source_type" in work_fields:
        where.append("w.source_type = ?")
        args.append(source_type)

    language = filters.get("language")
    if language and "language" in work_fields:
        where.append("lower(coalesce(w.language, '')) = ?")
        args.append(str(language).lower())

    open_access_is_oa = filters.get("open_access_is_oa")
    if open_access_is_oa in {"true", "false"} and "open_access_is_oa" in work_fields:
        where.append("lower(CAST(coalesce(w.open_access_is_oa, false) AS VARCHAR)) = ?")
        args.append(open_access_is_oa)

    min_cited_by_count = filters.get("min_cited_by_count")
    if min_cited_by_count:
        where.append("w.cited_by_count >= ?")
        args.append(int(min_cited_by_count))

    q = filters.get("q")
    if q:
        where.append(
            """
            (
              aw.author_display_name ILIKE ?
              OR w.display_name ILIKE ?
              OR w.source_display_name ILIKE ?
              OR w.primary_topic_display_name ILIKE ?
            )
            """
        )
        args.extend([f"%{q}%"] * 4)

    with connect() as conn:
        rows = _records(
            conn.execute(
                f"""
                SELECT
                  aw.author_id,
                  aw.author_display_name,
                  aw.work_id,
                  aw.publication_year,
                  aw.cited_by_count,
                  aw.authors_count_used,
                  aw.credit_weight,
                  aw.cited_credit,
                  aw.single_authored_flag,
                  aw.qf_any,
                  aw.qf_authorship_truncated,
                  au.country_codes_csv AS author_country_code,
                  au.institution_ids_csv,
                  w.primary_topic_display_name AS author_subject_name
                FROM author_work aw
                JOIN works w USING(work_id)
                LEFT JOIN (
                  SELECT
                    work_id,
                    author_id,
                    string_agg(DISTINCT coalesce(country_codes_csv, ''), '|') AS country_codes_csv,
                    string_agg(DISTINCT coalesce(institution_ids_csv, ''), '|') AS institution_ids_csv
                  FROM authorships
                  WHERE author_id IS NOT NULL AND author_id != ''
                  GROUP BY work_id, author_id
                ) au ON au.work_id = aw.work_id AND au.author_id = aw.author_id
                WHERE {" AND ".join(where)}
                """,
                args,
            )
        )

    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["author_id"])].append(row)

    out: list[dict[str, Any]] = []
    for author_id, group in groups.items():
        group.sort(key=lambda row: str(row.get("work_id") or ""))
        citations = [_as_int(row.get("cited_by_count")) for row in group]
        cited_credits = [_as_float(row.get("cited_credit")) for row in group]
        p = len({str(row.get("work_id") or "") for row in group if row.get("work_id")})
        c_frac = float(sum(cited_credits))
        c = float(sum(citations))
        h = h_index(citations)
        publication_years = [_as_int(row.get("publication_year")) for row in group if _as_int(row.get("publication_year")) > 0]
        local_age = max(publication_years) - min(publication_years) + 1 if publication_years else 1
        f5_value = _f5(group)
        fm5_value = _fm5(group)
        out.append(
            {
                "run_id": "filtered",
                "fraction_mode": fraction_mode,
                "author_id": author_id,
                "author_display_name": _first_nonempty(row.get("author_display_name") for row in group),
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
                "mean_authors_per_work": _mean([_as_float(row.get("authors_count_used")) for row in group]),
                "share_single_authored": _mean([1.0 if _truthy(row.get("single_authored_flag")) else 0.0 for row in group]),
                "n_flagged_works": sum(1 for row in group if _truthy(row.get("qf_any"))),
                "n_truncated_works": sum(1 for row in group if _truthy(row.get("qf_authorship_truncated"))),
                "country_code": _first_nonempty(row.get("author_country_code") for row in group),
                "subject_name": _first_nonempty(row.get("author_subject_name") for row in group),
            }
        )

    assign_iupv_percentiles(out)
    out.sort(key=lambda row: (str(row.get("author_display_name") or ""), str(row.get("author_id") or "")))
    return out


def metric_ranking(fraction_mode: str, metric: str, filters: FilterSet | None = None, *, limit: int = 20) -> dict[str, Any]:
    if metric not in INDEX_NUMERIC_FIELDS:
        raise ValueError(f"Unsupported metric: {metric}")
    rows = filtered_author_indices(fraction_mode, filters)
    ranked = []
    visible_metrics = _visible_metrics(rows)
    for row in sort_metric_rows(rows, metric):
        item = {
            "author_id": row["author_id"],
            "author_display_name": row["author_display_name"],
            "score": _as_float(row.get(metric)),
        }
        for field in visible_metrics:
            item[field] = row.get(field)
        ranked.append(item)
    _assign_competition_rank(ranked, "score", "rank_competition")
    limit = max(1, min(int(limit), 200))
    fields = ["rank_competition", "author_display_name", "score", *visible_metrics, "author_id"]
    return {
        "table": "filtered_rating",
        "rank_metric": metric,
        "fraction_mode": fraction_mode,
        "filters": filters or {},
        "fields": fields,
        "rows": ranked[:limit],
        "total": len(ranked),
        "limit": limit,
        "offset": 0,
    }


def metric_distribution(fraction_mode: str, metric: str, filters: FilterSet | None = None) -> dict[str, Any]:
    if metric not in INDEX_NUMERIC_FIELDS:
        raise ValueError(f"Unsupported metric: {metric}")
    values = sorted(_as_float(row.get(metric)) for row in filtered_author_indices(fraction_mode, filters))
    summary = _describe(values)
    summary["histogram"] = _histogram(values, bins=8)
    return summary


def metric_line_series(
    fraction_mode: str,
    filters: FilterSet | None = None,
    *,
    metrics: tuple[str, ...] | None = None,
    rank_metric: str = "islv",
    limit: int = 30,
) -> dict[str, Any]:
    if rank_metric not in INDEX_NUMERIC_FIELDS:
        raise ValueError(f"Unsupported rank metric: {rank_metric}")
    rows = filtered_author_indices(fraction_mode, filters)
    selected_metrics = tuple(metric for metric in (metrics or _visible_metrics(rows)) if metric in INDEX_NUMERIC_FIELDS)
    rows = sort_metric_rows(rows, rank_metric)

    ranges: dict[str, tuple[float, float]] = {}
    for metric in selected_metrics:
        values = [_as_float(row.get(metric)) for row in rows]
        ranges[metric] = (min(values) if values else 0.0, max(values) if values else 0.0)

    out = []
    limit = max(1, min(int(limit), 100))
    for index, row in enumerate(rows[:limit], start=1):
        item: dict[str, Any] = {
            "rank": index,
            "label": str(index),
            "author_display_name": row.get("author_display_name"),
            "author_id": row.get("author_id"),
        }
        for metric in selected_metrics:
            low, high = ranges[metric]
            raw = _as_float(row.get(metric))
            item[metric] = 0.0 if high == low else (raw - low) / (high - low) * 100.0
            item[f"{metric}_raw"] = raw
        out.append(item)

    return {
        "rank_metric": rank_metric,
        "fraction_mode": fraction_mode,
        "normalization": "min_max_0_100_by_current_filtered_slice",
        "metrics": list(selected_metrics),
        "rows": out,
        "total": len(rows),
        "limit": limit,
    }


def read_json_doc(name: str) -> dict[str, Any] | None:
    path = JSON_FILES.get(name)
    if not path or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def author_detail(author_id: str) -> dict[str, Any]:
    with connect() as conn:
        indices = _records(conn.execute("SELECT * FROM indices WHERE author_id = ?", [author_id]))
        ratings = _records(conn.execute("SELECT * FROM ratings WHERE author_id = ? ORDER BY metric_name, rank_competition", [author_id]))
        profile = []
        works = []
        if TABLE_FILES.get("author_profiles") and TABLE_FILES["author_profiles"].exists():
            profile = _records(conn.execute("SELECT * FROM author_profiles WHERE author_id = ?", [author_id]))
        if TABLE_FILES["author_work"].exists() and TABLE_FILES["works"].exists():
            works = _records(conn.execute(
                """
                SELECT DISTINCT w.*
                FROM author_work aw
                JOIN works w USING(work_id)
                WHERE aw.author_id = ?
                ORDER BY w.cited_by_count DESC, w.publication_date DESC
                """,
                [author_id],
            ))
    return {"author_id": author_id, "profile": profile[0] if profile else None, "indices": indices, "ratings": ratings, "works": works}


def work_detail(work_id: str) -> dict[str, Any]:
    with connect() as conn:
        works = _records(conn.execute("SELECT * FROM works WHERE work_id = ?", [work_id]))
        authorships = _records(conn.execute("SELECT * FROM authorships WHERE work_id = ? ORDER BY author_seq", [work_id]))
        author_work = _records(conn.execute("SELECT * FROM author_work WHERE work_id = ? ORDER BY fraction_mode, author_display_name", [work_id]))
    return {"work_id": work_id, "work": works[0] if works else None, "authorships": authorships, "author_work": author_work}


def _records(result: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    columns = [desc[0] for desc in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def _clean_filters(filters: FilterSet) -> FilterSet:
    clean: FilterSet = {}
    for key in (
        "from_publication_date",
        "to_publication_date",
        "work_type",
        "country_code",
        "filter_mode",
        "subject_level",
        "subject_id",
        "author_id",
        "author_display_name",
        "institution_id",
        "source_id",
        "source_type",
        "language",
        "open_access_is_oa",
        "has_abstract",
        "min_cited_by_count",
        "q",
    ):
        value = filters.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if key == "country_code":
            text = text.upper()[:2]
        if key == "min_cited_by_count":
            try:
                clean[key] = max(0, int(float(text)))
            except ValueError:
                continue
            continue
        clean[key] = text
    return clean


def _short_openalex_id(value: Any) -> str:
    text = str(value or "").strip().rstrip("/")
    return text.rsplit("/", 1)[-1]


def _describe(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "min": 0, "q1": 0, "median": 0, "mean": 0, "q3": 0, "p90": 0, "max": 0, "stddev": 0}
    mean = sum(values) / len(values)
    if len(values) > 1:
        variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    else:
        variance = 0.0
    return {
        "n": len(values),
        "min": values[0],
        "q1": _quantile(values, 0.25),
        "median": _quantile(values, 0.50),
        "mean": mean,
        "q3": _quantile(values, 0.75),
        "p90": _quantile(values, 0.90),
        "max": values[-1],
        "stddev": variance**0.5,
    }


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(values) - 1)
    weight = pos - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _histogram(values: list[float], bins: int) -> list[dict[str, Any]]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high == low:
        return [{"label": f"{low:.3g}", "min": low, "max": high, "count": len(values)}]
    width = (high - low) / bins
    counts = [0] * bins
    for value in values:
        index = min(int((value - low) / width), bins - 1)
        counts[index] += 1
    return [
        {
            "label": f"{low + width * i:.3g}-{low + width * (i + 1):.3g}",
            "min": low + width * i,
            "max": low + width * (i + 1),
            "count": count,
        }
        for i, count in enumerate(counts)
    ]


def _assign_competition_rank(rows: list[dict[str, Any]], score_field: str, rank_field: str) -> None:
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
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    return int(_as_float(value))


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _visible_metrics(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return list(LINE_CHART_METRICS)
    if any("two_year_mean_citedness" in row for row in rows):
        order = NATIVE_LINE_CHART_METRICS
    else:
        order = LEGACY_LINE_CHART_METRICS
    return [metric for metric in order if any(metric in row for row in rows)]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _f5(group: list[dict[str, Any]]) -> float:
    return float(sum(1 for row in group if _as_int(row.get("cited_by_count")) >= 5))


def _fm5(group: list[dict[str, Any]]) -> float:
    return float(sum(_as_float(row.get("credit_weight")) for row in group if _as_int(row.get("cited_by_count")) >= 5))


def _first_nonempty(values: Any) -> str | None:
    for value in values:
        if value:
            return str(value)
    return None


def _preferred_table_path(name: str, csv_path: Path) -> Path:
    parquet_path = PARQUET_TABLE_FILES.get(name)
    if parquet_path and parquet_path.exists():
        return parquet_path
    return csv_path
