from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from app.application import scientometric_workflow
from app.api.query_contracts import AnalysisFilterQuery
from app.services import cohorts, custom_metrics, warehouse


router = APIRouter(tags=["reports"])


@router.post("/reports/build")
def build_report(
    metric: str = "h",
    fraction_mode: str = "strict_authors_count",
    run_id: str = "",
    dump_id: str = "",
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
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
    limit: int = Query(50, ge=0, le=500_000),
    scientometric_metrics: str = "p,c,cpp,h,i10,g",
    baseline_metric: str = "h",
    rank_top_n: int = Query(100, ge=0, le=500_000),
    data_filters: str = "",
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = Query(0, ge=0, le=500_000),
    custom_metric_defs: str = "",
) -> dict[str, Any]:
    filters = AnalysisFilterQuery(
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
    ).to_filters()
    try:
        return scientometric_workflow.build_report_bundle(
            metric=metric,
            fraction_mode=fraction_mode,
            limit=limit,
            run_id=run_id,
            dump_id=dump_id,
            filters=filters,
            cohort_id=cohort_id,
            cohort_filter_policy=cohort_filter_policy,
            scientometric_metrics=scientometric_metrics,
            baseline_metric=baseline_metric,
            rank_top_n=rank_top_n,
            data_filters=warehouse.parse_column_filters(data_filters),
            data_sort=data_sort,
            data_direction=data_direction,
            data_limit=data_limit,
            custom_metric_defs=custom_metrics.parse_custom_metrics(custom_metric_defs),
        )
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Группа авторов не найдена") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/reports/bundle.json")
def report_bundle(
    run_id: str = "",
    dump_id: str = "",
    metric: str = "h",
    fraction_mode: str = "strict_authors_count",
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
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
    limit: int = Query(50, ge=0, le=500_000),
    scientometric_metrics: str = "p,c,cpp,h,i10,g",
    baseline_metric: str = "h",
    rank_top_n: int = Query(100, ge=0, le=500_000),
    data_filters: str = "",
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = Query(0, ge=0, le=500_000),
    custom_metric_defs: str = "",
) -> Response:
    filters = AnalysisFilterQuery(
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
    ).to_filters()
    try:
        payload = scientometric_workflow.report_bundle_json(
            metric=metric,
            fraction_mode=fraction_mode,
            limit=limit,
            run_id=run_id,
            dump_id=dump_id,
            filters=filters,
            cohort_id=cohort_id,
            cohort_filter_policy=cohort_filter_policy,
            scientometric_metrics=scientometric_metrics,
            baseline_metric=baseline_metric,
            rank_top_n=rank_top_n,
            data_filters=warehouse.parse_column_filters(data_filters),
            data_sort=data_sort,
            data_direction=data_direction,
            data_limit=data_limit,
            custom_metric_defs=custom_metrics.parse_custom_metrics(custom_metric_defs),
        )
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Группа авторов не найдена") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="openalex_dss_report_bundle.json"'},
    )
