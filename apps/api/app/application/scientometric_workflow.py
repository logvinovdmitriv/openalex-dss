from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.domain.scientometric_contract import DataSelectionPolicy, RankingUseCase, ScopedAnalysisContext
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
    use_case = _ranking_use_case(
        run_id=run_id,
        dump_id=dump_id,
        fraction_mode=fraction_mode,
        metric=metric,
        data_selection=data_selection,
    )
    return warehouse.metric_bundle(
        use_case.fraction_mode,
        use_case.primary_metric,
        filters,
        limit=limit,
        run_id=use_case.context.run_id,
        dump_id=use_case.context.dump_id,
        author_ids=author_ids,
        custom_metric_defs=custom_metric_defs,
        **use_case.data_selection.to_query_kwargs(),
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
    use_case = _ranking_use_case(
        run_id=run_id,
        dump_id=dump_id,
        fraction_mode=fraction_mode,
        metric=metric,
        data_selection=data_selection,
    )
    return warehouse.metric_distribution(
        use_case.fraction_mode,
        use_case.primary_metric,
        filters,
        run_id=use_case.context.run_id,
        dump_id=use_case.context.dump_id,
        author_ids=author_ids,
        custom_metric_defs=custom_metric_defs,
        **use_case.data_selection.to_query_kwargs(),
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
    use_case = _ranking_use_case(
        run_id=run_id,
        dump_id=dump_id,
        fraction_mode=fraction_mode,
        metric=metric,
        data_selection=data_selection,
    )
    return warehouse.metric_ranking(
        use_case.fraction_mode,
        use_case.primary_metric,
        filters,
        limit=limit,
        max_limit=max_limit,
        run_id=use_case.context.run_id,
        dump_id=use_case.context.dump_id,
        author_ids=author_ids,
        custom_metric_defs=custom_metric_defs,
        **use_case.data_selection.to_query_kwargs(),
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
    use_case = _ranking_use_case(
        run_id=run_id,
        dump_id=dump_id,
        fraction_mode=fraction_mode,
        metric=metric,
        data_selection=data_selection,
    )
    return warehouse.iter_metric_ranking_csv(
        use_case.fraction_mode,
        use_case.primary_metric,
        filters,
        limit=limit,
        max_limit=max_limit,
        run_id=use_case.context.run_id,
        dump_id=use_case.context.dump_id,
        author_ids=author_ids,
        custom_metric_defs=custom_metric_defs,
        **use_case.data_selection.to_query_kwargs(),
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


def _ranking_use_case(
    *,
    run_id: str,
    dump_id: str,
    fraction_mode: str,
    metric: str,
    data_selection: dict[str, Any],
) -> RankingUseCase:
    return RankingUseCase(
        context=ScopedAnalysisContext(run_id=run_id, dump_id=dump_id),
        primary_metric=metric,
        fraction_mode=fraction_mode,
        data_selection=DataSelectionPolicy.from_kwargs(**data_selection),
    ).require_ready()
