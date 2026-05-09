import { useState } from "react";
import { Download, Loader2 } from "lucide-react";
import type { CustomMetricDefinition, TableColumnFilters } from "../../api";
import { API_BASE } from "../../api";
import type { ActiveFilters } from "../../domain";
import { filterParams } from "../../domain";
import { DownloadLink, JsonPanel } from "../../components/ui";
import {
  customMetricDefsQuery,
  dataSelectionQuery,
  localDataPreviewCsvUrl,
} from "../../workbench";
import { metricLabelFor } from "../formulas/FormulaBuilder";

export function ReportsPage({
  filters,
  metric,
  fractionMode,
  runId,
  dumpId,
  scientometricMetrics,
  baselineMetric,
  rankTopN,
  dataFilters,
  dataSort,
  dataDirection,
  customMetrics,
  metricLabels,
  onBuild,
  building,
  state,
  sliceDoc,
  estimate,
  materialization,
}: {
  filters: ActiveFilters;
  metric: string;
  fractionMode: string;
  runId: string;
  dumpId: string;
  scientometricMetrics: string[];
  baselineMetric: string;
  rankTopN: number;
  dataFilters: TableColumnFilters;
  dataSort: string;
  dataDirection: "asc" | "desc";
  customMetrics: CustomMetricDefinition[];
  metricLabels: Record<string, string>;
  onBuild: () => void;
  building: boolean;
  state: any;
  sliceDoc: any;
  estimate: any;
  materialization: any;
}) {
  const [section, setSection] = useState<"exports" | "passports">("exports");
  const selectionQuery = dataSelectionQuery({ filters: dataFilters, sort: dataSort, direction: dataDirection, limit: 0 });
  const activeRestrictionCount = Object.keys(dataFilters).length;
  const reportParams = filterParams(filters, {
    fraction_mode: fractionMode,
    metric,
    limit: 0,
    run_id: runId,
    dump_id: dumpId,
    scientometric_metrics: scientometricMetrics.join(","),
    baseline_metric: baselineMetric,
    rank_top_n: rankTopN,
    custom_metric_defs: customMetricDefsQuery(customMetrics),
    ...selectionQuery,
  });
  const rankingUrl = `${API_BASE}/analytics/ranking.csv?${reportParams.toString()}`;
  const bundleUrl = `${API_BASE}/reports/bundle.json?${reportParams.toString()}`;
  const hasReportDataScope = Boolean(runId || dumpId);
  const localIndicesUrl = `${API_BASE}${localDataPreviewCsvUrl("indices", { runId, dumpId, limit: 100_000, sort: dataSort, direction: dataDirection, fractionMode, dataFilters })}`;
  const localWorksUrl = `${API_BASE}${localDataPreviewCsvUrl("works", { runId, dumpId, limit: 100_000, sort: dataSort, direction: dataDirection, dataFilters })}`;
  const localAuthorshipsUrl = `${API_BASE}${localDataPreviewCsvUrl("authorships", { runId, dumpId, limit: 100_000, sort: dataSort, direction: dataDirection, dataFilters })}`;
  const localWorkTopicsUrl = `${API_BASE}${localDataPreviewCsvUrl("work_topics", { runId, dumpId, limit: 100_000, sort: dataSort, direction: dataDirection, dataFilters })}`;
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">Отчет</span>
            <h2>Отчеты и пакет воспроизводимости</h2>
            <p>Отчет фиксирует срез исследования, локальную загрузку, текущую выборку из “Данных”, расчет индексов, ограничения и паспорта.</p>
          </div>
          <button onClick={onBuild} disabled={building}>{building ? <Loader2 size={16} className="spin" /> : <Download size={16} />} Собрать HTML</button>
        </div>
        <div className="choice-grid compact section-tabs" role="tablist" aria-label="Разделы отчетов">
          {[
            ["exports", "Пакет и таблицы"],
            ["passports", "Паспорта"],
          ].map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={section === id} className={section === id ? "choice-pill active" : "choice-pill"} onClick={() => setSection(id as "exports" | "passports")}>
              {label}
            </button>
          ))}
        </div>
        {section === "exports" && (
          <>
            <div className="download-grid">
              {hasReportDataScope && <DownloadLink href={rankingUrl} label="Рейтинг авторов" />}
              <DownloadLink href={bundleUrl} label="Пакет отчета" />
              {hasReportDataScope && (
                <>
                  <DownloadLink href={localIndicesUrl} label="Авторы и индексы" />
                  <DownloadLink href={localWorksUrl} label="Работы" />
                  <DownloadLink href={localAuthorshipsUrl} label="Авторство в работах" />
                  <DownloadLink href={localWorkTopicsUrl} label="Темы работ" />
                </>
              )}
              <DownloadLink href={`${API_BASE}/workbench`} label="Состояние системы" />
              <DownloadLink href={`${API_BASE}/catalog`} label="Каталог настроек" />
            </div>
            {!hasReportDataScope && (
              <div className="notice warn">
                <b>Выгрузка требует выбранный срез</b>
                <span>Выберите расчет или локальный срез: ссылки на локальные таблицы не показываются без выбранной области анализа.</span>
              </div>
            )}
          </>
        )}
        {section === "passports" && (
          <ReportPassportsSection state={state} sliceDoc={sliceDoc} estimate={estimate} materialization={materialization} />
        )}
        <div className="notice">
          <b>Параметры пакета</b>
          <span>Показатели: {scientometricMetrics.map((item) => metricLabelFor(item, metricLabels)).join(", ")}. Основной показатель: {metricLabelFor(baselineMetric, metricLabels)}. Авторы: все после поиска и ограничений из “Данных”. Ограничений по столбцам: {activeRestrictionCount}.</span>
        </div>
      </section>
    </div>
  );
}

function ReportPassportsSection({ state, sliceDoc, estimate, materialization }: { state: any; sliceDoc: any; estimate: any; materialization: any }) {
  return (
    <div className="passport-grid">
      <JsonPanel title="Паспорт среза" value={sliceDoc ?? state?.workflow?.current_slice ?? {}} />
      <JsonPanel title="Паспорт оценки" value={estimate ?? sliceDoc?.current_estimate ?? {}} />
      <JsonPanel title="Паспорт загрузки и хранения" value={materialization ?? sliceDoc?.current_materialization_plan ?? {}} />
      <JsonPanel title="Паспорт качества данных" value={state?.quality ?? {}} />
    </div>
  );
}
