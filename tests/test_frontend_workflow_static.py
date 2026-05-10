from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_progress_component_uses_structured_phases() -> None:
    component = (ROOT / "apps/web/src/components/JobProgress.tsx").read_text(encoding="utf-8")
    assert "progress_phases" in component
    assert "determinate" in component
    assert "phaseStateLabel" in component
    assert "Скачивание файлов" in component
    assert "Расчет индексов" in component


def test_workbench_uses_scope_and_data_selection_hooks() -> None:
    main = (ROOT / "apps/web/src/WorkbenchApp.tsx").read_text(encoding="utf-8")
    assert "useWorkbenchScope" in main
    assert "useDataSelection" in main
    assert "ProgressPanel" in main
    assert "RunCard" in main


def test_data_sorting_does_not_eagerly_refresh_heavy_analytics() -> None:
    main = (ROOT / "apps/web/src/WorkbenchApp.tsx").read_text(encoding="utf-8")
    grid = (ROOT / "apps/web/src/components/ui.tsx").read_text(encoding="utf-8")
    assert 'const dataViewActive = view === "data"' in main
    assert 'const rankingsViewActive = view === "rankings"' in main
    assert 'const analyticsViewActive = view === "statistics"' in main
    assert "enabled: dataViewActive && scopeReady && localDataKindAvailable" in main
    assert "enabled: (rankingsViewActive || analyticsViewActive) && hasLocalAnalyticsData" in main
    assert 'sort: ""' in main
    assert "enabled: analyticsViewActive && hasLocalAnalyticsData && scientometricMetrics.length > 0" in main
    assert "{ signal }) => getJson<TableResponse>" in main
    assert "data: rows" in grid
    assert "manualSorting: Boolean(onSortChange)" in grid
    assert "getSortedRowModel" not in grid
    assert "rows.filter" not in grid


def test_formula_and_tooltip_ui_stay_in_dedicated_components() -> None:
    indices_view = (ROOT / "apps/web/src/features/indices/IndicesView.tsx").read_text(encoding="utf-8")
    formula_component = (ROOT / "apps/web/src/features/formulas/FormulaBuilder.tsx").read_text(encoding="utf-8")
    assert "FormulaBuilderDialog" in indices_view
    assert "formula-builder" in formula_component
    assert "MetricInfoPopover" in formula_component
    assert "modal-backdrop" in formula_component


def test_analytics_and_indices_are_feature_views() -> None:
    main = (ROOT / "apps/web/src/WorkbenchApp.tsx").read_text(encoding="utf-8")
    analytics = (ROOT / "apps/web/src/features/analytics/AnalyticsView.tsx").read_text(encoding="utf-8")
    indices = (ROOT / "apps/web/src/features/indices/IndicesView.tsx").read_text(encoding="utf-8")
    assert "function StatisticsPage" not in main
    assert "function RankingsPage" not in main
    assert "export function AnalyticsView" in analytics
    assert "export function IndicesView" in indices


def test_analytics_uses_explicit_author_marker_search() -> None:
    analytics = (ROOT / "apps/web/src/features/analytics/AnalyticsView.tsx").read_text(encoding="utf-8")
    data_view = (ROOT / "apps/web/src/features/data/DataView.tsx").read_text(encoding="utf-8")
    assert "analytics-author-marker-search" in analytics
    assert "Показать выбранных авторов точками" in analytics
    assert "Распределения строятся агрегированно по всем авторам выборки" in analytics
    assert "Показать всех авторов точками" not in data_view
