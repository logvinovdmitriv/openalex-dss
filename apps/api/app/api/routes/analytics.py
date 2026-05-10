from __future__ import annotations

import csv
import json
from io import StringIO
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.application import scientometric_workflow
from app.api.query_contracts import AnalysisFilterQuery, DataSelectionQuery, ScopeQuery
from app.services import cohorts, custom_metrics, warehouse


router = APIRouter(tags=["analytics"])

JSON_RESULT_MAX_ROWS = 5_000
EXPORT_RESULT_MAX_ROWS = 500_000


@router.get("/analytics")
def analytics(
    run_id: str = "",
    dump_id: str = "",
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
    fraction_mode: str = "strict_authors_count",
    metric: str = "h",
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
    q: str = "",
    author_ids: str = "",
    data_filters: str = "",
    data_search: str = "",
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = Query(0, ge=0, le=EXPORT_RESULT_MAX_ROWS),
    custom_metric_defs: str = "",
    limit: int = Query(20, ge=0, le=JSON_RESULT_MAX_ROWS),
) -> dict[str, Any]:
    requested_run_id = run_id
    requested_dump_id = dump_id
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
        q=q,
    )
    try:
        cohort_ctx = _cohort_context(cohort_id, run_id=run_id, dump_id=dump_id, fraction_mode=fraction_mode, filters=filters, filter_policy=cohort_filter_policy)
        run_id = cohort_ctx["run_id"]
        dump_id = cohort_ctx["dump_id"]
        _require_analysis_scope(run_id=run_id, dump_id=dump_id)
        filters = cohort_ctx["filters"]
        filter_warnings = warehouse.analysis_filter_warnings(filters, run_id=run_id, dump_id=dump_id)
        parsed_data_filters = warehouse.parse_column_filters(data_filters)
        bundle = scientometric_workflow.metric_bundle(
            fraction_mode,
            metric,
            filters,
            limit=limit,
            run_id=run_id,
            dump_id=dump_id,
            author_ids=_combined_author_ids(cohort_ctx["author_ids"], author_ids),
            custom_metric_defs=_custom_metric_defs(custom_metric_defs),
            **_data_selection_kwargs(parsed_data_filters, data_search=data_search, data_sort=data_sort, data_direction=data_direction, data_limit=data_limit),
        )
        distribution = bundle["distribution"]
        top = bundle["ranking"]
        metric_lines = bundle["line_series"]
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Группа авторов не найдена") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = {
        "fraction_mode": fraction_mode,
        "metric": metric,
        "run_id": run_id,
        "dump_id": dump_id or top.get("dump_id") or distribution.get("dump_id"),
        "metric_scope": "filtered_recomputed",
        "percentile_scope": "current filtered author set",
        "metric_params": distribution.get("metric_params") or top.get("metric_params"),
        "filters": filters,
        "data_filters": parsed_data_filters,
        "data_search": data_search,
        "selected_author_ids": _author_ids_query(author_ids),
        "cohort": cohort_ctx["cohort"],
        "filter_warnings": filter_warnings,
        "filtered_distribution": distribution,
        "filtered_top": top,
        "filtered_metric_lines": metric_lines,
        "distribution": distribution,
        "top": top["rows"],
        "top_table": top,
        "metric_lines": metric_lines,
    }
    _annotate_scope_payload(
        payload,
        requested_run_id=requested_run_id,
        requested_dump_id=requested_dump_id,
        resolved_run_id=run_id,
        resolved_dump_id=payload["dump_id"],
        cohort_id=cohort_id,
    )
    return payload


@router.get("/analytics/custom-metrics")
def list_custom_metric_models(run_id: str = "") -> dict[str, Any]:
    try:
        models = custom_metrics.list_metric_models(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"run_id": run_id, "models": models}


@router.post("/analytics/custom-metrics")
def save_custom_metric_model(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        run_id = str(payload.get("run_id") or "").strip()
        model = custom_metrics.save_metric_model(run_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "action": "Исправьте формулу и повторите сохранение."}) from exc
    return {"run_id": run_id, "model": model}


@router.delete("/analytics/custom-metrics/{model_id}")
def delete_custom_metric_model(model_id: str, run_id: str = "") -> dict[str, Any]:
    try:
        result = custom_metrics.delete_metric_model(run_id, model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"run_id": run_id, **result}


@router.get("/analytics/distribution")
def distribution(
    run_id: str = "",
    dump_id: str = "",
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
    fraction_mode: str = "strict_authors_count",
    metric: str = "h",
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
    q: str = "",
    author_ids: str = "",
    data_filters: str = "",
    data_search: str = "",
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = Query(0, ge=0, le=EXPORT_RESULT_MAX_ROWS),
    custom_metric_defs: str = "",
) -> dict[str, Any]:
    requested_run_id = run_id
    requested_dump_id = dump_id
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
        q=q,
    )
    try:
        cohort_ctx = _cohort_context(cohort_id, run_id=run_id, dump_id=dump_id, fraction_mode=fraction_mode, filters=filters, filter_policy=cohort_filter_policy)
        run_id = cohort_ctx["run_id"]
        dump_id = cohort_ctx["dump_id"]
        _require_analysis_scope(run_id=run_id, dump_id=dump_id)
        filters = cohort_ctx["filters"]
        parsed_data_filters = warehouse.parse_column_filters(data_filters)
        payload = scientometric_workflow.metric_distribution(
            fraction_mode,
            metric,
            filters,
            run_id=run_id,
            dump_id=dump_id,
            author_ids=_combined_author_ids(cohort_ctx["author_ids"], author_ids),
            custom_metric_defs=_custom_metric_defs(custom_metric_defs),
            **_data_selection_kwargs(parsed_data_filters, data_search=data_search, data_sort=data_sort, data_direction=data_direction, data_limit=data_limit),
        )
        payload["cohort"] = cohort_ctx["cohort"]
        payload["data_filters"] = parsed_data_filters
        payload["data_search"] = data_search
        payload["selected_author_ids"] = _author_ids_query(author_ids)
        payload["filter_warnings"] = warehouse.analysis_filter_warnings(filters, run_id=run_id, dump_id=dump_id)
        _annotate_scope_payload(
            payload,
            requested_run_id=requested_run_id,
            requested_dump_id=requested_dump_id,
            resolved_run_id=str(payload.get("run_id") or run_id),
            resolved_dump_id=str(payload.get("dump_id") or dump_id),
            cohort_id=cohort_id,
        )
        return payload
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Группа авторов не найдена") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/analytics/ranking")
def ranking_json(
    run_id: str = "",
    dump_id: str = "",
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
    fraction_mode: str = "strict_authors_count",
    metric: str = "h",
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
    q: str = "",
    author_ids: str = "",
    data_filters: str = "",
    data_search: str = "",
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = Query(0, ge=0, le=EXPORT_RESULT_MAX_ROWS),
    custom_metric_defs: str = "",
    limit: int = Query(100, ge=0, le=JSON_RESULT_MAX_ROWS),
    rank_direction: str = "desc",
) -> dict[str, Any]:
    requested_run_id = run_id
    requested_dump_id = dump_id
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
        q=q,
    )
    try:
        cohort_ctx = _cohort_context(cohort_id, run_id=run_id, dump_id=dump_id, fraction_mode=fraction_mode, filters=filters, filter_policy=cohort_filter_policy)
        run_id = cohort_ctx["run_id"]
        dump_id = cohort_ctx["dump_id"]
        _require_analysis_scope(run_id=run_id, dump_id=dump_id)
        filters = cohort_ctx["filters"]
        parsed_data_filters = warehouse.parse_column_filters(data_filters)
        payload = scientometric_workflow.metric_ranking(
            fraction_mode,
            metric,
            filters,
            limit=limit,
            max_limit=JSON_RESULT_MAX_ROWS,
            run_id=run_id,
            dump_id=dump_id,
            author_ids=_combined_author_ids(cohort_ctx["author_ids"], author_ids),
            rank_direction=rank_direction,
            custom_metric_defs=_custom_metric_defs(custom_metric_defs),
            **_data_selection_kwargs(parsed_data_filters, data_search=data_search, data_sort=data_sort, data_direction=data_direction, data_limit=data_limit),
        )
        payload["cohort"] = cohort_ctx["cohort"]
        payload["data_filters"] = parsed_data_filters
        payload["data_search"] = data_search
        payload["selected_author_ids"] = _author_ids_query(author_ids)
        payload["filter_warnings"] = warehouse.analysis_filter_warnings(filters, run_id=run_id, dump_id=dump_id)
        _annotate_scope_payload(
            payload,
            requested_run_id=requested_run_id,
            requested_dump_id=requested_dump_id,
            resolved_run_id=str(payload.get("run_id") or run_id),
            resolved_dump_id=str(payload.get("dump_id") or dump_id),
            cohort_id=cohort_id,
        )
        return payload
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Группа авторов не найдена") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/analytics/ranking.csv")
def ranking_csv(
    run_id: str = "",
    dump_id: str = "",
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
    fraction_mode: str = "strict_authors_count",
    metric: str = "h",
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
    q: str = "",
    author_ids: str = "",
    data_filters: str = "",
    data_search: str = "",
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = Query(0, ge=0, le=EXPORT_RESULT_MAX_ROWS),
    custom_metric_defs: str = "",
    limit: int = Query(100_000, ge=0, le=EXPORT_RESULT_MAX_ROWS),
) -> StreamingResponse:
    requested_run_id = run_id
    requested_dump_id = dump_id
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
        q=q,
    )
    try:
        cohort_ctx = _cohort_context(cohort_id, run_id=run_id, dump_id=dump_id, fraction_mode=fraction_mode, filters=filters, filter_policy=cohort_filter_policy)
        run_id = cohort_ctx["run_id"]
        dump_id = cohort_ctx["dump_id"]
        _require_analysis_scope(run_id=run_id, dump_id=dump_id)
        filters = cohort_ctx["filters"]
        parsed_data_filters = warehouse.parse_column_filters(data_filters)
        stream = scientometric_workflow.iter_metric_ranking_csv(
            fraction_mode,
            metric,
            filters,
            limit=limit,
            max_limit=EXPORT_RESULT_MAX_ROWS,
            run_id=run_id,
            dump_id=dump_id,
            author_ids=_combined_author_ids(cohort_ctx["author_ids"], author_ids),
            custom_metric_defs=_custom_metric_defs(custom_metric_defs),
            **_data_selection_kwargs(parsed_data_filters, data_search=data_search, data_sort=data_sort, data_direction=data_direction, data_limit=data_limit),
        )
        payload = {"run_id": run_id, "dump_id": dump_id}
        _annotate_scope_payload(
            payload,
            requested_run_id=requested_run_id,
            requested_dump_id=requested_dump_id,
            resolved_run_id=str(payload.get("run_id") or run_id),
            resolved_dump_id=str(payload.get("dump_id") or dump_id),
            cohort_id=cohort_id,
        )
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Группа авторов не найдена") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    return StreamingResponse(
        stream,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="openalex_dss_filtered_rating.csv"',
            **_scope_response_headers(payload),
        },
    )


@router.get("/analytics/scientometrics")
def scientometric_analysis(
    run_id: str = "",
    dump_id: str = "",
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
    fraction_mode: str = "strict_authors_count",
    metrics: str = "",
    baseline_metric: str = "h",
    top_n: int = Query(100, ge=0, le=1000),
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
    q: str = "",
    author_ids: str = "",
    data_filters: str = "",
    data_search: str = "",
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = Query(0, ge=0, le=EXPORT_RESULT_MAX_ROWS),
    custom_metric_defs: str = "",
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
        q=q,
    )
    try:
        payload = scientometric_workflow.build_scientometric_analysis(
            fraction_mode=fraction_mode,
            metrics=_metric_list(metrics),
            baseline_metric=baseline_metric,
            filters=filters,
            run_id=run_id,
            dump_id=dump_id,
            cohort_id=cohort_id,
            cohort_filter_policy=cohort_filter_policy,
            top_n=top_n,
            data_filters=warehouse.parse_column_filters(data_filters),
            data_search=data_search,
            author_ids=_author_ids_query(author_ids),
            data_sort=data_sort,
            data_direction=data_direction,
            data_limit=data_limit,
            custom_metric_defs=_custom_metric_defs(custom_metric_defs),
        )
        _annotate_scope_payload(
            payload,
            requested_run_id=run_id,
            requested_dump_id=dump_id,
            resolved_run_id=str((payload.get("scope") or {}).get("run_id") or payload.get("run_id") or ""),
            resolved_dump_id=str((payload.get("scope") or {}).get("dump_id") or payload.get("dump_id") or ""),
            cohort_id=cohort_id,
        )
        return payload
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Группа авторов не найдена") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/analytics/scientometrics.json")
def scientometric_analysis_json(request: Request) -> Response:
    try:
        payload = _scientometric_payload_from_request(request)
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Группа авторов не найдена") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="openalex_dss_scientometrics.json"'},
    )


@router.get("/analytics/scientometrics/descriptive.csv")
def scientometric_descriptive_csv(request: Request) -> Response:
    try:
        payload = _scientometric_export_payload_from_request(request)
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Группа авторов не найдена") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fields = [
        "metric",
        "n",
        "missing_count",
        "zero_count",
        "zero_rate",
        "min",
        "q1",
        "median",
        "q3",
        "max",
        "mean",
        "stddev",
        "coefficient_of_variation",
        "iqr",
        "p90",
        "p95",
        "p99",
        "skewness",
        "excess_kurtosis",
        "tie_rate",
        "unique_count",
        "outlier_count_iqr",
        "outlier_share_iqr",
    ]
    return _csv_response(fields, _scientometric_descriptive_rows(payload), filename="openalex_dss_scientometrics_descriptive.csv", headers=_scope_response_headers(payload))


@router.get("/analytics/scientometrics/correlations.csv")
def scientometric_correlations_csv(request: Request) -> Response:
    try:
        payload = _scientometric_export_payload_from_request(request)
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Группа авторов не найдена") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fields = ["method", "left_metric", "right_metric", "value"]
    return _csv_response(fields, _scientometric_correlation_rows(payload), filename="openalex_dss_scientometrics_correlations.csv", headers=_scope_response_headers(payload))


@router.get("/analytics/scientometrics/outliers.csv")
def scientometric_outliers_csv(request: Request) -> Response:
    try:
        payload = _scientometric_export_payload_from_request(request)
        rows = scientometric_workflow.build_outlier_export_rows(**_scientometric_kwargs_from_request(request))
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Группа авторов не найдена") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fields = ["metric", "author_id", "author_display_name", "value", "rule", "lower_fence", "upper_fence"]
    return _csv_response(fields, rows, filename="openalex_dss_scientometrics_outliers.csv", headers=_scope_response_headers(payload))


@router.get("/analytics/scientometrics/top-outliers.csv")
def scientometric_top_outliers_csv(request: Request) -> Response:
    try:
        payload = _scientometric_export_payload_from_request(request)
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Группа авторов не найдена") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fields = ["metric", "author_id", "author_display_name", "value", "rule", "lower_fence", "upper_fence"]
    return _csv_response(fields, _scientometric_top_outlier_rows(payload), filename="openalex_dss_scientometrics_top_outliers.csv", headers=_scope_response_headers(payload))


@router.get("/analytics/scientometrics/findings.csv")
def scientometric_findings_csv(request: Request) -> Response:
    try:
        payload = _scientometric_export_payload_from_request(request)
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Группа авторов не найдена") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fields = ["id", "type", "metric", "baseline_metric", "severity", "text", "recommendation", "evidence_json"]
    return _csv_response(fields, _scientometric_finding_rows(payload), filename="openalex_dss_scientometrics_findings.csv", headers=_scope_response_headers(payload))


@router.get("/analytics/scientometrics/conclusion.md")
def scientometric_conclusion_markdown(request: Request) -> Response:
    try:
        payload = _scientometric_export_payload_from_request(request)
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Группа авторов не найдена") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    markdown = scientometric_workflow.scientometric_conclusion_markdown(payload)
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="openalex_dss_scientometrics_conclusion.md"',
            **_scope_response_headers(payload),
        },
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
    q: str = "",
) -> dict[str, str]:
    return AnalysisFilterQuery(
        country_code=country_code,
        filter_mode=filter_mode,
        subject_level=subject_level,
        subject_id=subject_id,
        keyword_id=keyword_id,
        keyword_display_name=keyword_display_name,
        text_search_query=text_search_query,
        author_id=author_id,
        author_orcid=author_orcid,
        author_display_name=author_display_name,
        doi=doi,
        affiliation_mode=affiliation_mode,
        institution_id=institution_id,
        source_id=source_id,
        source_display_name=source_display_name,
        source_type=source_type,
        language=language,
        open_access_is_oa=open_access_is_oa,
        has_abstract=has_abstract,
        min_cited_by_count=min_cited_by_count,
        from_publication_date=from_publication_date,
        to_publication_date=to_publication_date,
        work_type=work_type,
        q=q,
    ).to_filters()


def _metric_list(metrics: str) -> list[str] | None:
    if not metrics:
        return None
    normalized = metrics.replace("|", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _author_ids_query(author_ids: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if author_ids is None:
        return []
    if isinstance(author_ids, str):
        raw_values = author_ids.replace("\n", ",").split(",")
    else:
        raw_values = list(author_ids)
    return [str(item).strip() for item in raw_values if str(item).strip()]


def _combined_author_ids(scope_author_ids: Any, requested_author_ids: str | list[str] | tuple[str, ...] | None) -> set[str] | list[str] | None:
    requested = set(_author_ids_query(requested_author_ids))
    if not requested:
        return scope_author_ids
    if scope_author_ids is None:
        return requested
    return {str(author_id).strip() for author_id in scope_author_ids if str(author_id).strip()}.intersection(requested)


def _scientometric_payload_from_request(request: Request) -> dict[str, Any]:
    kwargs = _scientometric_kwargs_from_request(request)
    payload = scientometric_workflow.build_scientometric_analysis(**kwargs)
    _annotate_scope_payload(
        payload,
        requested_run_id=str(kwargs.get("run_id") or ""),
        requested_dump_id=str(kwargs.get("dump_id") or ""),
        resolved_run_id=str((payload.get("scope") or {}).get("run_id") or payload.get("run_id") or ""),
        resolved_dump_id=str((payload.get("scope") or {}).get("dump_id") or payload.get("dump_id") or ""),
        cohort_id=str(kwargs.get("cohort_id") or ""),
    )
    return payload


def _scientometric_export_payload_from_request(request: Request) -> dict[str, Any]:
    return _scientometric_payload_from_request(request)


def _scientometric_kwargs_from_request(request: Request) -> dict[str, Any]:
    query = request.query_params
    filters = _slice_filters(
        country_code=query.get("country_code", ""),
        filter_mode=query.get("filter_mode", ""),
        subject_level=query.get("subject_level", ""),
        subject_id=query.get("subject_id", ""),
        keyword_id=query.get("keyword_id", ""),
        keyword_display_name=query.get("keyword_display_name", "") or query.get("keyword_name", ""),
        text_search_query=query.get("text_search_query", ""),
        author_id=query.get("author_id", ""),
        author_orcid=query.get("author_orcid", ""),
        author_display_name=query.get("author_display_name", "") or query.get("author_name", ""),
        doi=query.get("doi", ""),
        affiliation_mode=query.get("affiliation_mode", ""),
        institution_id=query.get("institution_id", ""),
        source_id=query.get("source_id", ""),
        source_display_name=query.get("source_display_name", "") or query.get("source_name", ""),
        source_type=query.get("source_type", ""),
        language=query.get("language", ""),
        open_access_is_oa=query.get("open_access_is_oa", ""),
        has_abstract=query.get("has_abstract", ""),
        min_cited_by_count=_int_query(query.get("min_cited_by_count"), 0),
        from_publication_date=query.get("from_publication_date", ""),
        to_publication_date=query.get("to_publication_date", ""),
        work_type=query.get("work_type", ""),
        q=query.get("q", ""),
    )
    return {
        "fraction_mode": query.get("fraction_mode", "strict_authors_count"),
        "metrics": _metric_list(query.get("metrics", "")),
        "baseline_metric": query.get("baseline_metric", "h"),
        "filters": filters,
        "run_id": query.get("run_id", ""),
        "dump_id": query.get("dump_id", ""),
        "cohort_id": query.get("cohort_id", ""),
        "cohort_filter_policy": query.get("cohort_filter_policy", "membership"),
        "top_n": max(0, min(_int_query(query.get("top_n"), 100), 1000)),
        "data_filters": warehouse.parse_column_filters(query.get("data_filters", "")),
        "data_search": query.get("data_search", ""),
        "author_ids": _author_ids_query(query.get("author_ids", "")),
        "data_sort": query.get("data_sort", ""),
        "data_direction": query.get("data_direction", "desc"),
        "data_limit": max(0, min(_int_query(query.get("data_limit"), 0), EXPORT_RESULT_MAX_ROWS)),
        "custom_metric_defs": _custom_metric_defs(query.get("custom_metric_defs", "")),
    }


def _custom_metric_defs(raw: str) -> list[dict[str, str]]:
    return custom_metrics.parse_custom_metrics(raw)


def _data_selection_kwargs(
    data_filters: dict[str, Any],
    *,
    data_search: str = "",
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = 0,
) -> dict[str, Any]:
    return DataSelectionQuery(
        data_filters=data_filters,
        data_search=str(data_search or ""),
        data_sort=str(data_sort or ""),
        data_direction=str(data_direction or "desc"),
        data_limit=_int_query(data_limit, 0),
        max_limit=EXPORT_RESULT_MAX_ROWS,
    ).to_kwargs()


def _csv_response(fields: list[str], rows: list[dict[str, Any]], *, filename: str, headers: dict[str, str] | None = None) -> Response:
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    response_headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    response_headers.update(headers or {})
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers=response_headers,
    )


def _iter_dict_csv(fields: list[str], rows: list[dict[str, Any]]) -> Any:
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    yield output.getvalue()
    for row in rows:
        output.seek(0)
        output.truncate(0)
        writer.writerow(row)
        yield output.getvalue()


def _scientometric_descriptive_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    descriptive = payload.get("descriptive") or {}
    return [{"metric": metric, **(summary or {})} for metric, summary in descriptive.items()]


def _scientometric_correlation_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    correlations = payload.get("correlations") or {}
    rows: list[dict[str, Any]] = []
    for method, matrix_payload in correlations.items():
        matrix = (matrix_payload or {}).get("matrix") if method == "kendall_tau_b" else matrix_payload
        if not isinstance(matrix, dict):
            continue
        for left_metric, right_values in matrix.items():
            if not isinstance(right_values, dict):
                continue
            for right_metric, value in right_values.items():
                rows.append({"method": method, "left_metric": left_metric, "right_metric": right_metric, "value": value})
    return rows


def _scientometric_top_outlier_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    outliers = payload.get("outliers") or {}
    boxplots = payload.get("boxplots") or {}
    rows: list[dict[str, Any]] = []
    for metric, metric_outliers in outliers.items():
        boxplot = boxplots.get(metric) or {}
        rule = boxplot.get("outlier_rule") or "iqr_1_5"
        lower_fence = boxplot.get("lower_fence")
        upper_fence = boxplot.get("upper_fence")
        for row in metric_outliers or []:
            rows.append(
                {
                    "metric": metric,
                    "author_id": row.get("author_id"),
                    "author_display_name": row.get("author_display_name"),
                    "value": row.get("value"),
                    "rule": rule,
                    "lower_fence": lower_fence,
                    "upper_fence": upper_fence,
                }
            )
    return rows


def _scientometric_finding_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for finding in payload.get("findings") or []:
        rows.append(
            {
                "id": finding.get("id"),
                "type": finding.get("type"),
                "metric": finding.get("metric"),
                "baseline_metric": finding.get("baseline_metric"),
                "severity": finding.get("severity"),
                "text": finding.get("text"),
                "recommendation": finding.get("recommendation"),
                "evidence_json": json.dumps(finding.get("evidence") or {}, ensure_ascii=False, sort_keys=True),
            }
        )
    return rows


def _int_query(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _scope_metadata(
    *,
    requested_run_id: str = "",
    requested_dump_id: str = "",
    resolved_run_id: str = "",
    resolved_dump_id: str = "",
    cohort_id: str = "",
) -> dict[str, Any]:
    requested_run_id = str(requested_run_id or "").strip()
    requested_dump_id = str(requested_dump_id or "").strip()
    resolved_run_id = str(resolved_run_id or "").strip()
    resolved_dump_id = str(resolved_dump_id or "").strip()
    cohort_id = str(cohort_id or "").strip()
    scope_query = ScopeQuery(run_id=requested_run_id, dump_id=requested_dump_id, cohort_id=cohort_id)
    if scope_query.has_direct_scope:
        _require_analysis_scope(run_id=resolved_run_id or requested_run_id, dump_id=resolved_dump_id or requested_dump_id)
        return {"scope_status": "explicit_scope", "reproducible": True}
    if scope_query.cohort_id and (resolved_run_id or resolved_dump_id):
        _require_analysis_scope(run_id=resolved_run_id, dump_id=resolved_dump_id)
        return {"scope_status": "cohort_resolved_scope", "reproducible": True}
    raise ValueError("run_id or dump_id is required for analytics access.")


def _annotate_scope_payload(
    payload: dict[str, Any],
    *,
    requested_run_id: str = "",
    requested_dump_id: str = "",
    resolved_run_id: str = "",
    resolved_dump_id: str = "",
    cohort_id: str = "",
) -> dict[str, Any]:
    metadata = _scope_metadata(
        requested_run_id=requested_run_id,
        requested_dump_id=requested_dump_id,
        resolved_run_id=resolved_run_id,
        resolved_dump_id=resolved_dump_id,
        cohort_id=cohort_id,
    )
    payload.update(metadata)
    metric_run_id = str(resolved_run_id or payload.get("run_id") or "").strip()
    if metric_run_id and "metric_models" not in payload:
        payload["metric_models"] = custom_metrics.list_metric_models(metric_run_id)
    scope = payload.get("scope")
    if isinstance(scope, dict):
        scope["scope_status"] = metadata["scope_status"]
        scope["reproducible"] = metadata["reproducible"]
    existing = payload.get("warnings")
    warnings = existing if isinstance(existing, list) else ([] if existing is None else [existing])
    payload["warnings"] = warnings
    return payload


def _scope_response_headers(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "X-OpenAlex-DSS-Scope-Status": str(payload.get("scope_status") or ""),
        "X-OpenAlex-DSS-Reproducible": "true" if payload.get("reproducible") is True else "false",
    }


def _require_analysis_scope(*, run_id: str = "", dump_id: str = "") -> None:
    if str(run_id or "").strip() or str(dump_id or "").strip():
        return
    raise ValueError("run_id or dump_id is required for analytics access.")


def _cohort_context(cohort_id: str, *, run_id: str, dump_id: str, fraction_mode: str, filters: dict[str, Any], filter_policy: str = "membership") -> dict[str, Any]:
    if not cohort_id:
        return {"run_id": run_id, "dump_id": dump_id, "filters": filters, "author_ids": None, "cohort": None}
    ctx = cohorts.resolve_cohort_context(cohort_id, run_id=run_id, dump_id=dump_id, fraction_mode=fraction_mode, filters=filters, filter_policy=filter_policy)
    cohort = ctx["cohort"]
    return {
        "run_id": ctx["run_id"],
        "dump_id": ctx["dump_id"],
        "filters": ctx["filters"],
        "author_ids": ctx["author_ids"],
        "cohort": {
            "cohort_id": cohort.get("cohort_id"),
            "name": cohort.get("name"),
            "source": cohort.get("source"),
            "n_authors": cohort.get("n_authors"),
            "checksum": cohort.get("checksum"),
            "membership_filters": ctx.get("membership_filters") or {},
            "analysis_filters": ctx.get("analysis_filters") or ctx.get("filters") or {},
            "filter_policy": ctx.get("filter_policy") or "membership",
            "resolved_filter_mode": ctx.get("resolved_filter_mode") or ctx.get("filter_mode"),
            "filter_mode": ctx.get("filter_mode"),
        },
    }
