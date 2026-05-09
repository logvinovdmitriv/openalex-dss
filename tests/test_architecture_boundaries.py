from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "apps/api", ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.api.query_contracts import AnalysisFilterQuery, DataSelectionQuery, ScopeQuery
from app.application import decision_support_workflow, scientometric_workflow
from app.domain.scientometric_contract import DataSelectionPolicy, MetricModel, RankingUseCase, ScopedAnalysisContext
from app.services import catalog, distribution_engine, metric_registry, ranking_engine, workflow


def test_catalog_uses_shared_metric_registry() -> None:
    registry_metrics = metric_registry.catalog_metrics()
    system_catalog = catalog.system_catalog()
    catalog_metrics = system_catalog["metrics"]

    assert catalog_metrics == registry_metrics
    assert "tables" not in system_catalog
    assert registry_metrics
    assert all(item["id"] and item["label"] for item in registry_metrics)
    assert any(item.get("formula") or item.get("algorithm") for item in registry_metrics)


def test_workflow_catalog_is_static_and_scoped_state_is_removed() -> None:
    stage_ids = [item["id"] for item in workflow.STAGE_DEFINITIONS]

    assert stage_ids == ["slice", "ingestion", "flatten", "indices", "analytics", "export"]
    assert not hasattr(workflow, "state")


def test_ranking_and_distribution_engines_keep_service_contracts() -> None:
    rows = [
        {"author_id": "a1", "author_display_name": "A", "h": 5, "p": 2},
        {"author_id": "a2", "author_display_name": "B", "h": 7, "p": 4},
        {"author_id": "a3", "author_display_name": "C", "h": 7, "p": 1},
    ]

    ranked, total = ranking_engine.build_metric_ranking_rows(rows, "h", ["p"], limit=10, max_limit=100)
    summary = distribution_engine.describe([row["h"] for row in rows])
    histogram = distribution_engine.histogram([row["h"] for row in rows], bins=2)

    assert total == 3
    assert [row["author_id"] for row in ranked] == ["a2", "a3", "a1"]
    assert ranked[0]["rank_competition"] == ranked[1]["rank_competition"] == 1
    assert summary["median"] == 7
    assert sum(bucket["count"] for bucket in histogram) == 3


def test_query_contracts_normalize_common_api_values() -> None:
    filters = AnalysisFilterQuery(country_code="ru", keyword_display_name="graph databases", min_cited_by_count=3).to_filters()
    selection = DataSelectionQuery(data_filters={"h": {"min": 1}}, data_search=" Ivanov ", data_sort="h", data_direction="asc", data_limit=50).to_kwargs()
    scope = ScopeQuery(run_id="run_1")

    assert scope.has_direct_scope
    assert filters["country_code"] == "RU"
    assert filters["keyword_display_name"] == "graph databases"
    assert filters["min_cited_by_count"] == "3"
    assert selection == {"data_filters": {"h": {"min": 1}}, "data_search": "Ivanov", "data_sort": "h", "data_direction": "asc", "data_limit": 50}


def test_application_layer_exposes_scientometric_use_cases() -> None:
    assert callable(scientometric_workflow.metric_ranking)
    assert callable(scientometric_workflow.iter_metric_ranking_csv)
    assert callable(scientometric_workflow.build_scientometric_analysis)
    assert callable(scientometric_workflow.build_report_bundle)


def test_domain_scoped_context_guards_future_use_cases() -> None:
    selection = DataSelectionPolicy.from_kwargs(data_search=" Ivanov ", data_sort="h", data_direction="asc", data_limit=25)
    use_case = RankingUseCase(
        context=ScopedAnalysisContext(run_id=" run_1 "),
        primary_metric=" h ",
        fraction_mode="",
        data_selection=selection,
    ).require_ready()

    assert use_case.context.run_id == "run_1"
    assert use_case.primary_metric == "h"
    assert use_case.fraction_mode == "strict_authors_count"
    assert use_case.data_selection.to_query_kwargs()["data_limit"] == 25


def test_application_layer_rejects_unscoped_analytics_before_storage() -> None:
    try:
        scientometric_workflow.metric_ranking(
            "strict_authors_count",
            "h",
            {},
            limit=10,
            max_limit=100,
            run_id="",
            dump_id="",
        )
    except ValueError as exc:
        assert "выбранный расчет или локальный срез" in str(exc)
    else:
        raise AssertionError("unscoped analytics must fail at the application boundary")


def test_decision_support_workflow_wraps_ready_ranking_use_case() -> None:
    use_case = RankingUseCase(
        context=ScopedAnalysisContext(run_id="run_1", dump_id="dump_1"),
        primary_metric="h",
        fraction_mode="strict_authors_count",
        data_selection=DataSelectionPolicy.from_kwargs(data_search="Ivanov", data_limit=10),
        metric_models=(MetricModel(id="custom_rating", label="Собственный рейтинг", expression="h + p"),),
    )

    case = decision_support_workflow.ranking_decision_case(use_case, candidate_ids=["a1", "a2"])
    run = decision_support_workflow.ranking_decision_run(use_case, candidate_ids=case.candidates)
    passport = decision_support_workflow.decision_passport(run, input_checksums={"indices": "abc"})
    same_passport = decision_support_workflow.decision_passport(run, input_checksums={"indices": "abc"})

    assert case.rule_profile_id == "scientometric_ranking"
    assert case.context["run_id"] == "run_1"
    assert case.context["dump_id"] == "dump_1"
    assert case.context["primary_metric"] == "h"
    assert case.candidates == ("a1", "a2")
    assert run.input_artifacts["run_id"] == "run_1"
    assert run.input_artifacts["dump_id"] == "dump_1"
    assert passport.schema == "decision_passport"
    assert passport.trace_hash == same_passport.trace_hash
    assert passport.input_checksums == {"indices": "abc"}


def test_decision_support_workflow_rejects_unscoped_case() -> None:
    use_case = RankingUseCase(
        context=ScopedAnalysisContext(),
        primary_metric="h",
        fraction_mode="strict_authors_count",
    )

    try:
        decision_support_workflow.ranking_decision_case(use_case)
    except ValueError as exc:
        assert "выбранный расчет или локальный срез" in str(exc)
    else:
        raise AssertionError("decision-support scenarios must keep the scoped analysis contract")
