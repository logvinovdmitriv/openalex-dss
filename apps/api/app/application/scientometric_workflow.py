from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.services import custom_metrics, reports, scientometrics, warehouse


def parse_custom_metric_defs(raw: Any) -> list[dict[str, str]]:
    return custom_metrics.parse_custom_metrics(raw)


def metric_bundle(
    fraction_mode: str,
    metric: str,
    filters: dict[str, Any],
    *,
    limit: int,
    run_id: str,
    dump_id: str,
    author_ids: set[str] | list[str] | None = None,
    custom_metric_defs: list[dict[str, str]] | None = None,
    **data_selection: Any,
) -> dict[str, Any]:
    return warehouse.metric_bundle(
        fraction_mode,
        metric,
        filters,
        limit=limit,
        run_id=run_id,
        dump_id=dump_id,
        author_ids=author_ids,
        custom_metric_defs=custom_metric_defs,
        **data_selection,
    )


def metric_distribution(
    fraction_mode: str,
    metric: str,
    filters: dict[str, Any],
    *,
    run_id: str,
    dump_id: str,
    author_ids: set[str] | list[str] | None = None,
    custom_metric_defs: list[dict[str, str]] | None = None,
    **data_selection: Any,
) -> dict[str, Any]:
    return warehouse.metric_distribution(
        fraction_mode,
        metric,
        filters,
        run_id=run_id,
        dump_id=dump_id,
        author_ids=author_ids,
        custom_metric_defs=custom_metric_defs,
        **data_selection,
    )


def metric_ranking(
    fraction_mode: str,
    metric: str,
    filters: dict[str, Any],
    *,
    limit: int,
    max_limit: int,
    run_id: str,
    dump_id: str,
    author_ids: set[str] | list[str] | None = None,
    custom_metric_defs: list[dict[str, str]] | None = None,
    **data_selection: Any,
) -> dict[str, Any]:
    return warehouse.metric_ranking(
        fraction_mode,
        metric,
        filters,
        limit=limit,
        max_limit=max_limit,
        run_id=run_id,
        dump_id=dump_id,
        author_ids=author_ids,
        custom_metric_defs=custom_metric_defs,
        **data_selection,
    )


def iter_metric_ranking_csv(
    fraction_mode: str,
    metric: str,
    filters: dict[str, Any],
    *,
    limit: int,
    max_limit: int,
    run_id: str,
    dump_id: str,
    author_ids: set[str] | list[str] | None = None,
    custom_metric_defs: list[dict[str, str]] | None = None,
    **data_selection: Any,
) -> Iterable[str]:
    return warehouse.iter_metric_ranking_csv(
        fraction_mode,
        metric,
        filters,
        limit=limit,
        max_limit=max_limit,
        run_id=run_id,
        dump_id=dump_id,
        author_ids=author_ids,
        custom_metric_defs=custom_metric_defs,
        **data_selection,
    )


def build_scientometric_analysis(**kwargs: Any) -> dict[str, Any]:
    return scientometrics.build_scientometric_analysis(**kwargs)


def build_outlier_export_rows(**kwargs: Any) -> list[dict[str, Any]]:
    return scientometrics.build_outlier_export_rows(**kwargs)


def scientometric_conclusion_markdown(payload: dict[str, Any]) -> str:
    return scientometrics.scientometric_conclusion_markdown(payload)


def build_report_bundle(**kwargs: Any) -> dict[str, Any]:
    return reports.build_report_bundle(**kwargs)


def report_bundle_json(**kwargs: Any) -> dict[str, Any]:
    return reports.report_bundle_json(**kwargs)
