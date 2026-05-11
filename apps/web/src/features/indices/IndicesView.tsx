import { useMemo, useState } from "react";
import { Loader2, Sigma } from "lucide-react";
import type { CustomMetricDefinition, TableColumnSchema, TableResponse } from "../../api";
import { fmt, metricLabel, modeLabel, type SelectOption } from "../../domain";
import { DataGrid, Field, MetricCard } from "../../components/ui";
import { FormulaBuilderDialog, MetricInfoPopover, metricLabelFor } from "../formulas/FormulaBuilder";

export function IndicesView({
  metric,
  setMetric,
  rankingDirection,
  setRankingDirection,
  fractionMode,
  setFractionMode,
  ranking,
  authorIndexTable,
  selectedMetrics,
  setSelectedMetrics,
  includeCustomMetricsInAnalysis,
  setIncludeCustomMetricsInAnalysis,
  customMetrics,
  setCustomMetrics,
  onSaveCustomMetric,
  onDeleteCustomMetric,
  customMetricPersistenceReady,
  selectedAuthorIds,
  metricOptions,
  metricLabels,
  fractionModeOptions,
  onRecalculate,
  canRecalculate,
  recalculating,
  usingActiveContextScope,
  effectiveDumpId,
  onSelect,
}: {
  metric: string;
  setMetric: (value: string) => void;
  rankingDirection: "asc" | "desc";
  setRankingDirection: (value: "asc" | "desc") => void;
  fractionMode: string;
  setFractionMode: (value: string) => void;
  ranking?: TableResponse;
  authorIndexTable?: TableResponse;
  selectedMetrics: string[];
  setSelectedMetrics: (value: string[]) => void;
  includeCustomMetricsInAnalysis: boolean;
  setIncludeCustomMetricsInAnalysis: (value: boolean) => void;
  customMetrics: CustomMetricDefinition[];
  setCustomMetrics: (value: CustomMetricDefinition[]) => void;
  onSaveCustomMetric: (value: CustomMetricDefinition) => Promise<unknown>;
  onDeleteCustomMetric: (id: string) => Promise<unknown>;
  customMetricPersistenceReady: boolean;
  selectedAuthorIds: string[];
  metricOptions: SelectOption[];
  metricLabels: Record<string, string>;
  fractionModeOptions: SelectOption[];
  onRecalculate: () => void;
  canRecalculate: boolean;
  recalculating: boolean;
  usingActiveContextScope: boolean;
  effectiveDumpId: string;
  onSelect: (value: { kind: "author" | "work"; id: string }) => void;
}) {
  const displayMetricOptions = ensureCurrentOptions(metricOptions, [metric, ...selectedMetrics]);
  const visibleMetrics = [...new Set([metric, ...selectedMetrics])].filter(Boolean);
  const [formulaBuilderOpen, setFormulaBuilderOpen] = useState(false);
  const rankingTable = useMemo(() => selectedAuthorIndexTable(authorIndexTable ?? ranking, visibleMetrics, selectedAuthorIds), [authorIndexTable, ranking, visibleMetrics.join(","), selectedAuthorIds.join("|")]);
  const sortableMetricIds = useMemo(() => new Set(displayMetricOptions.map((item) => item.value)), [displayMetricOptions]);
  const rankingColumnSchema = useMemo<TableColumnSchema[]>(() => {
    const metricSet = new Set(visibleMetrics);
    return (rankingTable?.fields ?? []).map((field) => ({
      field,
      label: metricLabels[field] ?? (field === "author_display_name" ? "Автор" : field === "country_code" ? "Страна" : field === "subject_name" ? "Направление" : metricLabel(field)),
      type: metricSet.has(field) ? "number" : "text",
      sortable: metricSet.has(field),
      filterable: false,
    }));
  }, [rankingTable?.fields?.join("|"), visibleMetrics.join("|"), JSON.stringify(metricLabels)]);
  const onRankingSortChange = (field: string, direction: "asc" | "desc" | "") => {
    if (!field || !sortableMetricIds.has(field)) {
      setRankingDirection("desc");
      return;
    }
    setMetric(field);
    setRankingDirection(direction || "desc");
  };
  const toggleMetric = (value: string) => {
    if (value === metric) return;
    if (selectedMetrics.includes(value)) {
      setSelectedMetrics(selectedMetrics.filter((item) => item !== value));
      return;
    }
    setSelectedMetrics([...selectedMetrics, value]);
  };
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">Расчет индексов</span>
            <h2>Индексы и рейтинги</h2>
            <p>Здесь показывается рейтинг авторов по всему выбранному срезу. Поиск и ограничения из вкладки “Данные” могут сузить выборку, но сортировка рейтинга задается основным индексом ниже.</p>
          </div>
          <button
            className="primary"
            onClick={onRecalculate}
            disabled={recalculating || !canRecalculate}
            title={canRecalculate ? undefined : "Сначала выберите локальный срез"}
          >
            {recalculating ? <Loader2 size={16} className="spin" /> : <Sigma size={16} />} Рассчитать
          </button>
        </div>
        <div className="form-grid tight">
          <Field label="Основной индекс рейтинга">
            <select value={metric} onChange={(event) => setMetric(event.target.value)}>
              {ensureCurrentOption(displayMetricOptions, metric).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
            <small className="field-hint">По этому индексу сортируется рейтинг и строится основной анализ.</small>
          </Field>
          <Field label="Учет вклада соавторов">
            <select value={fractionMode} onChange={(event) => setFractionMode(event.target.value)}>
              {ensureCurrentOption(fractionModeOptions, fractionMode).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
            <small className="field-hint">Настройка влияет на расчет авторских показателей.</small>
          </Field>
        </div>
        <div className="metric-grid">
          <MetricCard label="Показатель" value={metricLabelFor(metric, metricLabels)} />
          <MetricCard label="Учет вклада" value={modeLabel(fractionMode)} />
          <MetricCard label="Авторов в таблице" value={fmt(authorIndexTable?.total ?? ranking?.total ?? 0)} />
          <MetricCard label="Точек на графиках" value={selectedAuthorIds.length ? fmt(selectedAuthorIds.length) : "нет"} />
        </div>
        {usingActiveContextScope && effectiveDumpId && (
          <div className="notice">
            <b>Пересчет по активному контексту</b>
            <span>Если запустить расчет сейчас, будет использован активный локальный срез: {effectiveDumpId}.</span>
          </div>
        )}
        {!authorIndexTable && (
          <div className="notice warn action-notice">
            <div>
              <b>Авторские индексы еще не рассчитаны</b>
              <span>Выбранный срез можно смотреть во вкладке “Данные”, но таблица авторов, рейтинги и графики появятся только после локального расчета индексов.</span>
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
          </div>
        )}
        <div className="notice">
          <div>
            <b>Какие индексы показывать</b>
            <span>Нажимайте на показатель, чтобы включить или скрыть его в таблице и аналитике. Значок i рядом с названием показывает смысл показателя и формулу расчета.</span>
          </div>
        </div>
        <div className="metric-option-grid" role="group" aria-label="Показатели в таблице индексов">
          {displayMetricOptions.map((item) => {
            const active = visibleMetrics.includes(item.value);
            const pinned = item.value === metric;
            return (
              <div
                key={item.value}
                className={active ? "metric-option-card active" : "metric-option-card"}
              >
                <button
                  type="button"
                  className="metric-option-toggle"
                  aria-pressed={active}
                  disabled={pinned}
                  onClick={() => toggleMetric(item.value)}
                >
                  <span>
                    <b>{item.label}</b>
                    <small>{pinned ? "основной индекс" : active ? "показан" : "скрыт"}</small>
                  </span>
                </button>
                <MetricInfoPopover metric={item} />
              </div>
            );
          })}
        </div>
        <section className="formula-summary">
          <div>
            <b>Пользовательские формулы</b>
            <span>Можно добавить расчетный показатель по данным выбранного среза. По умолчанию аналитика и отчет остаются на baseline-наборе; расширенные формулы включаются явно.</span>
          </div>
          <div className="row-actions">
            <button
              type="button"
              className={includeCustomMetricsInAnalysis ? "choice-pill active" : "choice-pill"}
              onClick={() => setIncludeCustomMetricsInAnalysis(!includeCustomMetricsInAnalysis)}
              title="Включает сохраненные пользовательские формулы в аналитический пакет и отчет. Рейтинг по выбранной формуле доступен отдельно через основной индекс."
            >
              {includeCustomMetricsInAnalysis ? "Расширенный набор" : "Только baseline"}
            </button>
            <button type="button" className="primary" onClick={() => setFormulaBuilderOpen(true)}>
              <Sigma size={16} /> Открыть конструктор
            </button>
          </div>
        </section>
        {formulaBuilderOpen && (
          <FormulaBuilderDialog
            metrics={customMetrics}
            setMetrics={setCustomMetrics}
            onSaveMetric={onSaveCustomMetric}
            onDeleteMetric={onDeleteCustomMetric}
            persistenceReady={customMetricPersistenceReady}
            selectedMetrics={selectedMetrics}
            setSelectedMetrics={setSelectedMetrics}
            activeMetric={metric}
            setActiveMetric={setMetric}
            onClose={() => setFormulaBuilderOpen(false)}
          />
        )}
      </section>
      <section className="panel table-panel">
        <div className="panel-head">
          <span className="step-badge">Рейтинг авторов</span>
          <h2>Авторы и выбранные показатели</h2>
          <p>Таблица показывает авторов и только выбранные показатели рейтинга. Сортировка идет по основному индексу рейтинга; служебные признаки качества остаются в исходных таблицах.</p>
        </div>
        <DataGrid
          data={rankingTable}
          onSelect={onSelect}
          hiddenFields={["author_id"]}
          fieldLabels={metricLabels}
          columnSchema={rankingColumnSchema}
          sortField={metric}
          sortDirection={rankingDirection}
          onSortChange={onRankingSortChange}
        />
      </section>
    </div>
  );
}

export function selectedAuthorIndexTable(ranking: TableResponse | undefined, metrics: string[], selectedAuthorIds: string[] = []): TableResponse | undefined {
  const projected = projectAuthorIndexTable(ranking, metrics);
  if (!projected) return undefined;
  const selected = new Set(selectedAuthorIds.map(String));
  const rows = selected.size
    ? (projected.rows ?? []).filter((row) => selected.has(String(row.author_id ?? "")))
    : projected.rows;
  return { ...projected, rows, total: selected.size ? rows.length : projected.total };
}

function projectAuthorIndexTable(ranking: TableResponse | undefined, metrics: string[]): TableResponse | undefined {
  if (!ranking) return undefined;
  const fields = ranking.fields ?? [];
  const identityFields = ["author_display_name", "author_id"].filter((field) => fields.includes(field));
  const metricFields = metrics.filter((field) => fields.includes(field));
  const contextFields = ["country_code", "subject_name"].filter((field) => fields.includes(field));
  const selectedFields = [...new Set([...identityFields, ...metricFields, ...contextFields])];
  return { ...ranking, fields: selectedFields.length ? selectedFields : fields };
}



function ensureCurrentOption(options: SelectOption[], value: string) {
  if (!value || options.some((item) => item.value === value)) return options;
  return [{ value, label: value }, ...options];
}

function ensureCurrentOptions(options: SelectOption[], values: string[]) {
  const missing = values
    .filter((value) => value && !options.some((item) => item.value === value))
    .map((value) => ({ value, label: metricLabel(value) }));
  return [...missing, ...options];
}
