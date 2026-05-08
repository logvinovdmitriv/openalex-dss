from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from io import StringIO
from pathlib import Path
from typing import Any

import duckdb

from app.core.paths import DATA, SRC, TABLE_KINDS, WAREHOUSE
from app.services import custom_metrics

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_dss.metrics import assign_iupv_percentiles, g_index, h_index, i10_index, lrdi as lrdi_metric  # noqa: E402
from openalex_dss.ranking import sort_metric_rows  # noqa: E402

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
}

NATIVE_LINE_CHART_METRICS = ("p", "c", "h", "i10")
CORE_LINE_CHART_METRICS = ("p", "c", "c_frac", "cpp", "h", "i10", "g", "m_local")
EXTENDED_LINE_CHART_METRICS = (*CORE_LINE_CHART_METRICS, "iupv", "islv", "lrdi")
LINE_CHART_METRICS = EXTENDED_LINE_CHART_METRICS

FilterSet = dict[str, Any]

DUMP_TABLES = {"works", "authorships", "work_topics"}
RUN_JSON_DOCS = {
    "fetch_meta": ("passports", "fetch_meta.json"),
    "quality": ("passports", "quality_report.json"),
    "checksums": ("passports", "checksums.json"),
    "pipeline": ("passports", "pipeline_summary.json"),
}


def connect_scope(*, run_id: str = "", dump_id: str = "") -> duckdb.DuckDBPyConnection:
    WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(":memory:")
    register_views(conn, run_id=run_id, dump_id=dump_id)
    return conn


def register_views(conn: duckdb.DuckDBPyConnection, *, run_id: str = "", dump_id: str = "") -> None:
    for name in TABLE_KINDS:
        table_path = resolve_scoped_table_path(name, run_id=run_id, dump_id=dump_id)
        if table_path and table_path.exists():
            _register_file_view(conn, name, table_path)


def _register_file_view(conn: duckdb.DuckDBPyConnection, name: str, table_path: Path) -> None:
    escaped_path = str(table_path).replace("'", "''")
    reader = "read_parquet" if table_path.suffix.lower() == ".parquet" else "read_csv_auto"
    args = "" if reader == "read_parquet" else ", header=true, ignore_errors=true"
    conn.execute(
        f"""
        CREATE OR REPLACE VIEW {name} AS
        SELECT * FROM {reader}('{escaped_path}'{args})
        """
    )


def resolve_scoped_table_path(
    table: str,
    *,
    run_id: str | None = None,
    dump_id: str | None = None,
) -> Path | None:
    if table not in TABLE_KINDS:
        raise ValueError(f"Unknown table: {table}")
    scope = resolve_analysis_scope(run_id=run_id or "", dump_id=dump_id or "")
    run_id = scope["run_id"]
    dump_id = scope["dump_id"]

    if run_id:
        if table in DUMP_TABLES:
            if dump_id:
                return _dump_table_path(dump_id, table)
            return None
        run_path = _run_table_path(run_id, table)
        if run_path:
            return run_path
        return None

    if dump_id and table in DUMP_TABLES:
        return _dump_table_path(dump_id, table)

    return None


def resolve_analysis_scope(*, run_id: str = "", dump_id: str = "") -> dict[str, str]:
    run_id = str(run_id or "").strip()
    dump_id = _resolve_dump_id(str(dump_id or "").strip())
    if not run_id and dump_id:
        run_id = _recent_run_for_dump(dump_id)
    expected_dump_id = _dump_id_for_run(run_id) if run_id else ""
    expected_dump_id = _resolve_dump_id(expected_dump_id)
    if run_id and dump_id and expected_dump_id and _safe_id(dump_id) != _safe_id(expected_dump_id):
        raise ValueError(f"dump_id={dump_id} is incompatible with run_id={run_id}; expected {expected_dump_id}")
    return {"run_id": run_id, "dump_id": dump_id or expected_dump_id}


def table_exists(name: str, *, run_id: str = "", dump_id: str = "") -> bool:
    if name not in TABLE_KINDS:
        return False
    table_path = resolve_scoped_table_path(name, run_id=run_id, dump_id=dump_id)
    return bool(table_path and table_path.exists())


def list_tables(*, run_id: str = "", dump_id: str = "") -> dict[str, Any]:
    scope = resolve_analysis_scope(run_id=run_id, dump_id=dump_id)
    if not (scope["run_id"] or scope["dump_id"]):
        return {}
    tables: dict[str, Any] = {}
    for name in TABLE_KINDS:
        resolved_path = resolve_scoped_table_path(name, run_id=scope["run_id"], dump_id=scope["dump_id"])
        exists = bool(resolved_path and resolved_path.exists())
        tables[name] = {
            "path": str(resolved_path or ""),
            "resolved_path": str(resolved_path or ""),
            "scope": "run" if scope["run_id"] else "dump",
            "run_id": scope["run_id"],
            "dump_id": scope["dump_id"],
            "exists": exists,
            "rows": count_rows(name, run_id=scope["run_id"], dump_id=scope["dump_id"]),
        }
    return tables


def count_rows(table: str, *, run_id: str = "", dump_id: str = "") -> int:
    if table not in TABLE_KINDS:
        return 0
    path = resolve_scoped_table_path(table, run_id=run_id, dump_id=dump_id)
    if not path or not path.exists():
        return 0
    if path.suffix.lower() == ".csv":
        return _count_csv_rows(path)
    return _count_parquet_rows(path)


def _count_csv_rows(path: Path) -> int:
    # Generated CSV artifacts do not contain multiline cells; line counting keeps
    # the UI status endpoint fast without opening DuckDB for every table.
    with path.open("rb") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def _count_parquet_rows(path: Path) -> int:
    escaped_path = str(path).replace("'", "''")
    with duckdb.connect(":memory:") as conn:
        return int(conn.execute(f"SELECT count(*) FROM read_parquet('{escaped_path}')").fetchone()[0])


def table_schema(table: str, *, run_id: str = "", dump_id: str = "") -> list[str]:
    if not table_exists(table, run_id=run_id, dump_id=dump_id):
        return []
    with connect_scope(run_id=run_id, dump_id=dump_id) as conn:
        return [row[1] for row in conn.execute(f"PRAGMA table_info('{table}')").fetchall()]


def query_table(
    table: str,
    *,
    run_id: str = "",
    dump_id: str = "",
    q: str = "",
    fraction_mode: str = "",
    metric: str = "",
    author_id: str = "",
    work_id: str = "",
    data_filters: dict[str, Any] | None = None,
    sort: str = "",
    direction: str = "desc",
    limit: int = 100,
    offset: int = 0,
    select_fields: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, Any]:
    if table not in TABLE_KINDS:
        raise ValueError(f"Unknown table: {table}")
    scope = resolve_analysis_scope(run_id=run_id, dump_id=dump_id)
    run_id = scope["run_id"]
    dump_id = scope["dump_id"]
    fields = table_schema(table, run_id=run_id, dump_id=dump_id)
    if not fields:
        return {"table": table, "fields": [], "rows": [], "total": 0, "limit": limit, "offset": offset, "run_id": run_id, "dump_id": dump_id}
    with connect_scope(run_id=run_id, dump_id=dump_id) as conn:
        payload = _query_registered_table(
            conn,
            table,
            fields,
            q=q,
            fraction_mode=fraction_mode,
            metric=metric,
            author_id=author_id,
            work_id=work_id,
            data_filters=data_filters,
            sort=sort,
            direction=direction,
            limit=limit,
            offset=offset,
            select_fields=select_fields,
        )
        payload["run_id"] = run_id
        payload["dump_id"] = dump_id
        source_path = resolve_scoped_table_path(table, run_id=run_id, dump_id=dump_id)
        if source_path:
            payload["source_path"] = str(source_path)
        return payload


def _query_registered_table(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    fields: list[str],
    *,
    q: str = "",
    fraction_mode: str = "",
    metric: str = "",
    author_id: str = "",
    work_id: str = "",
    data_filters: dict[str, Any] | None = None,
    sort: str = "",
    direction: str = "desc",
    limit: int = 100,
    offset: int = 0,
    select_fields: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, Any]:

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
    _append_column_filter_clauses(where, args, fields, data_filters)

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    order_sql = ""
    if sort and sort in fields:
        order_sql = f"ORDER BY {sort} {'DESC' if direction == 'desc' else 'ASC'}"
    selected_fields = _selected_table_fields(fields, select_fields)
    select_sql = ", ".join(selected_fields) if selected_fields else "*"
    raw_limit = max(0, min(500_000, int(limit or 0)))
    offset = max(0, int(offset))

    total = int(conn.execute(f"SELECT count(*) FROM {table} {where_sql}", args).fetchone()[0])
    if raw_limit > 0:
        rel = conn.execute(
            f"SELECT {select_sql} FROM {table} {where_sql} {order_sql} LIMIT ? OFFSET ?",
            [*args, raw_limit, offset],
        )
        effective_limit = raw_limit
    else:
        rel = conn.execute(
            f"SELECT {select_sql} FROM {table} {where_sql} {order_sql} OFFSET ?",
            [*args, offset],
        )
        effective_limit = 0
    rows = _records(rel)
    return {"table": table, "fields": selected_fields or fields, "rows": rows, "total": total, "limit": effective_limit, "offset": offset}


def _selected_table_fields(fields: list[str], select_fields: list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    if not select_fields:
        return list(fields)
    requested = {str(field).strip() for field in select_fields if str(field).strip()}
    return [field for field in fields if field in requested]


def _append_column_filter_clauses(where: list[str], args: list[Any], fields: list[str], data_filters: dict[str, Any] | None) -> None:
    filters = parse_column_filters(data_filters)
    field_set = set(fields)
    for field, filter_payload in filters.items():
        if field not in field_set:
            continue
        contains = str(filter_payload.get("contains") or "").strip()
        if contains:
            where.append(f"CAST({field} AS VARCHAR) ILIKE ?")
            args.append(f"%{contains}%")
        min_text = str(filter_payload.get("min") or "").strip().replace(",", ".")
        if min_text:
            min_value = _parse_filter_number(min_text, field)
            where.append(f"TRY_CAST({field} AS DOUBLE) >= ?")
            args.append(min_value)
        max_text = str(filter_payload.get("max") or "").strip().replace(",", ".")
        if max_text:
            max_value = _parse_filter_number(max_text, field)
            where.append(f"TRY_CAST({field} AS DOUBLE) <= ?")
            args.append(max_value)


def _row_matches_column_filters(row: dict[str, Any], filters: dict[str, dict[str, str]], *, ignore_unknown_fields: bool = False) -> bool:
    for field, filter_payload in filters.items():
        if field not in row:
            if ignore_unknown_fields:
                continue
            return False
        contains = str(filter_payload.get("contains") or "").strip().lower()
        if contains and contains not in str(row.get(field) or "").lower():
            return False
        min_text = str(filter_payload.get("min") or "").strip().replace(",", ".")
        max_text = str(filter_payload.get("max") or "").strip().replace(",", ".")
        if min_text or max_text:
            value = _as_float(row.get(field))
            if min_text and value < _parse_filter_number(min_text, field):
                return False
            if max_text and value > _parse_filter_number(max_text, field):
                return False
    return True


def _parse_filter_number(value: str, field: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric filter for {field}: {value}") from exc


def export_table(
    table: str,
    *,
    run_id: str = "",
    dump_id: str = "",
    q: str = "",
    fraction_mode: str = "",
    metric: str = "",
    author_id: str = "",
    work_id: str = "",
    data_filters: dict[str, Any] | None = None,
    sort: str = "",
    direction: str = "desc",
    limit: int = 100_000,
    offset: int = 0,
) -> dict[str, Any]:
    if table not in TABLE_KINDS:
        raise ValueError(f"Unknown table: {table}")
    scope = resolve_analysis_scope(run_id=run_id, dump_id=dump_id)
    run_id = scope["run_id"]
    dump_id = scope["dump_id"]
    fields = table_schema(table, run_id=run_id, dump_id=dump_id)
    if not fields:
        return {"table": table, "fields": [], "rows": [], "total": 0, "limit": limit, "offset": offset, "run_id": run_id, "dump_id": dump_id}

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
    _append_column_filter_clauses(where, args, fields, data_filters)

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    order_sql = ""
    if sort and sort in fields:
        order_sql = f"ORDER BY {sort} {'DESC' if direction == 'desc' else 'ASC'}"
    raw_limit = max(0, min(500_000, int(limit or 0)))
    offset = max(0, int(offset))

    source_path = resolve_scoped_table_path(table, run_id=run_id, dump_id=dump_id)
    with connect_scope(run_id=run_id, dump_id=dump_id) as conn:
        total = int(conn.execute(f"SELECT count(*) FROM {table} {where_sql}", args).fetchone()[0])
        if raw_limit > 0:
            rows = _records(
                conn.execute(
                    f"SELECT * FROM {table} {where_sql} {order_sql} LIMIT ? OFFSET ?",
                    [*args, raw_limit, offset],
                )
            )
            effective_limit = raw_limit
        else:
            rows = _records(
                conn.execute(
                    f"SELECT * FROM {table} {where_sql} {order_sql} OFFSET ?",
                    [*args, offset],
                )
            )
            effective_limit = 0
    payload = {"table": table, "fields": fields, "rows": rows, "total": total, "limit": effective_limit, "offset": offset, "run_id": run_id, "dump_id": dump_id}
    if source_path:
        payload["source_path"] = str(source_path)
    return payload


def export_table_csv(table: str, **kwargs: Any) -> str:
    payload = export_table(table, **kwargs)
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=payload["fields"], extrasaction="ignore")
    writer.writeheader()
    writer.writerows(payload["rows"])
    return output.getvalue()


def parse_column_filters(raw: str | dict[str, Any] | None) -> dict[str, dict[str, str]]:
    if not raw:
        return {}
    payload: Any = raw
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("data_filters must be a JSON object.") from exc
    if not isinstance(payload, dict):
        raise ValueError("data_filters must be a JSON object.")
    out: dict[str, dict[str, str]] = {}
    for field, filter_payload in payload.items():
        field_name = str(field or "").strip()
        if not field_name or not isinstance(filter_payload, dict):
            continue
        clean: dict[str, str] = {}
        for key in ("contains", "min", "max"):
            value = str(filter_payload.get(key) or "").strip()
            if value:
                clean[key] = value
        if clean:
            out[field_name] = clean
    return out


def filter_rows_by_column_filters(
    rows: list[dict[str, Any]],
    data_filters: dict[str, Any] | None,
    *,
    ignore_unknown_fields: bool = False,
) -> list[dict[str, Any]]:
    filters = parse_column_filters(data_filters)
    if not filters:
        return rows
    return [row for row in rows if _row_matches_column_filters(row, filters, ignore_unknown_fields=ignore_unknown_fields)]


def apply_data_selection(
    rows: list[dict[str, Any]],
    *,
    data_filters: dict[str, Any] | None = None,
    data_search: str = "",
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = 0,
) -> list[dict[str, Any]]:
    """Apply the Data page filter, search, sort and row limit contract to in-memory metric rows."""
    selected = filter_rows_by_column_filters(rows, data_filters, ignore_unknown_fields=True)
    search = str(data_search or "").strip().lower()
    if search:
        selected = [row for row in selected if any(search in str(value or "").lower() for value in row.values())]
    sort_field = str(data_sort or "").strip()
    if sort_field and any(sort_field in row and row.get(sort_field) not in (None, "") for row in selected):
        selected = _sort_rows_by_field(selected, sort_field, data_direction=data_direction)
    try:
        limit = int(data_limit or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit > 0:
        selected = selected[: max(1, min(limit, 500_000))]
    return selected


def selected_index_rows(
    fraction_mode: str,
    filters: FilterSet | None = None,
    *,
    run_id: str = "",
    dump_id: str = "",
    author_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    data_filters: dict[str, Any] | None = None,
    data_search: str = "",
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = 0,
    custom_metric_defs: list[dict[str, str]] | None = None,
    select_fields: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return author-level rows using the fastest safe source for the current selection.

    If the request does not apply work-level slice filters, the run-scoped
    ``indices`` table is already the correct author-level source. Reading it
    directly keeps large local slices responsive because DuckDB can filter,
    sort and limit the table before rows reach Python. Work-level filters still
    use the recomputation path because those filters must rebuild author
    aggregates from matching works.
    """
    scope = resolve_analysis_scope(run_id=run_id, dump_id=dump_id)
    run_id = scope["run_id"]
    dump_id = scope["dump_id"]
    parsed_filters = parse_column_filters(data_filters)
    data_search = str(data_search or "").strip()
    data_sort = str(data_sort or "").strip()
    data_direction = "asc" if str(data_direction or "").strip().lower() == "asc" else "desc"
    try:
        normalized_limit = max(0, min(int(data_limit or 0), 500_000))
    except (TypeError, ValueError):
        normalized_limit = 0

    if _can_use_precomputed_indices(filters, run_id=run_id, dump_id=dump_id):
        return _selected_precomputed_index_rows(
            fraction_mode,
            run_id=run_id,
            dump_id=dump_id,
            author_ids=author_ids,
            data_filters=parsed_filters,
            data_search=data_search,
            data_sort=data_sort,
            data_direction=data_direction,
            data_limit=normalized_limit,
            custom_metric_defs=custom_metric_defs,
            select_fields=select_fields,
        )

    rows = filtered_indices(fraction_mode, filters, run_id=run_id, dump_id=dump_id)
    rows = filter_rows_by_author_ids(rows, author_ids)
    rows = apply_data_selection(
        rows,
        data_filters=parsed_filters,
        data_search=data_search,
        data_sort=data_sort,
        data_direction=data_direction,
        data_limit=normalized_limit,
    )
    return custom_metrics.apply_custom_metrics(rows, custom_metric_defs)


def _can_use_precomputed_indices(filters: FilterSet | None, *, run_id: str = "", dump_id: str = "") -> bool:
    return not _clean_filters(filters or {}) and table_exists("indices", run_id=run_id, dump_id=dump_id)


def _selected_precomputed_index_rows(
    fraction_mode: str,
    *,
    run_id: str,
    dump_id: str,
    author_ids: set[str] | list[str] | tuple[str, ...] | None,
    data_filters: dict[str, Any],
    data_search: str,
    data_sort: str,
    data_direction: str,
    data_limit: int,
    custom_metric_defs: list[dict[str, str]] | None,
    select_fields: list[str] | tuple[str, ...] | set[str] | None,
) -> list[dict[str, Any]]:
    fields = set(table_schema("indices", run_id=run_id, dump_id=dump_id))
    custom_ids = custom_metrics.custom_metric_ids(custom_metric_defs)
    native_filters = {field: value for field, value in parse_column_filters(data_filters).items() if field in fields}
    python_filters = {field: value for field, value in parse_column_filters(data_filters).items() if field not in fields}
    sort_is_native = not data_sort or data_sort in fields
    sort_is_custom = data_sort in custom_ids
    needs_python_selection = bool(author_ids) or bool(python_filters) or sort_is_custom
    required_fields = _selected_index_query_fields(
        fields,
        requested_fields=select_fields,
        native_filters=native_filters,
        data_sort=data_sort,
        custom_metric_defs=custom_metric_defs,
    )
    effective_data_limit = data_limit
    query_limit = data_limit
    query_sort = data_sort if sort_is_native else ""
    payload = query_table(
        "indices",
        run_id=run_id,
        dump_id=dump_id,
        q=data_search,
        fraction_mode=fraction_mode,
        data_filters=native_filters,
        sort=query_sort,
        direction=data_direction,
        limit=query_limit,
        select_fields=required_fields,
    )
    rows = list(payload.get("rows") or [])
    rows = filter_rows_by_author_ids(rows, author_ids)
    if custom_metric_defs:
        rows = custom_metrics.apply_custom_metrics(rows, custom_metric_defs)
    if needs_python_selection:
        rows = apply_data_selection(
            rows,
            data_filters=python_filters,
            data_search="",
            data_sort=data_sort,
            data_direction=data_direction,
            data_limit=effective_data_limit,
        )
    return rows


def _selected_index_query_fields(
    fields: set[str],
    *,
    requested_fields: list[str] | tuple[str, ...] | set[str] | None,
    native_filters: dict[str, Any],
    data_sort: str,
    custom_metric_defs: list[dict[str, str]] | None,
) -> set[str]:
    required = {"author_id", "author_display_name"}
    required.update(str(field).strip() for field in requested_fields or [] if str(field).strip())
    required.update(native_filters.keys())
    if data_sort:
        required.add(data_sort)
    required.update(custom_metrics.referenced_base_fields(custom_metric_defs))
    return {field for field in required if field in fields}


def _sort_rows_by_field(rows: list[dict[str, Any]], field: str, *, data_direction: str = "desc") -> list[dict[str, Any]]:
    present = [row for row in rows if field in row and row.get(field) not in (None, "")]
    missing = [row for row in rows if field not in row or row.get(field) in (None, "")]
    reverse = str(data_direction or "desc").strip().lower() != "asc"
    return sorted(present, key=lambda row: _selection_sort_key(row.get(field)), reverse=reverse) + missing


def _selection_sort_key(value: Any) -> tuple[int, float, str]:
    try:
        return (0, float(value), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(value or "").casefold())


def filtered_indices(
    fraction_mode: str,
    filters: FilterSet | None = None,
    *,
    run_id: str = "",
    dump_id: str = "",
) -> list[dict[str, Any]]:
    return _filtered_work_indices(fraction_mode, filters, run_id=run_id, dump_id=dump_id)


def _filtered_work_indices(
    fraction_mode: str,
    filters: FilterSet | None = None,
    *,
    run_id: str = "",
    dump_id: str = "",
) -> list[dict[str, Any]]:
    if not (
        table_exists("author_work", run_id=run_id, dump_id=dump_id)
        and table_exists("works", run_id=run_id, dump_id=dump_id)
        and table_exists("authorships", run_id=run_id, dump_id=dump_id)
    ):
        return []

    filters = _clean_filters(filters or {})
    metric_params = _run_metric_params(run_id)
    work_fields = set(table_schema("works", run_id=run_id, dump_id=dump_id))
    _validate_local_analysis_filters(filters)
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

    filter_mode = filters.get("filter_mode")
    subject_id = filters.get("subject_id")
    subject_level = filters.get("subject_level")
    if subject_id:
        use_topics_any = filter_mode == "topics_any" and table_exists("work_topics", run_id=run_id, dump_id=dump_id)
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

    keyword_id = filters.get("keyword_id")
    keyword_display_name = filters.get("keyword_display_name")
    if filter_mode == "keyword" and (keyword_id or keyword_display_name):
        clauses: list[str] = []
        if table_exists("work_topics", run_id=run_id, dump_id=dump_id):
            topic_terms = [term for term in (_short_openalex_id(keyword_id), keyword_display_name) if term]
            if topic_terms:
                topic_clauses = []
                for term in topic_terms:
                    topic_clauses.append("(wt.topic_id ILIKE ? OR wt.topic_display_name ILIKE ?)")
                    args.extend([f"%{term}%", f"%{term}%"])
                clauses.append(f"EXISTS (SELECT 1 FROM work_topics wt WHERE wt.work_id = w.work_id AND ({' OR '.join(topic_clauses)}))")
        text_clause, text_args = _text_match_clause(work_fields, keyword_display_name or _short_openalex_id(keyword_id))
        if text_clause:
            clauses.append(text_clause)
            args.extend(text_args)
        if clauses:
            where.append(f"({' OR '.join(clauses)})")

    text_search_query = filters.get("text_search_query")
    if text_search_query:
        text_clause, text_args = _text_match_clause(work_fields, text_search_query)
        if text_clause:
            where.append(text_clause)
            args.extend(text_args)

    doi = filters.get("doi")
    if doi and "doi" in work_fields:
        variants = _doi_variants(doi)
        if variants:
            where.append(f"lower(trim(coalesce(w.doi, ''))) IN ({', '.join('?' for _ in variants)})")
            args.extend(variants)

    country_code = filters.get("country_code")
    if country_code:
        where.append("list_contains(string_split(upper(coalesce(au.country_codes_csv, '')), '|'), ?)")
        args.append(str(country_code).upper())

    author_id = filters.get("author_id")
    if author_id:
        where.append("aw.author_id ILIKE ?")
        args.append(f"%{_short_openalex_id(author_id)}%")

    author_orcid = filters.get("author_orcid")
    if author_orcid and "author_orcid" in set(table_schema("authorships", run_id=run_id, dump_id=dump_id)):
        where.append(
            """
            EXISTS (
              SELECT 1 FROM authorships ax
              WHERE ax.work_id = aw.work_id
                AND ax.author_id = aw.author_id
                AND coalesce(ax.author_orcid, '') ILIKE ?
            )
            """
        )
        args.append(f"%{author_orcid}%")

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

    source_display_name = filters.get("source_display_name")
    if source_display_name and "source_display_name" in work_fields:
        where.append("w.source_display_name ILIKE ?")
        args.append(f"%{source_display_name}%")

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

    has_abstract = filters.get("has_abstract")
    if has_abstract in {"true", "false"} and "has_abstract" in work_fields:
        where.append("lower(CAST(coalesce(w.has_abstract, false) AS VARCHAR)) = ?")
        args.append(has_abstract)

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

    with connect_scope(run_id=run_id, dump_id=dump_id) as conn:
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
                "source_run_id": run_id,
                "source_dump_id": dump_id or _dump_id_for_run(run_id),
                "metric_scope": "filtered_recomputed",
                "percentile_scope": "current filtered author set",
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
                "lrdi": lrdi_metric(
                    group,
                    analysis_year=metric_params["analysis_year"],
                    p0=metric_params["lrdi_p0"],
                    lam=metric_params["lrdi_lambda"],
                ),
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


def metric_ranking(
    fraction_mode: str,
    metric: str,
    filters: FilterSet | None = None,
    *,
    limit: int = 20,
    max_limit: int = 200,
    run_id: str = "",
    dump_id: str = "",
    author_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    data_filters: dict[str, Any] | None = None,
    data_search: str = "",
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = 0,
    custom_metric_defs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    if not _metric_supported(metric, custom_metric_defs):
        raise ValueError(f"Unsupported metric: {metric}")
    rows = selected_index_rows(
        fraction_mode,
        filters,
        run_id=run_id,
        dump_id=dump_id,
        author_ids=author_ids,
        data_filters=data_filters,
        data_search=data_search,
        data_sort=data_sort,
        data_direction=data_direction,
        data_limit=data_limit,
        custom_metric_defs=custom_metric_defs,
    )
    return metric_ranking_from_rows(
        rows,
        fraction_mode,
        metric,
        filters,
        limit=limit,
        max_limit=max_limit,
        run_id=run_id,
        dump_id=dump_id,
        custom_metric_defs=custom_metric_defs,
    )


def metric_ranking_from_rows(
    rows: list[dict[str, Any]],
    fraction_mode: str,
    metric: str,
    filters: FilterSet | None = None,
    *,
    limit: int = 20,
    max_limit: int = 200,
    run_id: str = "",
    dump_id: str = "",
    custom_metric_defs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    if not _metric_supported(metric, custom_metric_defs, rows):
        raise ValueError(f"Unsupported metric: {metric}")
    scope = resolve_analysis_scope(run_id=run_id, dump_id=dump_id)
    ranked = []
    visible_metrics = _visible_metrics(rows, custom_metric_defs)
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
    requested_limit = max(0, min(int(limit or 0), max(1, int(max_limit))))
    visible_rows = ranked if requested_limit <= 0 else ranked[:requested_limit]
    fields = ["rank_competition", "author_display_name", "score", *visible_metrics, "author_id"]
    return {
        "table": "filtered_rating",
        "rank_metric": metric,
        "fraction_mode": fraction_mode,
        "metric_scope": "filtered_recomputed",
        "percentile_scope": "current filtered author set",
        "filters": filters or {},
        "metric_params": _run_metric_params(scope["run_id"]),
        "run_id": scope["run_id"],
        "dump_id": scope["dump_id"],
        "fields": fields,
        "rows": visible_rows,
        "total": len(ranked),
        "limit": requested_limit,
        "offset": 0,
        "custom_metrics": custom_metrics.metric_catalog(custom_metric_defs),
    }


def metric_distribution(
    fraction_mode: str,
    metric: str,
    filters: FilterSet | None = None,
    *,
    run_id: str = "",
    dump_id: str = "",
    author_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    data_filters: dict[str, Any] | None = None,
    data_search: str = "",
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = 0,
    custom_metric_defs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    if not _metric_supported(metric, custom_metric_defs):
        raise ValueError(f"Unsupported metric: {metric}")
    rows = selected_index_rows(
        fraction_mode,
        filters,
        run_id=run_id,
        dump_id=dump_id,
        author_ids=author_ids,
        data_filters=data_filters,
        data_search=data_search,
        data_sort=data_sort,
        data_direction=data_direction,
        data_limit=data_limit,
        custom_metric_defs=custom_metric_defs,
    )
    return metric_distribution_from_rows(rows, fraction_mode, metric, run_id=run_id, dump_id=dump_id, custom_metric_defs=custom_metric_defs)


def metric_distribution_from_rows(
    rows: list[dict[str, Any]],
    fraction_mode: str,
    metric: str,
    *,
    run_id: str = "",
    dump_id: str = "",
    custom_metric_defs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    del fraction_mode
    if not _metric_supported(metric, custom_metric_defs, rows):
        raise ValueError(f"Unsupported metric: {metric}")
    scope = resolve_analysis_scope(run_id=run_id, dump_id=dump_id)
    values = sorted(_as_float(row.get(metric)) for row in rows)
    summary = _describe(values)
    summary["histogram"] = _histogram(values, bins=8)
    summary["run_id"] = scope["run_id"]
    summary["dump_id"] = scope["dump_id"]
    summary["metric_scope"] = "filtered_recomputed"
    summary["percentile_scope"] = "current filtered author set"
    summary["metric_params"] = _run_metric_params(scope["run_id"])
    summary["custom_metrics"] = custom_metrics.metric_catalog(custom_metric_defs)
    return summary


def metric_line_series(
    fraction_mode: str,
    filters: FilterSet | None = None,
    *,
    metrics: tuple[str, ...] | None = None,
    rank_metric: str = "islv",
    limit: int = 30,
    run_id: str = "",
    dump_id: str = "",
    custom_metric_defs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    if not _metric_supported(rank_metric, custom_metric_defs):
        raise ValueError(f"Unsupported rank metric: {rank_metric}")
    rows = filtered_indices(fraction_mode, filters, run_id=run_id, dump_id=dump_id)
    rows = custom_metrics.apply_custom_metrics(rows, custom_metric_defs)
    return metric_line_series_from_rows(
        rows,
        fraction_mode,
        metrics=metrics,
        rank_metric=rank_metric,
        limit=limit,
        run_id=run_id,
        dump_id=dump_id,
        custom_metric_defs=custom_metric_defs,
    )


def metric_line_series_from_rows(
    rows: list[dict[str, Any]],
    fraction_mode: str,
    *,
    metrics: tuple[str, ...] | None = None,
    rank_metric: str = "islv",
    limit: int = 30,
    run_id: str = "",
    dump_id: str = "",
    custom_metric_defs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    if not _metric_supported(rank_metric, custom_metric_defs, rows):
        raise ValueError(f"Unsupported rank metric: {rank_metric}")
    scope = resolve_analysis_scope(run_id=run_id, dump_id=dump_id)
    selected_metrics = tuple(metric for metric in (metrics or _visible_metrics(rows, custom_metric_defs)) if _metric_supported(metric, custom_metric_defs, rows))
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
        "run_id": scope["run_id"],
        "dump_id": scope["dump_id"],
        "metric_scope": "filtered_recomputed",
        "percentile_scope": "current filtered author set",
        "metric_params": _run_metric_params(scope["run_id"]),
        "normalization": "min_max_0_100_by_current_filtered_slice",
        "metrics": list(selected_metrics),
        "rows": out,
        "total": len(rows),
        "limit": limit,
        "custom_metrics": custom_metrics.metric_catalog(custom_metric_defs),
    }


def metric_bundle(
    fraction_mode: str,
    metric: str,
    filters: FilterSet | None = None,
    *,
    limit: int = 20,
    run_id: str = "",
    dump_id: str = "",
    author_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    data_filters: dict[str, Any] | None = None,
    data_search: str = "",
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = 0,
    custom_metric_defs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    if not _metric_supported(metric, custom_metric_defs):
        raise ValueError(f"Unsupported metric: {metric}")
    scope = resolve_analysis_scope(run_id=run_id, dump_id=dump_id)
    rows = selected_index_rows(
        fraction_mode,
        filters,
        run_id=scope["run_id"],
        dump_id=scope["dump_id"],
        author_ids=author_ids,
        data_filters=data_filters,
        data_search=data_search,
        data_sort=data_sort,
        data_direction=data_direction,
        data_limit=data_limit,
        custom_metric_defs=custom_metric_defs,
    )
    return {
        "rows": rows,
        "distribution": metric_distribution_from_rows(rows, fraction_mode, metric, run_id=scope["run_id"], dump_id=scope["dump_id"], custom_metric_defs=custom_metric_defs),
        "ranking": metric_ranking_from_rows(rows, fraction_mode, metric, filters, limit=limit, max_limit=500_000, run_id=scope["run_id"], dump_id=scope["dump_id"], custom_metric_defs=custom_metric_defs),
        "line_series": metric_line_series_from_rows(rows, fraction_mode, rank_metric=metric, limit=40, run_id=scope["run_id"], dump_id=scope["dump_id"], custom_metric_defs=custom_metric_defs),
    }


def filter_rows_by_author_ids(rows: list[dict[str, Any]], author_ids: set[str] | list[str] | tuple[str, ...] | None) -> list[dict[str, Any]]:
    if author_ids is None:
        return rows
    allowed = {str(author_id) for author_id in author_ids if str(author_id).strip()}
    if not allowed:
        return []
    return [row for row in rows if str(row.get("author_id") or "") in allowed]


def read_json_doc(name: str, *, run_id: str = "") -> dict[str, Any] | None:
    if run_id:
        path = _run_json_path(run_id, name)
        if path and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def author_detail(author_id: str, *, run_id: str = "", dump_id: str = "") -> dict[str, Any]:
    with connect_scope(run_id=run_id, dump_id=dump_id) as conn:
        indices = _records(conn.execute("SELECT * FROM indices WHERE author_id = ?", [author_id])) if table_exists("indices", run_id=run_id, dump_id=dump_id) else []
        ratings = _records(conn.execute("SELECT * FROM ratings WHERE author_id = ? ORDER BY metric_name, rank_competition", [author_id])) if table_exists("ratings", run_id=run_id, dump_id=dump_id) else []
        works = []
        if table_exists("author_work", run_id=run_id, dump_id=dump_id) and table_exists("works", run_id=run_id, dump_id=dump_id):
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
    return {
        "author_id": author_id,
        "run_id": run_id,
        "dump_id": dump_id or _dump_id_for_run(run_id),
        "indices": indices,
        "ratings": ratings,
        "works": works,
    }


def work_detail(work_id: str, *, run_id: str = "", dump_id: str = "") -> dict[str, Any]:
    with connect_scope(run_id=run_id, dump_id=dump_id) as conn:
        works = _records(conn.execute("SELECT * FROM works WHERE work_id = ?", [work_id])) if table_exists("works", run_id=run_id, dump_id=dump_id) else []
        authorship_order = " ORDER BY author_seq" if "author_seq" in table_schema("authorships", run_id=run_id, dump_id=dump_id) else ""
        authorships = _records(conn.execute(f"SELECT * FROM authorships WHERE work_id = ?{authorship_order}", [work_id])) if table_exists("authorships", run_id=run_id, dump_id=dump_id) else []
        author_work = _records(conn.execute("SELECT * FROM author_work WHERE work_id = ? ORDER BY fraction_mode, author_display_name", [work_id])) if table_exists("author_work", run_id=run_id, dump_id=dump_id) else []
    return {
        "work_id": work_id,
        "run_id": run_id,
        "dump_id": dump_id or _dump_id_for_run(run_id),
        "work": works[0] if works else None,
        "authorships": authorships,
        "author_work": author_work,
    }


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
        "keyword_id",
        "keyword_display_name",
        "keyword_name",
        "text_search_query",
        "author_id",
        "author_orcid",
        "author_display_name",
        "author_name",
        "doi",
        "affiliation_mode",
        "institution_id",
        "source_id",
        "source_display_name",
        "source_name",
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
        if key == "filter_mode" and text == "all":
            continue
        if key == "affiliation_mode" and text == "historical" and not (filters.get("country_code") or filters.get("institution_id")):
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
    if "keyword_display_name" not in clean and clean.get("keyword_name"):
        clean["keyword_display_name"] = str(clean.pop("keyword_name"))
    else:
        clean.pop("keyword_name", None)
    if "author_display_name" not in clean and clean.get("author_name"):
        clean["author_display_name"] = str(clean.pop("author_name"))
    else:
        clean.pop("author_name", None)
    if "source_display_name" not in clean and clean.get("source_name"):
        clean["source_display_name"] = str(clean.pop("source_name"))
    else:
        clean.pop("source_name", None)
    return clean


def _validate_local_analysis_filters(filters: FilterSet) -> None:
    if filters.get("affiliation_mode") == "current" and (filters.get("country_code") or filters.get("institution_id")):
        raise ValueError(
            "affiliation_mode=current is not available for local works-dump analytics. "
            "Use affiliation_mode=historical or run a targeted Authors API enrichment workflow."
        )


def analysis_filter_warnings(filters: FilterSet | None = None, *, run_id: str = "", dump_id: str = "") -> list[dict[str, str]]:
    clean = _clean_filters(filters or {})
    warnings: list[dict[str, str]] = []
    if clean.get("affiliation_mode") == "current":
        warnings.append(
            {
                "code": "current_affiliation_requires_enrichment",
                "message": "Current affiliation is an Authors API enrichment concept; local analytics use historical works authorships.",
            }
        )
    if clean.get("filter_mode") == "keyword":
        warnings.append(
            {
                "code": "keyword_local_best_effort",
                "message": "OpenAlex keyword IDs are used for download pushdown; local analytics can only match normalized work topic/text fields.",
            }
        )
    if clean.get("filter_mode") == "topics_any" and not table_exists("work_topics", run_id=run_id, dump_id=dump_id):
        warnings.append(
            {
                "code": "topics_any_requires_work_topics",
                "message": "topics_any requires a local work_topics table; without it only primary-topic fields can be used.",
            }
        )
    return warnings


def _text_match_clause(work_fields: set[str], query: str | None) -> tuple[str, list[str]]:
    text = str(query or "").strip()
    if not text:
        return "", []
    searchable = [
        ("display_name", "w.display_name"),
        ("source_display_name", "w.source_display_name"),
        ("primary_topic_display_name", "w.primary_topic_display_name"),
        ("doi", "w.doi"),
    ]
    clauses = [f"{expr} ILIKE ?" for field, expr in searchable if field in work_fields]
    return (f"({' OR '.join(clauses)})", [f"%{text}%"] * len(clauses)) if clauses else ("", [])


def _doi_variants(value: str) -> list[str]:
    text = str(value or "").strip().lower().rstrip("/")
    if not text:
        return []
    text = text.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    text = text.removeprefix("https://dx.doi.org/").removeprefix("http://dx.doi.org/")
    text = text.removeprefix("doi:")
    return sorted({text, f"doi:{text}", f"https://doi.org/{text}", f"http://doi.org/{text}"})


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


def _metric_supported(metric: str, custom_metric_defs: list[dict[str, str]] | None = None, rows: list[dict[str, Any]] | None = None) -> bool:
    metric = str(metric or "").strip()
    if metric in INDEX_NUMERIC_FIELDS:
        return True
    if metric in custom_metrics.custom_metric_ids(custom_metric_defs):
        return True
    return bool(rows and any(metric in row for row in rows))


def _visible_metrics(rows: list[dict[str, Any]], custom_metric_defs: list[dict[str, str]] | None = None) -> list[str]:
    custom_ids = [definition["id"] for definition in custom_metric_defs or []]
    if not rows:
        return [*LINE_CHART_METRICS, *custom_ids]
    if any("two_year_mean_citedness" in row for row in rows):
        order = NATIVE_LINE_CHART_METRICS
    else:
        order = EXTENDED_LINE_CHART_METRICS
    return [metric for metric in (*order, *custom_ids) if any(metric in row for row in rows)]


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


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in str(value).strip())[:140] or "artifact"


def _run_dir(run_id: str) -> Path:
    return DATA / "runs" / _safe_id(run_id)


def _dump_table_path(dump_id: str, table: str) -> Path:
    return DATA / "tables" / _safe_id(_resolve_dump_id(dump_id)) / f"{table}.parquet"


def _resolve_dump_id(dump_id: str) -> str:
    raw = str(dump_id or "").strip()
    if not raw:
        return ""
    safe = _safe_id(raw)
    if (DATA / "tables" / safe).exists() or (DATA / "dumps" / safe).exists():
        return raw
    if not safe.startswith("dump_"):
        candidate = f"dump_{safe}"
        if (DATA / "tables" / candidate).exists() or (DATA / "dumps" / candidate).exists():
            return candidate
    return raw


def _run_table_path(run_id: str, table: str) -> Path | None:
    run_dir = _run_dir(run_id)
    candidates: list[Path] = []
    for suffix in (".parquet", ".csv"):
        candidates.append(run_dir / "tables" / f"{table}{suffix}")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _run_json_path(run_id: str, name: str) -> Path | None:
    run_dir = _run_dir(run_id)
    mapped = RUN_JSON_DOCS.get(name)
    if mapped:
        path = run_dir / mapped[0] / mapped[1]
        if path.exists():
            return path
    fallback = run_dir / "passports" / f"{name}.json"
    if fallback.exists():
        return fallback
    return None


def _run_metric_params(run_id: str) -> dict[str, Any]:
    defaults = {"analysis_year": 2026, "lrdi_p0": 5.0, "lrdi_lambda": 0.15, "source": "defaults"}
    candidates: list[tuple[Path, str]] = []
    if run_id:
        candidates.append((_run_dir(run_id) / "passports" / "calculation_passport.json", "run_calculation_passport"))
    for path, source in candidates:
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        lrdi_doc = doc.get("lrdi") if isinstance(doc, dict) else {}
        if not isinstance(lrdi_doc, dict):
            lrdi_doc = {}
        return {
            "analysis_year": _as_int(lrdi_doc.get("analysis_year") or doc.get("analysis_year") or defaults["analysis_year"]),
            "lrdi_p0": _as_float(lrdi_doc.get("p0") or doc.get("lrdi_p0") or defaults["lrdi_p0"]),
            "lrdi_lambda": _as_float(lrdi_doc.get("lambda") or doc.get("lrdi_lambda") or defaults["lrdi_lambda"]),
            "source": source,
        }
    if run_id:
        defaults["source"] = "defaults_missing_run_calculation_passport"
    return defaults


def _dump_id_for_run(run_id: str) -> str:
    path = _run_dir(run_id) / "metric_run.json"
    if not path.is_file():
        return ""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(doc.get("input_dump_id") or doc.get("dump_id") or "")


def _recent_run_for_dump(dump_id: str) -> str:
    target = _safe_id(_resolve_dump_id(str(dump_id or "")))
    if not target:
        return ""
    best_run_id = ""
    best_mtime = -1.0
    for metric_run in (DATA / "runs").glob("run_*/metric_run.json"):
        try:
            doc = json.loads(metric_run.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        run_dump_id = _safe_id(_resolve_dump_id(str(doc.get("input_dump_id") or doc.get("dump_id") or "")))
        if run_dump_id != target:
            continue
        try:
            mtime = metric_run.stat().st_mtime
        except OSError:
            mtime = 0.0
        if mtime >= best_mtime:
            best_mtime = mtime
            best_run_id = metric_run.parent.name
    return best_run_id
