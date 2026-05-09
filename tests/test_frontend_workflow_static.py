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


def test_formula_and_tooltip_ui_stay_in_dedicated_components() -> None:
    main = (ROOT / "apps/web/src/WorkbenchApp.tsx").read_text(encoding="utf-8")
    assert "FormulaBuilderDialog" in main
    assert "formula-builder" in main
    assert "InfoPopover" in main
    assert "modal-backdrop" in main
