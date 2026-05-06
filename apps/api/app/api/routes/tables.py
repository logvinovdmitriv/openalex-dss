from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from app.services import warehouse


router = APIRouter(tags=["tables"])


@router.get("/tables/{table}")
def table(
    table: str,
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
    try:
        return warehouse.query_table(table, run_id=run_id, dump_id=dump_id, q=q, fraction_mode=fraction_mode, metric=metric, author_id=author_id, work_id=work_id, sort=sort, direction=direction, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/exports/{table}.csv")
def export_csv(
    table: str,
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
    try:
        data = warehouse.export_table_csv(table, run_id=run_id, dump_id=dump_id, q=q, fraction_mode=fraction_mode, metric=metric, author_id=author_id, work_id=work_id, sort=sort, direction=direction, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"openalex_dss_{table}.csv"
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/exports/{table}.json")
def export_json(
    table: str,
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
    try:
        payload = warehouse.export_table(table, run_id=run_id, dump_id=dump_id, q=q, fraction_mode=fraction_mode, metric=metric, author_id=author_id, work_id=work_id, sort=sort, direction=direction, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"openalex_dss_{table}.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
