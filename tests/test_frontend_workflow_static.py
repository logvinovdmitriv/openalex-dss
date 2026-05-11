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


def test_slice_storage_labels_distinguish_archive_and_local_footprint() -> None:
    progress = (ROOT / "apps/web/src/components/JobProgress.tsx").read_text(encoding="utf-8")
    downloaded = (ROOT / "apps/web/src/features/slices/DownloadedSlices.tsx").read_text(encoding="utf-8")
    estimate = (ROOT / "apps/web/src/features/slices/EstimatePanels.tsx").read_text(encoding="utf-8")
    main = (ROOT / "apps/web/src/WorkbenchApp.tsx").read_text(encoding="utf-8")

    assert "Архив OpenAlex" in progress
    assert "Ориентир временной загрузки" in progress
    assert "Файл среза:" not in progress
    assert "Ориентир загрузки" not in progress

    assert "total_known_bytes" in downloaded
    assert "raw_package_bytes" in downloaded
    assert "Полный локальный объем среза" in downloaded
    assert "Все хранилище DSS" in downloaded
    assert "Путь к архиву OpenAlex" in downloaded
    assert "Пакет загрузки" not in downloaded
    assert "Размер файла среза" not in downloaded

    assert "Оценка объема API" in estimate
    assert "полные метаданные" in estimate
    assert "raw/API" not in estimate

    assert "Прогноз полных метаданных" in main
    assert "Прогноз загрузки" not in main
    assert "установленный загрузчик OpenAlex требует ключ" not in main


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
    assert "enabled: analyticsViewActive && hasLocalAnalyticsData && effectiveScientometricMetrics.length > 0" in main
    assert "includeCustomMetricsInAnalysis" in main
    assert "analyticsCustomMetrics" in main
    assert "{ signal }) => getJson<TableResponse>" in main
    assert "data: rows" in grid
    assert "manualSorting: Boolean(onSortChange)" in grid
    assert "schema?.sortable === true" in grid
    assert "schema?.filterable === true" in grid
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


def test_collapsed_boxplot_does_not_stretch_to_extreme_values() -> None:
    analytics = (ROOT / "apps/web/src/features/analytics/AnalyticsView.tsx").read_text(encoding="utf-8")
    assert "const collapsed = Boolean" in analytics
    assert "const min = collapsed ? q1" in analytics
    assert "const max = collapsed ? q3" in analytics
    assert "viewBox=\"0 0 360 260\"" in analytics
    assert "boxplotAxisValues" in analytics
    assert "className={row.collapsed ? \"boxplot-box collapsed\" : \"boxplot-box\"}" in analytics
    assert "boxplot-caption" in analytics
    assert "верхняя граница</text>" not in analytics
    assert "boxplotScaleMode" in analytics
    assert "до 95-го процентиля" in analytics
    assert "boxplotScaleCap" in analytics
    assert "Верхний ус IQR" in analytics
    assert "boxplot-scale-cap" in analytics
    assert "boxplotDataMode" in analytics
    assert "только ненулевые" in analytics
    assert "boxplotForDataMode" in analytics
