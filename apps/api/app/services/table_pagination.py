from __future__ import annotations

import base64
import json
from typing import Any


def stable_order_sql(fields: list[str] | set[str], sort: str, direction: str = "desc") -> str:
    order = [f"{quote_sql_identifier(field)} {field_direction}" for field, field_direction in stable_order_fields(fields, sort, direction)]
    return "ORDER BY " + ", ".join(order)


def stable_order_fields(fields: list[str] | set[str], sort: str, direction: str = "desc") -> list[tuple[str, str]]:
    field_set = set(fields)
    if sort not in field_set:
        return []
    safe_direction = "DESC" if str(direction or "desc").strip().lower() == "desc" else "ASC"
    order: list[tuple[str, str]] = [(sort, safe_direction)]
    for tie_field, tie_direction in (("c", "DESC"), ("p", "DESC"), ("author_display_name", "ASC"), ("author_id", "ASC"), ("work_id", "ASC")):
        if tie_field in field_set and tie_field != sort:
            order.append((tie_field, tie_direction))
    return order


def decode_page_cursor(token: str) -> dict[str, Any]:
    raw = str(token or "").strip()
    if not raw:
        return {}
    try:
        padding = "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode((raw + padding).encode("ascii")).decode("utf-8"))
    except (ValueError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {**payload, "token": raw}


def encode_next_cursor(row: dict[str, Any], fields: list[str] | set[str], *, sort: str, direction: str) -> str | None:
    order_fields = stable_order_fields(fields, sort, direction)
    if not order_fields:
        return None
    values = {field: cursor_value(row.get(field)) for field, _ in order_fields if field in row}
    if not values:
        return None
    payload = {
        "v": 1,
        "sort": sort,
        "direction": "asc" if str(direction or "").strip().lower() == "asc" else "desc",
        "values": values,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def cursor_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def keyset_where_clause(fields: list[str] | set[str], sort: str, direction: str, values: dict[str, Any]) -> tuple[str, list[Any]]:
    order_fields = stable_order_fields(fields, sort, direction)
    if not order_fields or not isinstance(values, dict):
        return "", []
    clauses: list[str] = []
    args: list[Any] = []
    equality_prefix: list[str] = []
    for field, field_direction in order_fields:
        if field not in values:
            break
        column = quote_sql_identifier(field)
        comparator = ">" if field_direction == "ASC" else "<"
        prefix = " AND ".join(equality_prefix)
        clause = f"{column} {comparator} ?"
        clauses.append(f"({prefix} AND {clause})" if prefix else f"({clause})")
        args.extend([*values_for_prefix(values, order_fields[: len(equality_prefix)]), values[field]])
        equality_prefix.append(f"{column} = ?")
    if not clauses:
        return "", []
    return "(" + " OR ".join(clauses) + ")", args


def values_for_prefix(values: dict[str, Any], prefix_fields: list[tuple[str, str]]) -> list[Any]:
    return [values[field] for field, _direction in prefix_fields if field in values]


def quote_sql_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'
