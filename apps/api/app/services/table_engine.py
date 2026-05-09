from __future__ import annotations

from typing import Any

import duckdb


def registered_fields(conn: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    try:
        return [row[1] for row in conn.execute(f"PRAGMA table_info('{table}')").fetchall()]
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


def records(result: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    columns = [desc[0] for desc in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]
