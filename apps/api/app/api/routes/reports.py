from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, Response

from app.services import reports


router = APIRouter(tags=["reports"])


@router.post("/reports/build")
def build_report(
    metric: str = "islv",
    fraction_mode: str = "strict_authors_count",
    run_id: str = "",
    dump_id: str = "",
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    return reports.build_report_bundle(metric=metric, fraction_mode=fraction_mode, limit=limit, run_id=run_id, dump_id=dump_id)


@router.get("/reports/bundle.json")
def report_bundle(run_id: str = "", dump_id: str = "") -> Response:
    payload = reports.report_bundle_json(run_id=run_id, dump_id=dump_id)
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="openalex_dss_report_bundle.json"'},
    )
