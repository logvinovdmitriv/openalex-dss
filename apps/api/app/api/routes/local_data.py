from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from app.services import warehouse


router = APIRouter(tags=["local-data"])

LOCAL_DATA_KINDS: dict[str, str] = {
    "works": "Работы",
    "authorships": "Авторства",
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

    scoped_tables = {
        kind: {
            **(tables.get(kind) or {}),
            "kind": kind,
            "label": label,
        }
        for kind, label in LOCAL_DATA_KINDS.items()
    }
    return {
        "kinds": [{"kind": kind, "label": label} for kind, label in LOCAL_DATA_KINDS.items()],
        "tables": scoped_tables,
        "run_id": _first_table_value(scoped_tables, "run_id") or run_id,
        "dump_id": _first_table_value(scoped_tables, "dump_id") or dump_id,
    }


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
    return payload


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
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
