from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.services import warehouse


router = APIRouter(tags=["local-data"])

LOCAL_DATA_KINDS: dict[str, str] = {
    "indices": "Авторы и индексы",
    "ratings": "Рейтинговые позиции",
    "works": "Работы",
    "authorships": "Авторства",
    "work_topics": "Темы работ",
    "author_work": "Автор-работа",
}

PREVIEW_DEFAULT_ROWS = 100
PREVIEW_MAX_ROWS = 1_000


@router.get("/local-data/summary")
def local_data_summary(run_id: str = "", dump_id: str = "") -> dict[str, Any]:
    _require_local_data_scope(run_id=run_id, dump_id=dump_id)
    try:
        tables = warehouse.list_tables(run_id=run_id, dump_id=dump_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scoped_tables = {kind: _summary_entry(kind, label, tables.get(kind) or {}) for kind, label in LOCAL_DATA_KINDS.items()}
    available_kinds = [
        {"kind": kind, "label": label}
        for kind, label in LOCAL_DATA_KINDS.items()
        if bool(scoped_tables.get(kind, {}).get("exists"))
    ]
    payload = {
        "kinds": available_kinds,
        "tables": scoped_tables,
        "run_id": _first_table_value(scoped_tables, "run_id") or run_id,
        "dump_id": _first_table_value(scoped_tables, "dump_id") or dump_id,
    }
    return _annotate_local_data_payload(payload, run_id=run_id, dump_id=dump_id)


@router.get("/local-data/preview")
def local_data_preview(
    kind: str,
    run_id: str = "",
    dump_id: str = "",
    q: str = "",
    fraction_mode: str = "",
    metric: str = "",
    author_id: str = "",
    work_id: str = "",
    data_filters: str = "",
    sort: str = "",
    direction: str = "desc",
    limit: int = Query(100, ge=0, le=500_000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    table = _local_data_kind(kind)
    _require_local_data_scope(run_id=run_id, dump_id=dump_id)
    _require_existing_table(table, run_id=run_id, dump_id=dump_id)
    try:
        parsed_data_filters = warehouse.parse_column_filters(data_filters)
        effective_limit = _preview_limit(limit)
        payload = warehouse.query_table(
            table,
            run_id=run_id,
            dump_id=dump_id,
            q=q,
            fraction_mode=fraction_mode,
            metric=metric,
            author_id=author_id,
            work_id=work_id,
            **({"data_filters": parsed_data_filters} if parsed_data_filters else {}),
            sort=sort,
            direction=direction,
            limit=effective_limit,
            offset=offset,
            include_total=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload["kind"] = table
    payload["label"] = LOCAL_DATA_KINDS[table]
    payload["requested_limit"] = limit
    payload["preview_limit"] = payload.get("limit", effective_limit)
    payload["truncated_for_preview"] = bool(limit <= 0 or limit > effective_limit)
    return _annotate_local_data_payload(payload, run_id=run_id, dump_id=dump_id)


@router.get("/local-data/preview.csv")
def local_data_preview_csv(
    kind: str,
    run_id: str = "",
    dump_id: str = "",
    q: str = "",
    fraction_mode: str = "",
    metric: str = "",
    author_id: str = "",
    work_id: str = "",
    data_filters: str = "",
    sort: str = "",
    direction: str = "desc",
    limit: int = Query(100_000, ge=0, le=500_000),
    offset: int = Query(0, ge=0),
) -> StreamingResponse:
    table = _local_data_kind(kind)
    _require_local_data_scope(run_id=run_id, dump_id=dump_id)
    _require_existing_table(table, run_id=run_id, dump_id=dump_id)
    try:
        parsed_data_filters = warehouse.parse_column_filters(data_filters)
        stream = warehouse.iter_table_csv(
            table,
            run_id=run_id,
            dump_id=dump_id,
            q=q,
            fraction_mode=fraction_mode,
            metric=metric,
            author_id=author_id,
            work_id=work_id,
            **({"data_filters": parsed_data_filters} if parsed_data_filters else {}),
            sort=sort,
            direction=direction,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"openalex_dss_local_data_{table}.csv"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        **_local_data_scope_headers(run_id=run_id, dump_id=dump_id),
    }
    return StreamingResponse(
        stream,
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


def _local_data_kind(kind: str) -> str:
    value = str(kind or "").strip()
    if value not in LOCAL_DATA_KINDS:
        allowed = ", ".join(LOCAL_DATA_KINDS)
        raise HTTPException(status_code=400, detail=f"Unsupported local data kind: {value or '<empty>'}. Allowed kinds: {allowed}")
    return value


def _preview_limit(limit: int) -> int:
    if int(limit or 0) <= 0:
        return PREVIEW_DEFAULT_ROWS
    return max(1, min(int(limit), PREVIEW_MAX_ROWS))


def _require_existing_table(kind: str, *, run_id: str = "", dump_id: str = "") -> None:
    try:
        exists = warehouse.table_exists(kind, run_id=run_id, dump_id=dump_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not exists:
        raise HTTPException(status_code=404, detail=f"Таблица «{LOCAL_DATA_KINDS.get(kind, kind)}» отсутствует в выбранном срезе.")


def _first_table_value(tables: dict[str, dict[str, Any]], key: str) -> str:
    for table in tables.values():
        value = str(table.get(key) or "").strip()
        if value:
            return value
    return ""


def _summary_entry(kind: str, label: str, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        **raw,
        "kind": kind,
        "label": label,
        "exists": bool(raw.get("exists")),
        "rows": int(raw.get("rows") or 0),
    }


def _local_data_scope_metadata(*, run_id: str = "", dump_id: str = "") -> dict[str, Any]:
    _require_local_data_scope(run_id=run_id, dump_id=dump_id)
    return {"scope_status": "explicit_scope", "reproducible": True}


def _annotate_local_data_payload(payload: dict[str, Any], *, run_id: str = "", dump_id: str = "") -> dict[str, Any]:
    metadata = _local_data_scope_metadata(run_id=run_id, dump_id=dump_id)
    payload.update(metadata)
    existing = payload.get("warnings")
    warnings = list(existing) if isinstance(existing, list) else ([] if existing is None else [existing])
    payload["warnings"] = warnings
    return payload


def _local_data_scope_headers(*, run_id: str = "", dump_id: str = "") -> dict[str, str]:
    metadata = _local_data_scope_metadata(run_id=run_id, dump_id=dump_id)
    headers = {
        "X-OpenAlex-DSS-Scope-Status": str(metadata["scope_status"]),
        "X-OpenAlex-DSS-Reproducible": "true" if metadata["reproducible"] else "false",
    }
    return headers


def _require_local_data_scope(*, run_id: str = "", dump_id: str = "") -> None:
    if str(run_id or "").strip() or str(dump_id or "").strip():
        return
    raise HTTPException(status_code=400, detail="run_id or dump_id is required for local-data access.")
