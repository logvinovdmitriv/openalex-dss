from __future__ import annotations

import csv
import json
from io import StringIO
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.services import cohorts, scientometrics, warehouse
from app.services.analysis_filters import build_analysis_filters


router = APIRouter(tags=["analytics"])


@router.get("/analytics")
def analytics(
    run_id: str = "",
    dump_id: str = "",
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
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
    try:
        cohort_ctx = _cohort_context(cohort_id, run_id=run_id, dump_id=dump_id, fraction_mode=fraction_mode, filters=filters, filter_policy=cohort_filter_policy)
        run_id = cohort_ctx["run_id"]
        dump_id = cohort_ctx["dump_id"]
        filters = cohort_ctx["filters"]
        stats = warehouse.read_json_doc("stats", run_id=run_id) or {}
        theory = warehouse.read_json_doc("theory", run_id=run_id) or {}
        filter_warnings = warehouse.analysis_filter_warnings(filters, run_id=run_id, dump_id=dump_id)
        bundle = warehouse.metric_bundle(fraction_mode, metric, filters, limit=limit, run_id=run_id, dump_id=dump_id, author_ids=cohort_ctx["author_ids"])
        distribution = bundle["distribution"]
        top = bundle["ranking"]
        metric_lines = bundle["line_series"]
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
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
        "cohort": cohort_ctx["cohort"],
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
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
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
        cohort_ctx = _cohort_context(cohort_id, run_id=run_id, dump_id=dump_id, fraction_mode=fraction_mode, filters=filters, filter_policy=cohort_filter_policy)
        run_id = cohort_ctx["run_id"]
        dump_id = cohort_ctx["dump_id"]
        filters = cohort_ctx["filters"]
        payload = warehouse.metric_distribution(fraction_mode, metric, filters, run_id=run_id, dump_id=dump_id, author_ids=cohort_ctx["author_ids"])
        payload["cohort"] = cohort_ctx["cohort"]
        payload["filter_warnings"] = warehouse.analysis_filter_warnings(filters, run_id=run_id, dump_id=dump_id)
        return payload
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/analytics/ranking")
def ranking_json(
    run_id: str = "",
    dump_id: str = "",
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
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
        cohort_ctx = _cohort_context(cohort_id, run_id=run_id, dump_id=dump_id, fraction_mode=fraction_mode, filters=filters, filter_policy=cohort_filter_policy)
        run_id = cohort_ctx["run_id"]
        dump_id = cohort_ctx["dump_id"]
        filters = cohort_ctx["filters"]
        payload = warehouse.metric_ranking(fraction_mode, metric, filters, limit=limit, max_limit=500_000, run_id=run_id, dump_id=dump_id, author_ids=cohort_ctx["author_ids"])
        payload["cohort"] = cohort_ctx["cohort"]
        payload["filter_warnings"] = warehouse.analysis_filter_warnings(filters, run_id=run_id, dump_id=dump_id)
        return payload
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/analytics/ranking.csv")
def ranking_csv(
    run_id: str = "",
    dump_id: str = "",
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
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
            cohort_id=cohort_id,
            cohort_filter_policy=cohort_filter_policy,
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


@router.get("/analytics/scientometrics")
def scientometric_analysis(
    run_id: str = "",
    dump_id: str = "",
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
    fraction_mode: str = "strict_authors_count",
    metrics: str = "",
    baseline_metric: str = "h",
    top_n: int = Query(100, ge=1, le=1000),
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
        return scientometrics.build_scientometric_analysis(
            fraction_mode=fraction_mode,
            metrics=_metric_list(metrics),
            baseline_metric=baseline_metric,
            filters=filters,
            run_id=run_id,
            dump_id=dump_id,
            cohort_id=cohort_id,
            cohort_filter_policy=cohort_filter_policy,
            top_n=top_n,
        )
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/analytics/scientometrics.json")
def scientometric_analysis_json(request: Request) -> Response:
    try:
        payload = _scientometric_payload_from_request(request)
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
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
        payload = _scientometric_payload_from_request(request)
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
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
    return _csv_response(fields, _scientometric_descriptive_rows(payload), filename="openalex_dss_scientometrics_descriptive.csv")


@router.get("/analytics/scientometrics/correlations.csv")
def scientometric_correlations_csv(request: Request) -> Response:
    try:
        payload = _scientometric_payload_from_request(request)
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fields = ["method", "left_metric", "right_metric", "value"]
    return _csv_response(fields, _scientometric_correlation_rows(payload), filename="openalex_dss_scientometrics_correlations.csv")


@router.get("/analytics/scientometrics/rank-shifts.csv")
def scientometric_rank_shifts_csv(request: Request) -> Response:
    try:
        rows = scientometrics.build_rank_shift_export_rows(**_scientometric_kwargs_from_request(request))
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fields = ["baseline_metric", "compare_metric", "author_id", "author_display_name", "baseline_rank", "metric_rank", "rank_delta", "abs_rank_delta"]
    return _csv_response(fields, rows, filename="openalex_dss_scientometrics_rank_shifts.csv")


@router.get("/analytics/scientometrics/largest-rank-shifts.csv")
def scientometric_largest_rank_shifts_csv(request: Request) -> Response:
    try:
        payload = _scientometric_payload_from_request(request)
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fields = ["baseline_metric", "compare_metric", "author_id", "author_display_name", "baseline_rank", "metric_rank", "rank_delta", "abs_rank_delta"]
    return _csv_response(fields, _scientometric_largest_rank_shift_rows(payload), filename="openalex_dss_scientometrics_largest_rank_shifts.csv")


@router.get("/analytics/scientometrics/outliers.csv")
def scientometric_outliers_csv(request: Request) -> Response:
    try:
        rows = scientometrics.build_outlier_export_rows(**_scientometric_kwargs_from_request(request))
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fields = ["metric", "author_id", "author_display_name", "value", "rule", "lower_fence", "upper_fence"]
    return _csv_response(fields, rows, filename="openalex_dss_scientometrics_outliers.csv")


@router.get("/analytics/scientometrics/top-outliers.csv")
def scientometric_top_outliers_csv(request: Request) -> Response:
    try:
        payload = _scientometric_payload_from_request(request)
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fields = ["metric", "author_id", "author_display_name", "value", "rule", "lower_fence", "upper_fence"]
    return _csv_response(fields, _scientometric_top_outlier_rows(payload), filename="openalex_dss_scientometrics_top_outliers.csv")


@router.get("/analytics/scientometrics/findings.csv")
def scientometric_findings_csv(request: Request) -> Response:
    try:
        payload = _scientometric_payload_from_request(request)
    except cohorts.CohortNotFound as exc:
        raise HTTPException(status_code=404, detail="Cohort not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fields = ["id", "type", "metric", "baseline_metric", "severity", "text", "recommendation", "evidence_json"]
    return _csv_response(fields, _scientometric_finding_rows(payload), filename="openalex_dss_scientometrics_findings.csv")


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
    return build_analysis_filters(
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
    )


def _metric_list(metrics: str) -> list[str] | None:
    if not metrics:
        return None
    normalized = metrics.replace("|", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _scientometric_payload_from_request(request: Request) -> dict[str, Any]:
    return scientometrics.build_scientometric_analysis(**_scientometric_kwargs_from_request(request))


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
        "top_n": max(1, min(_int_query(query.get("top_n"), 100), 1000)),
    }


def _csv_response(fields: list[str], rows: list[dict[str, Any]], *, filename: str) -> Response:
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


def _scientometric_largest_rank_shift_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    comparisons = payload.get("rank_comparisons") or {}
    rows: list[dict[str, Any]] = []
    for compare_metric, comparison in comparisons.items():
        for row in (comparison or {}).get("largest_shifts") or []:
            rows.append(
                {
                    "baseline_metric": (comparison or {}).get("baseline_metric") or (payload.get("scope") or {}).get("baseline_metric"),
                    "compare_metric": compare_metric,
                    "author_id": row.get("author_id"),
                    "author_display_name": row.get("author_display_name"),
                    "baseline_rank": row.get("baseline_rank"),
                    "metric_rank": row.get("metric_rank"),
                    "rank_delta": row.get("rank_delta"),
                    "abs_rank_delta": row.get("abs_rank_delta"),
                }
            )
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
