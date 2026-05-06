from __future__ import annotations

import csv
from io import StringIO
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from app.services import warehouse


router = APIRouter(tags=["analytics"])


@router.get("/analytics")
def analytics(
    run_id: str = "",
    dump_id: str = "",
    fraction_mode: str = "strict_authors_count",
    metric: str = "islv",
    country_code: str = "",
    subject_level: str = "",
    subject_id: str = "",
    author_id: str = "",
    author_display_name: str = "",
    author_name: str = "",
    institution_id: str = "",
    source_id: str = "",
    source_type: str = "",
    language: str = "",
    open_access_is_oa: str = "",
    has_abstract: str = "",
    min_cited_by_count: int = 0,
    from_publication_date: str = "",
    to_publication_date: str = "",
    work_type: str = "",
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    filters = _slice_filters(
        country_code=country_code,
        subject_level=subject_level,
        subject_id=subject_id,
        author_id=author_id,
        author_display_name=author_display_name or author_name,
        institution_id=institution_id,
        source_id=source_id,
        source_type=source_type,
        language=language,
        open_access_is_oa=open_access_is_oa,
        has_abstract=has_abstract,
        min_cited_by_count=min_cited_by_count,
        from_publication_date=from_publication_date,
        to_publication_date=to_publication_date,
        work_type=work_type,
    )
    stats = warehouse.read_json_doc("stats", run_id=run_id) or {}
    theory = warehouse.read_json_doc("theory", run_id=run_id) or {}
    try:
        distribution = warehouse.metric_distribution(fraction_mode, metric, filters, run_id=run_id, dump_id=dump_id)
        top = warehouse.metric_ranking(fraction_mode, metric, filters, limit=limit, max_limit=200, run_id=run_id, dump_id=dump_id)
        metric_lines = warehouse.metric_line_series(fraction_mode, filters, rank_metric=metric, limit=40, run_id=run_id, dump_id=dump_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    run_global_stats = {
        "metric_summary": stats.get("fraction_modes", {}).get(fraction_mode, {}).get("metrics", {}).get(metric),
        "spearman": stats.get("fraction_modes", {}).get(fraction_mode, {}).get("spearman_on_competition_ranks"),
        "top_overlap": stats.get("fraction_modes", {}).get(fraction_mode, {}).get("top_overlap"),
        "scope": "full_run_precomputed",
        "note": "These statistics come from the full selected run; filtered_distribution and filtered_top are recomputed after current filters.",
    }
    return {
        "fraction_mode": fraction_mode,
        "metric": metric,
        "run_id": run_id,
        "dump_id": dump_id or top.get("dump_id") or distribution.get("dump_id"),
        "metric_scope": "filtered_recomputed",
        "percentile_scope": "current filtered author set",
        "filters": filters,
        "filtered_distribution": distribution,
        "filtered_top": top,
        "filtered_metric_lines": metric_lines,
        "run_global_stats": run_global_stats,
        "distribution": distribution,
        "metric_summary": run_global_stats["metric_summary"],
        "spearman": run_global_stats["spearman"],
        "top_overlap": run_global_stats["top_overlap"],
        "theory": theory,
        "top": top["rows"],
        "top_table": top,
        "metric_lines": metric_lines,
    }


@router.get("/analytics/distribution")
def distribution(
    run_id: str = "",
    dump_id: str = "",
    fraction_mode: str = "strict_authors_count",
    metric: str = "islv",
    country_code: str = "",
    subject_level: str = "",
    subject_id: str = "",
    author_id: str = "",
    author_display_name: str = "",
    author_name: str = "",
    institution_id: str = "",
    source_id: str = "",
    source_type: str = "",
    language: str = "",
    open_access_is_oa: str = "",
    has_abstract: str = "",
    min_cited_by_count: int = 0,
    from_publication_date: str = "",
    to_publication_date: str = "",
    work_type: str = "",
) -> dict[str, Any]:
    filters = _slice_filters(
        country_code=country_code,
        subject_level=subject_level,
        subject_id=subject_id,
        author_id=author_id,
        author_display_name=author_display_name or author_name,
        institution_id=institution_id,
        source_id=source_id,
        source_type=source_type,
        language=language,
        open_access_is_oa=open_access_is_oa,
        has_abstract=has_abstract,
        min_cited_by_count=min_cited_by_count,
        from_publication_date=from_publication_date,
        to_publication_date=to_publication_date,
        work_type=work_type,
    )
    try:
        return warehouse.metric_distribution(fraction_mode, metric, filters, run_id=run_id, dump_id=dump_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/analytics/ranking.csv")
def ranking_csv(
    run_id: str = "",
    dump_id: str = "",
    fraction_mode: str = "strict_authors_count",
    metric: str = "islv",
    country_code: str = "",
    subject_level: str = "",
    subject_id: str = "",
    author_id: str = "",
    author_display_name: str = "",
    author_name: str = "",
    institution_id: str = "",
    source_id: str = "",
    source_type: str = "",
    language: str = "",
    open_access_is_oa: str = "",
    has_abstract: str = "",
    min_cited_by_count: int = 0,
    from_publication_date: str = "",
    to_publication_date: str = "",
    work_type: str = "",
    limit: int = Query(100_000, ge=1, le=500_000),
) -> Response:
    filters = _slice_filters(
        country_code=country_code,
        subject_level=subject_level,
        subject_id=subject_id,
        author_id=author_id,
        author_display_name=author_display_name or author_name,
        institution_id=institution_id,
        source_id=source_id,
        source_type=source_type,
        language=language,
        open_access_is_oa=open_access_is_oa,
        has_abstract=has_abstract,
        min_cited_by_count=min_cited_by_count,
        from_publication_date=from_publication_date,
        to_publication_date=to_publication_date,
        work_type=work_type,
    )
    try:
        payload = warehouse.metric_ranking(fraction_mode, metric, filters, limit=limit, max_limit=500_000, run_id=run_id, dump_id=dump_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=payload["fields"], extrasaction="ignore")
    writer.writeheader()
    writer.writerows(payload["rows"])
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="openalex_dss_filtered_rating.csv"'},
    )


def _slice_filters(
    *,
    country_code: str = "",
    subject_level: str = "",
    subject_id: str = "",
    author_id: str = "",
    author_display_name: str = "",
    institution_id: str = "",
    source_id: str = "",
    source_type: str = "",
    language: str = "",
    open_access_is_oa: str = "",
    has_abstract: str = "",
    min_cited_by_count: int = 0,
    from_publication_date: str = "",
    to_publication_date: str = "",
    work_type: str = "",
) -> dict[str, str]:
    return {
        "country_code": country_code.strip().upper(),
        "subject_level": subject_level.strip(),
        "subject_id": subject_id.strip(),
        "author_id": author_id.strip(),
        "author_display_name": author_display_name.strip(),
        "institution_id": institution_id.strip(),
        "source_id": source_id.strip(),
        "source_type": source_type.strip(),
        "language": language.strip(),
        "open_access_is_oa": open_access_is_oa.strip(),
        "has_abstract": has_abstract.strip(),
        "min_cited_by_count": str(min_cited_by_count) if min_cited_by_count else "",
        "from_publication_date": from_publication_date.strip(),
        "to_publication_date": to_publication_date.strip(),
        "work_type": work_type.strip(),
    }
