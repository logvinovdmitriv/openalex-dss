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
    assert 'const dataViewActive = view === "data"' in main
    assert 'const rankingsViewActive = view === "rankings"' in main
    assert 'const analyticsViewActive = view === "statistics"' in main
    assert "enabled: dataViewActive && scopeReady && localDataKindAvailable" in main
    assert "enabled: rankingsViewActive && hasLocalAnalyticsData" in main
    assert "enabled: analyticsViewActive && hasLocalAnalyticsData && scientometricMetrics.length > 0" in main


def test_formula_and_tooltip_ui_stay_in_dedicated_components() -> None:
    main = (ROOT / "apps/web/src/WorkbenchApp.tsx").read_text(encoding="utf-8")
    formula_component = (ROOT / "apps/web/src/features/formulas/FormulaBuilder.tsx").read_text(encoding="utf-8")
    assert "FormulaBuilderDialog" in main
    assert "formula-builder" in formula_component
    assert "MetricInfoPopover" in formula_component
    assert "modal-backdrop" in formula_component
