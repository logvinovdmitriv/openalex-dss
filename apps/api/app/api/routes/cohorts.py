from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.schemas import AuthorCohortCreateRequest
from app.services.analysis_filters import build_analysis_filters
from app.services import cohorts


router = APIRouter(tags=["cohorts"])


@router.post("/cohorts")
def create_cohort(payload: AuthorCohortCreateRequest) -> dict[str, Any]:
    try:
        return cohorts.create_cohort(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cohorts")
def list_cohorts(limit: int = Query(50, ge=1, le=250)) -> dict[str, Any]:
    return cohorts.list_cohorts(limit=limit)


@router.get("/cohorts/{cohort_id}")
def get_cohort(cohort_id: str) -> dict[str, Any]:
    try:
        return cohorts.get_cohort(cohort_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc


@router.get("/cohorts/{cohort_id}/statistics")
@router.post("/cohorts/{cohort_id}/statistics")
def cohort_statistics(
    cohort_id: str,
    run_id: str = "",
    dump_id: str = "",
    fraction_mode: str = "",
    cohort_filter_policy: str = "membership",
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
    filters = _analysis_filters(
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
        return cohorts.cohort_statistics(cohort_id, run_id=run_id, dump_id=dump_id, fraction_mode=fraction_mode, filters=filters, filter_policy=cohort_filter_policy)
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cohorts/{cohort_id}/author-metrics.json")
def cohort_author_metrics_json(
    cohort_id: str,
    run_id: str = "",
    dump_id: str = "",
    fraction_mode: str = "",
    cohort_filter_policy: str = "membership",
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
    metric: str = "",
    limit: int = Query(100_000, ge=1, le=500_000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    filters = _analysis_filters(
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
        return cohorts.cohort_author_metrics(cohort_id, run_id=run_id, dump_id=dump_id, fraction_mode=fraction_mode, filters=filters, filter_policy=cohort_filter_policy, metric=metric, limit=limit, offset=offset)
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cohorts/{cohort_id}/author-metrics.csv")
def cohort_author_metrics_csv(
    cohort_id: str,
    run_id: str = "",
    dump_id: str = "",
    fraction_mode: str = "",
    cohort_filter_policy: str = "membership",
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
    metric: str = "",
    limit: int = Query(100_000, ge=1, le=500_000),
    offset: int = Query(0, ge=0),
) -> Response:
    filters = _analysis_filters(
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
        data = cohorts.cohort_author_metrics_csv(cohort_id, run_id=run_id, dump_id=dump_id, fraction_mode=fraction_mode, filters=filters, filter_policy=cohort_filter_policy, metric=metric, limit=limit, offset=offset)
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="openalex_dss_{cohort_id}_author_metrics.csv"'},
    )


def _analysis_filters(**kwargs: Any) -> dict[str, str]:
    return build_analysis_filters(**kwargs)
