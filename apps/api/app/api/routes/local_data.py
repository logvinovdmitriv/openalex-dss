from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from app.services import warehouse


router = APIRouter(tags=["local-data"])

LOCAL_DATA_KINDS: dict[str, str] = {
    "works": "Работы",
    "authorships": "Авторства",
    "work_topics": "Темы работ",
    "author_work": "Автор-работа",
    "indices": "Индексы авторов",
    "ratings": "Позиции рейтингов",
}


@router.get("/local-data/summary")
def local_data_summary(run_id: str = "", dump_id: str = "") -> dict[str, Any]:
    try:
        tables = warehouse.list_tables(run_id=run_id, dump_id=dump_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scoped_tables = {kind: _summary_entry(kind, label, tables.get(kind) or {}) for kind, label in LOCAL_DATA_KINDS.items()}
    payload = {
        "kinds": [{"kind": kind, "label": label} for kind, label in LOCAL_DATA_KINDS.items()],
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
    sort: str = "",
    direction: str = "desc",
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    table = _local_data_kind(kind)
    try:
        payload = warehouse.query_table(
            table,
            run_id=run_id,
            dump_id=dump_id,
            q=q,
            fraction_mode=fraction_mode,
            metric=metric,
            author_id=author_id,
            work_id=work_id,
            sort=sort,
            direction=direction,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload["kind"] = table
    payload["label"] = LOCAL_DATA_KINDS[table]
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
    sort: str = "",
    direction: str = "desc",
    limit: int = Query(100_000, ge=1, le=500_000),
    offset: int = Query(0, ge=0),
) -> Response:
    table = _local_data_kind(kind)
    try:
        data = warehouse.export_table_csv(
            table,
            run_id=run_id,
            dump_id=dump_id,
            q=q,
            fraction_mode=fraction_mode,
            metric=metric,
            author_id=author_id,
            work_id=work_id,
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
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


def _local_data_kind(kind: str) -> str:
    value = str(kind or "").strip()
    if value not in LOCAL_DATA_KINDS:
        allowed = ", ".join(LOCAL_DATA_KINDS)
        raise HTTPException(status_code=400, detail=f"Unsupported local data kind: {value or '<empty>'}. Allowed kinds: {allowed}")
    return value


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
    if str(run_id or "").strip() or str(dump_id or "").strip():
        return {"scope_status": "explicit_scope", "reproducible": True, "scope_warnings": []}
    return {
        "scope_status": "implicit_latest_preview",
        "reproducible": False,
        "scope_warnings": [
            (
                "No run_id or dump_id was provided; this local-data preview uses compatibility "
                "latest-view data and is not suitable for final analysis."
            )
        ],
    }


def _annotate_local_data_payload(payload: dict[str, Any], *, run_id: str = "", dump_id: str = "") -> dict[str, Any]:
    metadata = _local_data_scope_metadata(run_id=run_id, dump_id=dump_id)
    payload.update(metadata)
    existing = payload.get("warnings")
    warnings = list(existing) if isinstance(existing, list) else ([] if existing is None else [existing])
    for warning in metadata["scope_warnings"]:
        if warning not in warnings:
            warnings.append(warning)
    payload["warnings"] = warnings
    return payload


def _local_data_scope_headers(*, run_id: str = "", dump_id: str = "") -> dict[str, str]:
    metadata = _local_data_scope_metadata(run_id=run_id, dump_id=dump_id)
    headers = {
        "X-OpenAlex-DSS-Scope-Status": str(metadata["scope_status"]),
        "X-OpenAlex-DSS-Reproducible": "true" if metadata["reproducible"] else "false",
    }
    warnings = metadata["scope_warnings"]
    if warnings:
        headers["X-OpenAlex-DSS-Scope-Warning"] = "; ".join(str(warning) for warning in warnings)
    return headers
