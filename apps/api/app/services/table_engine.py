from __future__ import annotations

from typing import Any

import duckdb


def registered_fields(conn: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    try:
        return [row[1] for row in conn.execute(f"PRAGMA table_info('{table}')").fetchmany(512)]
    except duckdb.Error:
        return []


def select_existing_sql(fields: list[str], preferred: tuple[str, ...], *, alias: str = "") -> str:
    selected = [field for field in preferred if field in fields] or list(fields)
    prefix = f"{alias}." if alias else ""
    return ", ".join(f"{prefix}{field}" for field in selected)


def order_sql(fields: list[str], preferred: tuple[str, ...], *, alias: str = "", direction: str = "ASC") -> str:
    selected = [field for field in preferred if field in fields]
    if not selected:
        return ""
    prefix = f"{alias}." if alias else ""
    safe_direction = "DESC" if str(direction).upper() == "DESC" else "ASC"
    return "ORDER BY " + ", ".join(f"{prefix}{field} {safe_direction}" for field in selected)


def records(result: duckdb.DuckDBPyConnection, *, max_rows: int = 100_000) -> list[dict[str, Any]]:
    """Read a bounded result set into dictionaries.

    Large user-facing tables should use DuckDB LIMIT/OFFSET or streaming exports before
    calling this helper. The bound makes accidental full-table fetches fail early.
    """
    columns = [desc[0] for desc in result.description]
    limit = max(1, int(max_rows or 1))
    rows = result.fetchmany(limit + 1)
    if len(rows) > limit:
        raise ValueError(f"Result set is too large for in-memory records helper; limit is {limit} rows.")
    return [dict(zip(columns, row)) for row in rows]
