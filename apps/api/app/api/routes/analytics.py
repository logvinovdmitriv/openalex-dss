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
    filter_mode: str = "",
    subject_level: str = "",
    subject_id: str = "",
    keyword_id: str = "",
    keyword_display_name: str = "",
    keyword_name: str = "",
    text_search_query: str = "",
    author_id: str = "",
    author_orcid: str = "",
    author_display_name: str = "",
    author_name: str = "",
    doi: str = "",
    affiliation_mode: str = "",
    institution_id: str = "",
    source_id: str = "",
    source_display_name: str = "",
    source_name: str = "",
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
        filter_mode=filter_mode,
        subject_level=subject_level,
        subject_id=subject_id,
        keyword_id=keyword_id,
        keyword_display_name=keyword_display_name or keyword_name,
        text_search_query=text_search_query,
        author_id=author_id,
        author_orcid=author_orcid,
        author_display_name=author_display_name or author_name,
        doi=doi,
        affiliation_mode=affiliation_mode,
        institution_id=institution_id,
        source_id=source_id,
        source_display_name=source_display_name or source_name,
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
        filter_warnings = warehouse.analysis_filter_warnings(filters, run_id=run_id, dump_id=dump_id)
        bundle = warehouse.metric_bundle(fraction_mode, metric, filters, limit=limit, run_id=run_id, dump_id=dump_id)
        distribution = bundle["distribution"]
        top = bundle["ranking"]
        metric_lines = bundle["line_series"]
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
        "metric_params": distribution.get("metric_params") or top.get("metric_params"),
        "filters": filters,
        "filter_warnings": filter_warnings,
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
    filter_mode: str = "",
    subject_level: str = "",
    subject_id: str = "",
    keyword_id: str = "",
    keyword_display_name: str = "",
    keyword_name: str = "",
    text_search_query: str = "",
    author_id: str = "",
    author_orcid: str = "",
    author_display_name: str = "",
    author_name: str = "",
    doi: str = "",
    affiliation_mode: str = "",
    institution_id: str = "",
    source_id: str = "",
    source_display_name: str = "",
    source_name: str = "",
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
        filter_mode=filter_mode,
        subject_level=subject_level,
        subject_id=subject_id,
        keyword_id=keyword_id,
        keyword_display_name=keyword_display_name or keyword_name,
        text_search_query=text_search_query,
        author_id=author_id,
        author_orcid=author_orcid,
        author_display_name=author_display_name or author_name,
        doi=doi,
        affiliation_mode=affiliation_mode,
        institution_id=institution_id,
        source_id=source_id,
        source_display_name=source_display_name or source_name,
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
        payload = warehouse.metric_distribution(fraction_mode, metric, filters, run_id=run_id, dump_id=dump_id)
        payload["filter_warnings"] = warehouse.analysis_filter_warnings(filters, run_id=run_id, dump_id=dump_id)
        return payload
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/analytics/ranking")
def ranking_json(
    run_id: str = "",
    dump_id: str = "",
    fraction_mode: str = "strict_authors_count",
    metric: str = "islv",
    country_code: str = "",
    filter_mode: str = "",
    subject_level: str = "",
    subject_id: str = "",
    keyword_id: str = "",
    keyword_display_name: str = "",
    keyword_name: str = "",
    text_search_query: str = "",
    author_id: str = "",
    author_orcid: str = "",
    author_display_name: str = "",
    author_name: str = "",
    doi: str = "",
    affiliation_mode: str = "",
    institution_id: str = "",
    source_id: str = "",
    source_display_name: str = "",
    source_name: str = "",
    source_type: str = "",
    language: str = "",
    open_access_is_oa: str = "",
    has_abstract: str = "",
    min_cited_by_count: int = 0,
    from_publication_date: str = "",
    to_publication_date: str = "",
    work_type: str = "",
    limit: int = Query(100, ge=1, le=500_000),
) -> dict[str, Any]:
    filters = _slice_filters(
        country_code=country_code,
        filter_mode=filter_mode,
        subject_level=subject_level,
        subject_id=subject_id,
        keyword_id=keyword_id,
        keyword_display_name=keyword_display_name or keyword_name,
        text_search_query=text_search_query,
        author_id=author_id,
        author_orcid=author_orcid,
        author_display_name=author_display_name or author_name,
        doi=doi,
        affiliation_mode=affiliation_mode,
        institution_id=institution_id,
        source_id=source_id,
        source_display_name=source_display_name or source_name,
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
        payload["filter_warnings"] = warehouse.analysis_filter_warnings(filters, run_id=run_id, dump_id=dump_id)
        return payload
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/analytics/ranking.csv")
def ranking_csv(
    run_id: str = "",
    dump_id: str = "",
    fraction_mode: str = "strict_authors_count",
    metric: str = "islv",
    country_code: str = "",
    filter_mode: str = "",
    subject_level: str = "",
    subject_id: str = "",
    keyword_id: str = "",
    keyword_display_name: str = "",
    keyword_name: str = "",
    text_search_query: str = "",
    author_id: str = "",
    author_orcid: str = "",
    author_display_name: str = "",
    author_name: str = "",
    doi: str = "",
    affiliation_mode: str = "",
    institution_id: str = "",
    source_id: str = "",
    source_display_name: str = "",
    source_name: str = "",
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
    try:
        payload = ranking_json(
            run_id=run_id,
            dump_id=dump_id,
            fraction_mode=fraction_mode,
            metric=metric,
            country_code=country_code,
            filter_mode=filter_mode,
            subject_level=subject_level,
            subject_id=subject_id,
            keyword_id=keyword_id,
            keyword_display_name=keyword_display_name,
            keyword_name=keyword_name,
            text_search_query=text_search_query,
            author_id=author_id,
            author_orcid=author_orcid,
            author_display_name=author_display_name,
            author_name=author_name,
            doi=doi,
            affiliation_mode=affiliation_mode,
            institution_id=institution_id,
            source_id=source_id,
            source_display_name=source_display_name,
            source_name=source_name,
            source_type=source_type,
            language=language,
            open_access_is_oa=open_access_is_oa,
            has_abstract=has_abstract,
            min_cited_by_count=min_cited_by_count,
            from_publication_date=from_publication_date,
            to_publication_date=to_publication_date,
            work_type=work_type,
            limit=limit,
        )
    except HTTPException:
        raise
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
    filter_mode: str = "",
    subject_level: str = "",
    subject_id: str = "",
    keyword_id: str = "",
    keyword_display_name: str = "",
    text_search_query: str = "",
    author_id: str = "",
    author_orcid: str = "",
    author_display_name: str = "",
    doi: str = "",
    affiliation_mode: str = "",
    institution_id: str = "",
    source_id: str = "",
    source_display_name: str = "",
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
        "filter_mode": filter_mode.strip(),
        "subject_level": subject_level.strip(),
        "subject_id": subject_id.strip(),
        "keyword_id": keyword_id.strip(),
        "keyword_display_name": keyword_display_name.strip(),
        "text_search_query": text_search_query.strip(),
        "author_id": author_id.strip(),
        "author_orcid": author_orcid.strip(),
        "author_display_name": author_display_name.strip(),
        "doi": doi.strip(),
        "affiliation_mode": affiliation_mode.strip(),
        "institution_id": institution_id.strip(),
        "source_id": source_id.strip(),
        "source_display_name": source_display_name.strip(),
        "source_type": source_type.strip(),
        "language": language.strip(),
        "open_access_is_oa": open_access_is_oa.strip(),
        "has_abstract": has_abstract.strip(),
        "min_cited_by_count": str(min_cited_by_count) if min_cited_by_count else "",
        "from_publication_date": from_publication_date.strip(),
        "to_publication_date": to_publication_date.strip(),
        "work_type": work_type.strip(),
    }
