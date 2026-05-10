import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Sigma } from "lucide-react";
import { Area, Brush, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { API_BASE, getJson, type CustomMetricDefinition, type TableColumnFilters, type TableResponse } from "../../api";
import { filterParams, fmt, metricLabel, type ActiveFilters } from "../../domain";
import { DownloadLink, EmptyState, MetricCard } from "../../components/ui";
import { customMetricDefsQuery, dataSelectionQuery, localDataPreviewUrl, mutationError, type LocalDataKind, type ScientometricAnalysisPayload, type ScientometricFinding } from "../../workbench";
import { metricLabelFor } from "../formulas/FormulaBuilder";
import { selectedAuthorIndexTable } from "../indices/IndicesView";

export function AnalyticsView({
  filters,
  scientometrics,
  authorIndexTable,
  loadingScientometrics,
  scientometricsError,
  hasAuthorIndices,
  onRecalculate,
  canRecalculate,
  recalculating,
  metric,
  fractionMode,
  runId,
  dumpId,
  metricLabels,
  customMetrics,
  scientometricMetrics,
  baselineMetric,
  rankTopN,
  dataFilters,
  dataKind,
  dataSearch,
  selectedAuthorIds,
  setSelectedAuthorIds,
  selectedAuthorRows: savedSelectedAuthorRows,
  setSelectedAuthorRows,
}: {
  filters: ActiveFilters;
  scientometrics?: ScientometricAnalysisPayload;
  authorIndexTable?: TableResponse;
  loadingScientometrics: boolean;
  scientometricsError: unknown;
  hasAuthorIndices: boolean;
  onRecalculate: () => void;
  canRecalculate: boolean;
  recalculating: boolean;
  metric: string;
  fractionMode: string;
  runId: string;
  dumpId: string;
  metricLabels: Record<string, string>;
  customMetrics: CustomMetricDefinition[];
  scientometricMetrics: string[];
  baselineMetric: string;
  rankTopN: number;
  dataFilters: TableColumnFilters;
  dataKind?: LocalDataKind;
  dataSearch: string;
  selectedAuthorIds: string[];
  setSelectedAuthorIds: (value: string[]) => void;
  selectedAuthorRows: Record<string, unknown>[];
  setSelectedAuthorRows: (value: Record<string, unknown>[]) => void;
}) {
  const metrics = (scientometrics?.metrics ?? scientometricMetrics).filter(Boolean);
  const analyticsMetrics = metrics.length ? metrics : [metric].filter(Boolean);
  const warnings = (scientometrics?.warnings ?? []).filter((warning) => !/Кендалл|Kendall/i.test(String(warning)));
  const [showBoxplot, setShowBoxplot] = useState(true);
  const [boxplotScaleMode, setBoxplotScaleMode] = useState<BoxplotScaleMode>("p95");
  const [boxplotDataMode, setBoxplotDataMode] = useState<BoxplotDataMode>("nonzero");
  const [authorSearch, setAuthorSearch] = useState("");
  const pageSelectedAuthorRows = selectedAuthorIndexTable(authorIndexTable, analyticsMetrics, selectedAuthorIds)?.rows ?? [];
  const selectedAuthorRows = mergeAuthorRows(savedSelectedAuthorRows, pageSelectedAuthorRows, selectedAuthorIds);
  const authorSearchQuery = useQuery({
    queryKey: ["analytics-author-marker-search", runId, dumpId, fractionMode, authorSearch.trim(), JSON.stringify(dataFilters)],
    queryFn: ({ signal }) => getJson<TableResponse>(localDataPreviewUrl("indices", {
      q: authorSearch,
      runId,
      dumpId,
      limit: 12,
      offset: 0,
      sort: "author_display_name",
      direction: "asc",
      fractionMode,
      dataFilters,
    }), { signal }),
    enabled: Boolean((runId || dumpId) && authorSearch.trim().length >= 2),
    staleTime: 60_000,
  });
  const scientometricMetricParam = scientometricMetrics.join(",");
  const selectionQuery = dataSelectionQuery({ kind: dataKind, filters: dataFilters, search: dataSearch, sort: "", direction: "desc", limit: 0 });
  const scientometricParams = filterParams(filters, {
    fraction_mode: fractionMode,
    metrics: scientometricMetricParam,
    baseline_metric: baselineMetric,
    top_n: rankTopN,
    run_id: runId,
    dump_id: dumpId,
    custom_metric_defs: customMetricDefsQuery(customMetrics),
    ...selectionQuery,
  });
  const hasAnalyticsExportScope = Boolean(runId || dumpId);
  const analyticsDownloads = {
    descriptive: `${API_BASE}/analytics/scientometrics/descriptive.csv?${scientometricParams.toString()}`,
    correlations: `${API_BASE}/analytics/scientometrics/correlations.csv?${scientometricParams.toString()}`,
    findings: `${API_BASE}/analytics/scientometrics/findings.csv?${scientometricParams.toString()}`,
    conclusion: `${API_BASE}/analytics/scientometrics/conclusion.md?${scientometricParams.toString()}`,
  };

  return (
    <div className="stack">
      <section className="notice">
        <b>Аналитика построена по выборке из “Данных”</b>
        <span>Расчеты и графики используют всех авторов выбранного среза. Поиск и фильтры из вкладки “Данные” могут сузить выборку; сортировка и текущая страница таблицы на расчеты не влияют.</span>
      </section>
      {!hasAuthorIndices && (
        <section className="notice warn action-notice">
          <div>
            <b>Для графиков нужен расчет индексов</b>
            <span>Скачанный срез содержит работы и авторства. Аналитика строится по авторской таблице “Авторы и индексы”. Запустите расчет для выбранного среза, после завершения графики обновятся автоматически.</span>
          </div>
          <button
            type="button"
            className="primary"
            onClick={onRecalculate}
            disabled={recalculating || !canRecalculate}
            title={canRecalculate ? undefined : "Сначала выберите локальный срез"}
          >
            {recalculating ? <Loader2 size={16} className="spin" /> : <Sigma size={16} />} Рассчитать индексы
          </button>
        </section>
      )}
      <section className="panel analytics-hero-panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">Аналитика</span>
            <h2>Аналитика выбранной выборки</h2>
            <p>На этой странице нет отдельных фильтров. Все графики ниже строятся по полному авторскому набору выбранного среза с учетом поиска и фильтров из “Данных”. Чтобы увидеть конкретных авторов на распределениях, найдите их в поле ниже и добавьте как точки.</p>
          </div>
          {loadingScientometrics && <span className="status-chip"><Loader2 size={14} className="spin" /> Обновление</span>}
        </div>
        <div className="analytics-context-line">
          <span><b>Авторов после ограничений:</b> {scientometrics?.n_authors !== undefined ? fmt(Number(scientometrics.n_authors)) : "все"}</span>
          <span><b>Основной показатель:</b> {metricLabelFor(baselineMetric, metricLabels)}</span>
          <span><b>Показатели:</b> {analyticsMetrics.map((item) => metricLabelFor(item, metricLabels)).join(", ")}</span>
        </div>
      </section>
      {Boolean(scientometricsError) && (
        <section className="notice error">
          <b>Не удалось построить аналитический пакет</b>
          <span>{mutationError(scientometricsError)}</span>
        </section>
      )}
      {warnings.length > 0 && (
        <section className="notice warn">
          <b>Ограничения интерпретации</b>
          <ul className="plain-list">
            {warnings.map((warning: string) => <li key={warning}>{analysisWarningLabel(warning, metricLabels)}</li>)}
          </ul>
        </section>
      )}
      <section className="panel author-marker-panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">Авторы на графиках</span>
            <h2>Показать выбранных авторов точками</h2>
            <p>Распределения строятся агрегированно по всем авторам выборки. Отдельные точки добавляются только для выбранных авторов, чтобы графики не перегружались на больших срезах.</p>
          </div>
          {selectedAuthorIds.length > 0 && <button type="button" className="ghost-button" onClick={() => { setSelectedAuthorIds([]); setSelectedAuthorRows([]); }}>Снять все точки</button>}
        </div>
        <div className="form-grid tight">
          <label>
            <span>Поиск автора</span>
            <input value={authorSearch} onChange={(event) => setAuthorSearch(event.target.value)} placeholder="Введите фамилию, имя или OpenAlex ID" />
          </label>
        </div>
        {authorSearch.trim().length > 0 && authorSearch.trim().length < 2 && <small className="field-hint">Введите минимум 2 символа.</small>}
        {authorSearchQuery.isFetching && <div className="table-loading-line" aria-label="Поиск авторов" />}
        {authorSearchQuery.data?.rows?.length ? (
          <div className="author-marker-results" role="list" aria-label="Найденные авторы">
            {authorSearchQuery.data.rows.map((row) => {
              const id = String(row.author_id ?? "");
              const selected = selectedAuthorIds.includes(id);
              return (
                <button
                  type="button"
                  key={id || String(row.author_display_name)}
                  className={selected ? "choice-pill active" : "choice-pill"}
                  onClick={() => {
                    if (!id) return;
                    if (selected) {
                      setSelectedAuthorIds(selectedAuthorIds.filter((item) => item !== id));
                      setSelectedAuthorRows(savedSelectedAuthorRows.filter((item) => String(item.author_id ?? "") !== id));
                    } else {
                      setSelectedAuthorIds([...selectedAuthorIds, id]);
                      setSelectedAuthorRows(mergeAuthorRows([...savedSelectedAuthorRows, row], [], [...selectedAuthorIds, id]));
                    }
                  }}
                >
                  <b>{String(row.author_display_name || row.author_name || id)}</b>
                  <span>{fmt(row.p ?? 0)} публ. · h={fmt(row.h ?? 0)} · цит. {fmt(row.c ?? 0)}</span>
                </button>
              );
            })}
          </div>
        ) : authorSearch.trim().length >= 2 && !authorSearchQuery.isFetching ? (
          <EmptyState title="Автор не найден" detail="Проверьте написание или измените ограничения во вкладке “Данные”." />
        ) : null}
        {selectedAuthorRows.length > 0 ? (
          <div className="selection-summary active">
            <b>Точки на графиках:</b>
            {selectedAuthorRows.map((row) => {
              const id = String(row.author_id ?? "");
              return (
                <button key={id} type="button" className="selection-chip active" onClick={() => {
                  setSelectedAuthorIds(selectedAuthorIds.filter((item) => item !== id));
                  setSelectedAuthorRows(savedSelectedAuthorRows.filter((item) => String(item.author_id ?? "") !== id));
                }}>
                  {String(row.author_display_name || id)} ×
                </button>
              );
            })}
          </div>
        ) : (
          <div className="selection-summary">
            <span>Авторы не выбраны. Графики показывают только распределение, без отдельных точек.</span>
          </div>
        )}
      </section>
      {selectedAuthorIds.length > 0 && (
        <section className="notice success">
          <b>На графиках отмечены выбранные авторы</b>
          <span>Красные точки показывают {authorCountText(selectedAuthorIds.length)}, выбранных через поиск или чекбоксы в таблице “Данные”. Распределения и матрицы продолжают считаться по всей отфильтрованной выборке.</span>
        </section>
      )}
      {dataSearch.trim() && selectedAuthorIds.length === 0 && (
        <section className="notice">
          <b>Учитывается поиск из таблицы “Данные”</b>
          <span>Текущий поиск: “{dataSearch.trim()}”. Он применяется вместе с фильтрами столбцов; сортировка и текущая страница таблицы на графики не влияют.</span>
        </section>
      )}
      {!scientometrics && (
        <EmptyState
          title={hasAuthorIndices ? "Нет аналитического пакета" : "Графики появятся после расчета индексов"}
          detail={hasAuthorIndices ? "Выберите расчет или локальный срез, затем дождитесь загрузки данных наукометрического анализа." : "Сейчас выбран только скачанный срез. Он пригоден для просмотра работ, но для статистики нужен авторский расчет."}
        />
      )}
      {scientometrics && Number(scientometrics.n_authors ?? 0) <= 0 && (
        <section className="notice warn action-notice">
          <div>
            <b>Графики пока не построены</b>
            <span>В выбранной области нет авторской таблицы индексов или текущие ограничения из “Данных” отфильтровали всех авторов. Откройте “Данные” → “Авторы и индексы”, проверьте строки, сбросьте ограничения или запустите расчет индексов для выбранного среза.</span>
          </div>
          {!hasAuthorIndices && (
            <button type="button" className="primary" onClick={onRecalculate} disabled={recalculating || !canRecalculate}>
              {recalculating ? <Loader2 size={16} className="spin" /> : <Sigma size={16} />} Рассчитать индексы
            </button>
          )}
        </section>
      )}
      {scientometrics && Number(scientometrics.n_authors ?? 0) > 0 && (
        <>
          <DescriptiveStatsPanel
            payload={scientometrics}
            metrics={analyticsMetrics}
            metricLabels={metricLabels}
            downloads={analyticsDownloads}
            hasExportScope={hasAnalyticsExportScope}
          />
          <DistributionComparisonPanel
            payload={scientometrics}
            metrics={analyticsMetrics}
            metricLabels={metricLabels}
            highlightedAuthors={selectedAuthorRows}
            loading={loadingScientometrics}
          />
          <section className="panel">
            <div className="panel-head split">
              <div>
                <span className="step-badge">Диапазоны</span>
                <h2>Разброс значений</h2>
                <p>Ящик с усами показывает медиану, квартильный диапазон Q1–Q3 и значения за пределами типичного диапазона по правилу 1,5 × IQR.</p>
              </div>
              <div className="boxplot-actions">
                <label>
                  <span>Шкала</span>
                  <select value={boxplotScaleMode} onChange={(event) => setBoxplotScaleMode(event.target.value as BoxplotScaleMode)}>
                    <option value="p95">до 95-го процентиля</option>
                    <option value="p99">до 99-го процентиля</option>
                    <option value="all">все значения</option>
                  </select>
                </label>
                <label>
                  <span>Данные ящика</span>
                  <select value={boxplotDataMode} onChange={(event) => setBoxplotDataMode(event.target.value as BoxplotDataMode)}>
                    <option value="nonzero">только ненулевые</option>
                    <option value="central95">центральные 95%</option>
                    <option value="all">все значения</option>
                  </select>
                </label>
                <button type="button" className={showBoxplot ? "choice-pill active" : "choice-pill"} onClick={() => setShowBoxplot(!showBoxplot)}>
                  {showBoxplot ? "Скрыть ящик с усами" : "Показать ящик с усами"}
                </button>
              </div>
            </div>
            {showBoxplot && <MetricBoxplotPanel payload={scientometrics} metrics={analyticsMetrics} metricLabels={metricLabels} scaleMode={boxplotScaleMode} dataMode={boxplotDataMode} />}
          </section>
          <CorrelationMatrixPanel payload={scientometrics} method="spearman" metrics={analyticsMetrics} metricLabels={metricLabels} />
          <FindingsPanel payload={scientometrics} metricLabels={metricLabels} />
          <ConclusionDraftPanel payload={scientometrics} metricLabels={metricLabels} />
        </>
      )}
    </div>
  );
}

function DescriptiveStatsPanel({
  payload,
  metrics,
  metricLabels,
  downloads,
  hasExportScope,
}: {
  payload: ScientometricAnalysisPayload;
  metrics: string[];
  metricLabels?: Record<string, string>;
  downloads: Record<string, string>;
  hasExportScope: boolean;
}) {
  const rows = metrics
    .map((metricName) => {
      const descriptive = (payload.descriptive ?? {})[metricName] ?? {};
      const boxplot = (payload.boxplots ?? {})[metricName] ?? {};
      const hasData = Number(descriptive.n ?? 0) > 0 || [descriptive.median, descriptive.mean, boxplot.outlier_count].some((value) => Number.isFinite(Number(value)));
      return {
        metricName,
        n: Number(descriptive.n ?? 0),
        mean: numberOrNull(descriptive.mean),
        median: numberOrNull(descriptive.median ?? boxplot.median),
        q1: numberOrNull(descriptive.q1 ?? boxplot.q1),
        q3: numberOrNull(descriptive.q3 ?? boxplot.q3),
        min: numberOrNull(descriptive.min ?? boxplot.min_whisker),
        max: numberOrNull(descriptive.max ?? boxplot.max_whisker),
        stddev: numberOrNull(descriptive.stddev),
        outliers: Number(boxplot.outlier_count ?? 0),
        hasData,
      };
    })
    .filter((row) => row.hasData);
  const baselineMetric = String(payload.scope?.baseline_metric ?? "");
  return (
    <section className="panel">
      <div className="panel-head split">
        <div>
          <span className="step-badge">Сводная статистика</span>
          <h2>Описательная статистика по показателям</h2>
          <p>Таблица показывает базовые характеристики распределения: число наблюдений, среднее, медиану, квартильный диапазон Q1–Q3, размах, стандартное отклонение и выбросы по правилу 1,5 × IQR.</p>
        </div>
        <div className="download-inline">
          {hasExportScope && <DownloadLink href={downloads.descriptive} label="Сводная таблица" compact />}
          {hasExportScope && <DownloadLink href={downloads.correlations} label="Связь показателей" compact />}
          {hasExportScope && <DownloadLink href={downloads.findings} label="Выводы" compact />}
          {hasExportScope && <DownloadLink href={downloads.conclusion} label="Заключение" compact />}
        </div>
      </div>
      <div className="table-wrap stats-summary-table">
        <table>
          <thead>
            <tr>
              <th>Показатель</th>
              <th>Наблюдений</th>
              <th>Среднее</th>
              <th>Медиана</th>
              <th>Q1–Q3</th>
              <th>Мин–макс</th>
              <th>Ст. отклонение</th>
              <th>Выбросы IQR</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.metricName} className={row.metricName === baselineMetric ? "summary-baseline-row" : undefined}>
                <td><b>{metricLabelFor(row.metricName, metricLabels)}</b>{row.metricName === baselineMetric ? <span className="muted-inline"> основной</span> : null}</td>
                <td>{fmt(row.n)}</td>
                <td>{formatNullableAnalysisValue(row.mean)}</td>
                <td>{formatNullableAnalysisValue(row.median)}</td>
                <td>{formatNullableRange(row.q1, row.q3)}</td>
                <td>{formatNullableRange(row.min, row.max)}</td>
                <td>{formatNullableAnalysisValue(row.stddev)}</td>
                <td>{fmt(row.outliers)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function mergeAuthorRows(
  savedRows: Record<string, unknown>[],
  pageRows: Record<string, unknown>[],
  selectedAuthorIds: string[],
) {
  const selected = new Set(selectedAuthorIds.map(String));
  const byId = new Map<string, Record<string, unknown>>();
  [...savedRows, ...pageRows].forEach((row) => {
    const id = String(row.author_id ?? "");
    if (id && selected.has(id)) byId.set(id, row);
  });
  return selectedAuthorIds.map((id) => byId.get(String(id))).filter(Boolean) as Record<string, unknown>[];
}

function formatNullableAnalysisValue(value: number | null) {
  return value === null ? "—" : formatAnalysisValue(value);
}

function formatNullableRange(left: number | null, right: number | null) {
  if (left === null && right === null) return "—";
  return `${formatNullableAnalysisValue(left)} – ${formatNullableAnalysisValue(right)}`;
}

function analysisWarningLabel(warning: string, metricLabels?: Record<string, string>) {
  const text = String(warning || "");
  const iqrMatch = text.match(/IQR is zero for metrics? ([^;.]+)[.;]/i);
  if (iqrMatch) {
    const metrics = iqrMatch[1]
      .split(/,\s*/)
      .map((item) => metricLabelFor(item.trim(), metricLabels))
      .join(", ");
    return `Для показателей ${metrics} межквартильный размах равен нулю; границы выбросов по правилу 1,5 × IQR здесь неинформативны.`;
  }
  if (/IQR outlier fences are not informative/i.test(text)) {
    return "Межквартильный размах равен нулю; границы выбросов по правилу 1,5 × IQR здесь неинформативны.";
  }
  return text;
}

const CHART_COLORS = ["#155e75", "#167343", "#5b5fc7", "#0f766e", "#7c3aed", "#8a5a00", "#2563eb", "#64748b"];

function DistributionComparisonPanel({
  payload,
  metrics,
  metricLabels,
  highlightedAuthors,
  loading = false,
}: {
  payload: ScientometricAnalysisPayload;
  metrics: string[];
  metricLabels?: Record<string, string>;
  highlightedAuthors?: Record<string, unknown>[];
  loading?: boolean;
}) {
  const visibleMetrics = metrics.filter(Boolean);
  const rows = visibleMetrics
    .map((metricName) => ({ metricName, rows: rawDistributionRows(payload, metricName) }))
    .filter((item) => item.rows.length > 0);
  const highlightRows = selectedAuthorDistributionMarkers(payload, visibleMetrics, highlightedAuthors ?? []);
  const hasHighlights = highlightRows.length > 0;
  return (
    <section className="panel analytics-main-chart">
      <div className="panel-head split">
        <div>
          <span className="step-badge">Распределение</span>
          <h2>Распределение авторов по показателям</h2>
          <p>Каждый показатель показан отдельно в собственной шкале. По горизонтали — значение показателя, по вертикали — число авторов. Нижняя полоса позволяет приблизить нужный диапазон.</p>
        </div>
        {loading && <span className="status-chip"><Loader2 size={14} className="spin" /> Обновление</span>}
      </div>
      {hasHighlights && (
        <div className="selection-summary active">
          <span>Красные точки показывают авторов, выбранных в таблице выше.</span>
        </div>
      )}
      {visibleMetrics.length === 0 || rows.length === 0 ? (
        <EmptyState title="Выберите хотя бы один показатель" detail="Включите показатель во вкладке “Индексы” или в конструкторе собственной формулы." />
      ) : (
        <div className="distribution-small-multiples">
          {rows.map((item, index) => (
            <div key={item.metricName} className="distribution-multiple-card">
              <div className="distribution-multiple-head">
                <b>{metricLabelFor(item.metricName, metricLabels)}</b>
                <span>{fmt(item.rows.reduce((sum, row) => sum + row.count, 0))} авторов</span>
              </div>
              <div className="chart-box index-distribution-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={item.rows} margin={{ left: 8, right: 14, top: 8, bottom: 30 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e7edf4" />
                    <XAxis dataKey="center" type="number" tickFormatter={(value) => fmt(value)} domain={["dataMin", "dataMax"]} />
                    <YAxis allowDecimals={false} label={{ value: "Авторов", angle: -90, position: "insideLeft" }} />
                    <Tooltip
                      labelFormatter={(_, payloadRows) => {
                        const row = payloadRows?.[0]?.payload;
                        if (row?.author) return `${row.author}: ${formatAnalysisValue(row.value)}`;
                        return row ? `${formatAnalysisValue(row.lo)} – ${formatAnalysisValue(row.hi)}` : "";
                      }}
                      formatter={(value, _name, item: unknown) => {
                        const tooltipItem = item && typeof item === "object" ? item as { payload?: Record<string, unknown> } : {};
                        const tooltipPayload = tooltipItem.payload ?? {};
                        if (tooltipPayload.author) return [`${metricLabelFor(String(tooltipPayload.metricName), metricLabels)}: ${formatAnalysisValue(tooltipPayload.value)}`, "выбранный автор"];
                        return [fmt(value), "авторов"];
                      }}
                    />
                    <Area type="monotone" dataKey="count" fill={CHART_COLORS[index % CHART_COLORS.length]} fillOpacity={0.14} stroke="none" isAnimationActive={false} />
                    <Line type="monotone" dataKey="count" stroke={CHART_COLORS[index % CHART_COLORS.length]} strokeWidth={3} dot={false} activeDot={{ r: 4 }} name="Авторов" />
                    <Scatter
                      name="Выбранные авторы"
                      data={highlightRows.filter((row) => row.metricName === item.metricName)}
                      dataKey="count"
                      fill="#be123c"
                      shape="circle"
                    />
                    <Brush dataKey="center" height={18} travellerWidth={8} tickFormatter={(value) => fmt(value)} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

type DistributionMarker = {
  center?: number;
  count: number;
  value: number;
  metricName: string;
  author: string;
};

function selectedAuthorDistributionMarkers(
  payload: ScientometricAnalysisPayload,
  metrics: string[],
  authors: Record<string, unknown>[],
): DistributionMarker[] {
  if (!authors.length) return [];
  return metrics.flatMap((metricName) => {
    const bins = rawDistributionRows(payload, metricName);
    if (!bins.length) return [];
    const out: DistributionMarker[] = [];
    authors.forEach((author) => {
        const value = Number(author[metricName]);
        if (!Number.isFinite(value)) return;
        const authorName = String(author.author_display_name || author.author_id || "Выбранный автор");
        const nearest = nearestRawDistributionBin(bins, value);
        out.push({
          center: value,
          count: Math.max(1, Number(nearest?.count ?? 1)),
          value,
          metricName,
          author: authorName,
        });
      });
    return out;
  });
}

function nearestRawDistributionBin(rows: ReturnType<typeof rawDistributionRows>, value: number) {
  return rows.reduce<(typeof rows)[number] | null>((best, row) => {
    if (value >= row.lo && value <= row.hi) return row;
    if (!best) return row;
    return Math.abs(row.center - value) < Math.abs(best.center - value) ? row : best;
  }, null);
}

function rawDistributionRows(payload: ScientometricAnalysisPayload, metricName: string) {
  const histogram = ((payload.histograms ?? {})[metricName]?.raw ?? []) as Array<Record<string, unknown>>;
  return histogram
    .map((row, index) => ({
      lo: Number(row.lo),
      hi: Number(row.hi),
      center: (Number(row.lo) + Number(row.hi)) / 2,
      count: Number(row.count ?? 0),
      bin: index + 1,
    }))
    .filter((row) => Number.isFinite(row.center) && Number.isFinite(row.count) && row.count >= 0);
}

type BoxplotScaleMode = "p95" | "p99" | "all";
type BoxplotDataMode = "all" | "nonzero" | "central95";

function MetricBoxplotPanel({ payload, metrics, metricLabels, scaleMode, dataMode }: { payload: ScientometricAnalysisPayload; metrics: string[]; metricLabels?: Record<string, string>; scaleMode: BoxplotScaleMode; dataMode: BoxplotDataMode }) {
  const rows = metrics
    .map((metricName) => {
      const fullBoxplot = (payload.boxplots ?? {})[metricName] ?? {};
      const boxplot = boxplotForDataMode(fullBoxplot, dataMode);
      const descriptive = (payload.descriptive ?? {})[metricName] ?? {};
      const q1 = numberOrNull(boxplot.q1);
      const median = numberOrNull(boxplot.median);
      const q3 = numberOrNull(boxplot.q3);
      const iqr = numberOrNull(boxplot.iqr);
      const collapsed = Boolean(iqr === 0 || (q1 !== null && median !== null && q3 !== null && q1 === median && median === q3));
      const min = collapsed ? q1 : numberOrNull(boxplot.min_whisker ?? boxplot.min);
      const max = collapsed ? q3 : numberOrNull(boxplot.max_whisker ?? boxplot.max);
      if (![min, q1, median, q3, max].every((value) => value !== null)) return null;
      const left = Math.min(min as number, q1 as number, median as number, q3 as number, max as number);
      const right = Math.max(min as number, q1 as number, median as number, q3 as number, max as number);
      const observedMax = numberOrNull(fullBoxplot.max);
      const scaleCap = boxplotScaleCap(scaleMode, descriptive, observedMax);
      return {
        metricName,
        min: min as number,
        q1: q1 as number,
        median: median as number,
        q3: q3 as number,
        max: max as number,
        n: Number(boxplot.n ?? 0),
        fullN: Number(fullBoxplot.n ?? descriptive.n ?? 0),
        outliers: Number(boxplot.display_outlier_count ?? boxplot.outlier_count ?? 0),
        domainMin: left,
        domainMax: right,
        observedMin: numberOrNull(fullBoxplot.min),
        observedMax,
        scaleCap,
        collapsed,
      };
    })
    .filter(Boolean) as Array<{
      metricName: string;
      min: number;
      q1: number;
      median: number;
      q3: number;
      max: number;
      n: number;
      fullN: number;
      outliers: number;
      domainMin: number;
      domainMax: number;
      observedMin: number | null;
      observedMax: number | null;
      scaleCap: number | null;
      collapsed: boolean;
    }>;
  if (!rows.length) {
    return <EmptyState title="Нет диапазонов" detail="Для выбранных индексов нет достаточного числа числовых значений." />;
  }
  return (
    <div className="boxplot-svg-list">
      {rows.map((row) => {
        const scaleMax = row.scaleCap ?? row.observedMax;
        const visualMin = Math.min(row.domainMin, row.observedMin ?? row.domainMin);
        const visualMax = Math.max(row.domainMax, scaleMax ?? row.domainMax);
        const domain = expandedBoxplotDomain(visualMin, visualMax, null, null, false);
        const y = (value: number) => {
          const top = 24;
          const bottom = 224;
          const height = bottom - top;
          return bottom - ((value - domain.min) / (domain.max - domain.min)) * height;
        };
        const yClamped = (value: number) => {
          const raw = y(value);
          return Math.max(24, Math.min(224, raw));
        };
        const minY = yClamped(row.min);
        const q1Y = yClamped(row.q1);
        const medianY = yClamped(row.median);
        const q3Y = yClamped(row.q3);
        const maxY = yClamped(row.max);
        const boxY = Math.min(q1Y, q3Y);
        const boxHeight = Math.max(6, Math.abs(q3Y - q1Y));
        const boxCenterX = 178;
        const axisValues = boxplotAxisValues(domain.min, domain.max);
        const scaleCapY = scaleMax !== null ? yClamped(scaleMax) : null;
        return (
          <div key={row.metricName} className="boxplot-svg-row">
            <div className="boxplot-svg-title">
              <b>{metricLabelFor(row.metricName, metricLabels)}</b>
              <span>
                {row.collapsed
                  ? `Основная масса значений равна ${formatAnalysisValue(row.median)}`
                  : `Q1 ${formatAnalysisValue(row.q1)} · медиана ${formatAnalysisValue(row.median)} · Q3 ${formatAnalysisValue(row.q3)}`}
                {row.n !== row.fullN ? ` · учтено ${fmt(row.n)} из ${fmt(row.fullN)}` : ""}
                {row.observedMax !== null ? ` · максимум ${formatAnalysisValue(row.observedMax)}` : ""}
              </span>
            </div>
            <svg viewBox="0 0 360 260" role="img" aria-label={`Ящик с усами для ${metricLabelFor(row.metricName, metricLabels)}`} className="boxplot-svg">
              <line x1="58" y1="24" x2="58" y2="224" className="boxplot-axis" />
              {axisValues.map((value, index) => (
                <g key={`${row.metricName}-${index}-${value}`}>
                  <line x1="52" y1={y(value)} x2="64" y2={y(value)} className="boxplot-axis-tick" />
                  <text x="46" y={y(value) + 4} textAnchor="end">{formatAnalysisValue(value)}</text>
                </g>
              ))}
              <line x1={boxCenterX} y1={maxY} x2={boxCenterX} y2={minY} className="boxplot-whisker" />
              <line x1={boxCenterX - 24} y1={maxY} x2={boxCenterX + 24} y2={maxY} className="boxplot-cap" />
              <line x1={boxCenterX - 24} y1={minY} x2={boxCenterX + 24} y2={minY} className="boxplot-cap" />
              <rect x={boxCenterX - 36} y={boxY} width="72" height={boxHeight} rx="2" className={row.collapsed ? "boxplot-box collapsed" : "boxplot-box"} />
              <line x1={boxCenterX - 42} y1={medianY} x2={boxCenterX + 42} y2={medianY} className="boxplot-median" />
              {scaleCapY !== null && scaleMode !== "all" && (
                <line x1="92" y1={scaleCapY} x2="304" y2={scaleCapY} className="boxplot-scale-cap">
                  <title>{boxplotScaleLabel(scaleMode, row.scaleCap)}</title>
                </line>
              )}
            </svg>
            <div className="boxplot-caption">
              <span>{boxplotDataModeLabel(dataMode)}</span>
              <span>{boxplotScaleLabel(scaleMode, row.scaleCap)}</span>
              <span>Нижний ус IQR: {formatAnalysisValue(row.min)}</span>
              <span>Q1: {formatAnalysisValue(row.q1)}</span>
              <span>Медиана: {formatAnalysisValue(row.median)}</span>
              <span>Q3: {formatAnalysisValue(row.q3)}</span>
              <span>Верхний ус IQR: {formatAnalysisValue(row.max)}</span>
              {row.observedMax !== null && <span>Максимум: {formatAnalysisValue(row.observedMax)}</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function boxplotScaleCap(mode: BoxplotScaleMode, descriptive: Record<string, unknown>, observedMax: number | null) {
  if (mode === "all") return observedMax;
  const percentile = numberOrNull(mode === "p99" ? descriptive.p99 : descriptive.p95);
  if (percentile === null) return observedMax;
  if (observedMax === null) return percentile;
  return Math.min(observedMax, percentile);
}

function boxplotForDataMode(boxplot: Record<string, unknown>, mode: BoxplotDataMode) {
  const views = (boxplot.views && typeof boxplot.views === "object" ? boxplot.views : {}) as Record<string, Record<string, unknown>>;
  const candidate = mode === "nonzero" ? views.nonzero : mode === "central95" ? views.central_95 : boxplot;
  if (candidate && numberOrNull(candidate.q1) !== null && numberOrNull(candidate.q3) !== null) return candidate;
  return boxplot;
}

function boxplotDataModeLabel(mode: BoxplotDataMode) {
  if (mode === "nonzero") return "Данные ящика: нулевые значения исключены";
  if (mode === "central95") return "Данные ящика: центральные 95% значений";
  return "Данные ящика: все значения";
}

function boxplotScaleLabel(mode: BoxplotScaleMode, cap: number | null) {
  if (mode === "all") return "Шкала: все значения";
  return `Шкала: до ${mode === "p99" ? "99-го" : "95-го"} процентиля${cap !== null ? ` (${formatAnalysisValue(cap)})` : ""}`;
}

function expandedBoxplotDomain(domainMin: number, domainMax: number, observedMin: number | null, observedMax: number | null, includeObservedSpread = true) {
  if (domainMax > domainMin) {
    const pad = Math.max((domainMax - domainMin) * 0.08, 0.5);
    return { min: domainMin - pad, max: domainMax + pad };
  }
  const center = domainMin;
  const observedSpread = includeObservedSpread ? Math.max(Math.abs((observedMax ?? center) - center), Math.abs(center - (observedMin ?? center))) : 0;
  const pad = Math.max(observedSpread > 0 ? Math.min(observedSpread, Math.max(1, Math.abs(center))) : 1, 1);
  return { min: center - pad, max: center + pad };
}

function uniqueAxisValues(values: number[]) {
  const out: number[] = [];
  for (const value of values) {
    if (!Number.isFinite(value)) continue;
    if (!out.some((existing) => Math.abs(existing - value) < 1e-9)) out.push(value);
  }
  return out;
}

function boxplotAxisValues(min: number, max: number) {
  if (!(max > min)) return [min];
  const step = (max - min) / 4;
  return uniqueAxisValues([min, min + step, min + step * 2, min + step * 3, max]);
}

function numberOrNull(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function CorrelationMatrixPanel({ payload, method, metrics, metricLabels }: { payload: ScientometricAnalysisPayload; method: "spearman" | "pearson_log1p" | "kendall_tau_b"; metrics: string[]; metricLabels?: Record<string, string> }) {
  const matrix = method === "kendall_tau_b" ? payload?.correlations?.kendall_tau_b?.matrix ?? {} : payload?.correlations?.[method] ?? {};
  const skipped = payload?.correlations?.kendall_tau_b?.skipped ?? [];
  const visibleMetrics = metrics.filter((metricName) => matrix?.[metricName]);
  return (
    <section className="panel correlation-panel-wide">
      <div className="panel-head">
        <span className="step-badge">Связь показателей</span>
        <h2>{correlationLabel(method)} между рейтингами</h2>
        <p>Большая матрица показывает, насколько похоже упорядочиваются авторы по выбранным показателям. Значение ближе к 1 означает более похожий рейтинг.</p>
      </div>
      {method === "kendall_tau_b" && skipped.length > 0 && <div className="notice warn"><b>Часть пар не рассчитана</b><span>Слишком много наблюдений для выбранного способа сравнения. Уточните поиск или ограничения во вкладке “Данные”.</span></div>}
      {visibleMetrics.length < 2 ? (
        <EmptyState title="Недостаточно показателей" detail="Для матрицы нужно выбрать минимум два показателя одной смысловой группы." />
      ) : (
        <div className="correlation-matrix-card wide">
          <div className="heatmap-grid compact-heatmap" style={{ gridTemplateColumns: `minmax(120px, 1fr) repeat(${visibleMetrics.length}, minmax(72px, 1fr))` }}>
            <span />
            {visibleMetrics.map((metricName) => <b key={metricName}>{metricShortLabel(metricName, metricLabels)}</b>)}
            {visibleMetrics.map((left) => (
              <div className="heatmap-row-fragment" key={left}>
                <b>{metricShortLabel(left, metricLabels)}</b>
                {visibleMetrics.map((right) => {
                  const value = matrix?.[left]?.[right];
                  return <span key={`${left}-${right}`} style={{ background: correlationColor(value) }}>{value === null || value === undefined ? "—" : fmt(value)}</span>;
                })}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function FindingsPanel({ payload, metricLabels }: { payload: ScientometricAnalysisPayload; metricLabels?: Record<string, string> }) {
  const findings = payload?.findings ?? [];
  const summary = payload?.finding_summary ?? {};
  if (!findings.length) return null;
  const priority: Record<string, number> = { high: 0, medium: 1, low: 2, informational: 3 };
  const visibleFindings = [...findings]
    .sort((left, right) => (priority[left.severity ?? ""] ?? 9) - (priority[right.severity ?? ""] ?? 9))
    .slice(0, 6);
  const groups: Array<[string, string]> = [
    ["high", "Важные замечания"],
    ["medium", "Требуют внимания"],
    ["low", "Дополнительные замечания"],
    ["informational", "Справочная информация"],
  ];
  return (
    <section className="panel">
      <div className="panel-head">
        <span className="step-badge">Выводы</span>
        <h2>Короткие выводы по показателям</h2>
        <p>Каждый вывод строится по текущей выборке из вкладки “Данные”. Это подсказка для отчета, не экспертное заключение.</p>
      </div>
      <div className="metric-grid">
        <MetricCard label="Выводов" value={fmt(Number(summary.n_findings ?? findings.length))} />
        <MetricCard label="Важных" value={fmt(Number(summary.high_count ?? 0))} />
        <MetricCard label="Требуют внимания" value={fmt(Number(summary.medium_count ?? 0))} />
        <MetricCard label="Рекомендуемый показатель" value={summary.candidate_metric ? metricLabelFor(String(summary.candidate_metric), metricLabels) : "—"} />
      </div>
      {groups.map(([severity, title]) => {
        const items = visibleFindings.filter((item) => item.severity === severity);
        if (!items.length) return null;
        return (
          <div key={severity} className="stack compact-stack">
            <h3>{title}</h3>
            {items.map((item) => (
              <div key={String(item.id)} className={findingNoticeClass(severity)}>
                <b>{findingTitle(item)}</b>
                <span>{String(item.text ?? "")}</span>
                {item.recommendation ? <small>{String(item.recommendation)}</small> : null}
                <div className="method-grid">
                  {findingEvidenceEntries(item.evidence).map(([key, value]) => (
                    <span key={key} className="check-pill">{evidenceLabel(key)}: {formatEvidenceValue(value)}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        );
      })}
      {findings.length > visibleFindings.length && (
        <div className="notice">
          <b>Показаны только ключевые выводы</b>
          <span>Полный список доступен через выгрузку “Таблица выводов”.</span>
        </div>
      )}
    </section>
  );
}

function ConclusionDraftPanel({ payload, metricLabels }: { payload: ScientometricAnalysisPayload; metricLabels?: Record<string, string> }) {
  const draft = payload?.conclusion_draft;
  const paragraphs = draft?.paragraphs ?? [];
  if (!draft || !paragraphs.length) return null;
  return (
    <section className="panel">
      <div className="panel-head">
        <span className="step-badge">Черновик заключения</span>
        <h2>{draft.title ?? "Черновик вывода"}</h2>
        <p>Текст собран из выводов текущей области анализа. Его можно использовать как основу раздела отчета после проверки таблиц и аналитических визуализаций.</p>
      </div>
      <div className="stack compact-stack">
        {paragraphs.map((paragraph, index) => (
          <div key={`${paragraph.role ?? "paragraph"}:${index}`} className="notice">
            <b>{conclusionRoleLabel(String(paragraph.role ?? ""))}</b>
            <span>{paragraph.text ?? ""}</span>
            {(paragraph.evidence_finding_ids ?? []).length > 0 && (
              <small>Основания: {(paragraph.evidence_finding_ids ?? []).join(", ")}</small>
            )}
            {(paragraph.evidence_metrics ?? []).length > 0 && (
              <small>Показатели: {(paragraph.evidence_metrics ?? []).map((item) => metricLabelFor(item, metricLabels)).join(", ")}</small>
            )}
          </div>
        ))}
      </div>
      {(draft.limitations ?? []).length > 0 && (
        <div className="notice warn">
          <b>Ограничения вывода</b>
          <ul className="plain-list">
            {(draft.limitations ?? []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      )}
    </section>
  );
}


function formatAnalysisValue(value: unknown, rate = false) {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return rate ? `${fmt(numeric * 100)}%` : fmt(numeric);
}

function findingNoticeClass(severity: string) {
  if (severity === "high") return "notice error";
  if (severity === "medium") return "notice warn";
  return "notice";
}

function findingTitle(finding: ScientometricFinding) {
  const metric = finding.metric ? metricLabel(String(finding.metric)) : "область анализа";
  const baseline = finding.baseline_metric ? `${metricLabel(String(finding.baseline_metric))} → ` : "";
  return `${findingSeverityLabel(String(finding.severity ?? ""))} · ${baseline}${metric} · ${findingTypeLabel(String(finding.type ?? ""))}`;
}

function findingSeverityLabel(value: string) {
  const labels: Record<string, string> = {
    high: "Важно",
    medium: "Внимание",
    low: "Дополнительно",
    informational: "Справочно",
  };
  return labels[value] ?? value;
}

function findingTypeLabel(value: string) {
  const labels: Record<string, string> = {
    heavy_tail_distribution: "есть резко высокие значения",
    zero_inflation: "много нулевых значений",
    high_tie_rate: "много одинаковых мест",
    publication_volume_dependence: "зависимость от числа публикаций",
    citation_volume_dependence: "зависимость от числа цитирований",
    top1_dominance_dependence: "зависимость от самой цитируемой работы",
    rank_instability: "места сильно меняются",
    rank_agreement: "места совпадают",
    balanced_candidate_metric: "рекомендуемый показатель",
    productivity_metric: "продуктивность",
    citation_volume_metric: "объем цитирования",
  };
  return labels[value] ?? value;
}

function conclusionRoleLabel(value: string) {
  const labels: Record<string, string> = {
    scope: "Область анализа",
    distribution_limits: "Распределения",
    index_limitations: "Различающая способность",
    dependence_limits: "Зависимости показателей",
    correction_effects: "Поправки к показателям",
    rank_comparison: "Сравнение мест",
    candidate_metric: "Рекомендуемый показатель",
    no_data: "Нет данных",
    final_caution: "Ограничение интерпретации",
  };
  return labels[value] ?? value;
}

function findingEvidenceEntries(value: unknown) {
  if (!value || typeof value !== "object") return [] as Array<[string, unknown]>;
  return Object.entries(value as Record<string, unknown>)
    .filter(([, item]) => item === null || ["string", "number", "boolean"].includes(typeof item))
    .slice(0, 5);
}

function evidenceLabel(value: string) {
  const labels: Record<string, string> = {
    skewness: "перекос распределения",
    excess_kurtosis: "резкие крайние значения",
    jarque_bera_p_approx: "отклонение от обычной формы",
    zero_rate: "нулевых",
    tie_rate: "одинаковых мест",
    abs_spearman_rho: "сила связи",
    spearman_rho: "связь показателей",
    direction: "направление",
    p90_abs_delta: "90% изменений",
    median_abs_delta: "медиана изменений",
    jaccard_top_n_exact: "совпадение первых строк",
    rank_top_n: "первые строки",
  };
  return labels[value] ?? value;
}

function formatEvidenceValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "да" : "нет";
  return formatAnalysisValue(value);
}

function metricShortLabel(value: string, metricLabels?: Record<string, string>) {
  if (metricLabels?.[value]) return metricLabels[value];
  const labels: Record<string, string> = {
    p: "Публикации",
    c: "Цитирования",
    c_frac: "Долевые цит.",
    cpp: "Средняя цит.",
    h: "Хирш",
    i10: "10+ цит.",
    g: "Индекс g",
    m_local: "Индекс m",
    top1_share: "Топ-1",
    f5: "Полянин f5",
    fm5: "Полянин fm5",
    iupv: "Собственный интегр.",
    islv: "Собственный сбал.",
    lrdi: "Устойчивость",
  };
  return labels[value] ?? value;
}

function correlationLabel(method: "spearman" | "pearson_log1p" | "kendall_tau_b") {
  if (method === "pearson_log1p") return "Связь численных значений";
  if (method === "kendall_tau_b") return "Совпадение порядка авторов";
  return "Связь мест в рейтинге";
}

function correlationColor(value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "#f3f6f9";
  const alpha = Math.min(0.42, Math.max(0.08, Math.abs(numeric) * 0.32 + 0.1));
  return numeric >= 0 ? `rgba(22, 115, 67, ${alpha})` : `rgba(21, 94, 117, ${alpha})`;
}



function authorCountText(count: number) {
  const value = Math.abs(Number(count) || 0);
  const mod10 = value % 10;
  const mod100 = value % 100;
  if (mod10 === 1 && mod100 !== 11) return `${fmt(count)} автор`;
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return `${fmt(count)} автора`;
  return `${fmt(count)} авторов`;
}
