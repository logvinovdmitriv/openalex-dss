import { FRACTION_MODES, type ActiveFilters, countryLabel, filterParams, fmt } from "./domain";

export type View = "slices" | "data" | "enrichment" | "rankings" | "cohorts" | "statistics" | "reports" | "passports";
export type ResolverTab = "subject" | "organization" | "author" | "source";
export type CohortFilterPolicy = "membership" | "current" | "none";
export type LocalDataKind = "works" | "authorships" | "work_topics" | "author_work" | "indices" | "ratings";
export type ScientometricFindingSeverity = "high" | "medium" | "low" | "informational";

export type ScientometricFinding = {
  id: string;
  type: string;
  metric?: string | null;
  baseline_metric?: string | null;
  severity: ScientometricFindingSeverity;
  evidence: Record<string, unknown>;
  text: string;
  recommendation?: string;
};

export type ScientometricFindingSummary = {
  findings_version?: string;
  n_findings?: number;
  high_count?: number;
  medium_count?: number;
  candidate_metric?: string | null;
  candidate_metric_claim?: string | null;
  primary_limitations?: Array<Record<string, unknown>>;
  recommended_discussion_points?: string[];
  notes?: string[];
};

export type ScientometricConclusionDraft = {
  version?: string;
  title?: string;
  paragraphs?: Array<{
    role?: string;
    text?: string;
    evidence_finding_ids?: string[];
    evidence_metrics?: string[];
  }>;
  limitations?: string[];
  source?: Record<string, unknown>;
};

export type ScientometricAnalysisPayload = {
  analysis_version: string;
  scope: Record<string, unknown>;
  cohort_context?: Record<string, unknown> | null;
  metrics: string[];
  n_authors: number;
  rank_top_n?: number;
  warnings: string[];
  descriptive: Record<string, Record<string, number | null>>;
  boxplots: Record<string, Record<string, unknown>>;
  histograms: Record<string, Record<string, Array<Record<string, number>>>>;
  normality: Record<string, Record<string, Record<string, unknown>>>;
  correlations: {
    pearson_log1p?: Record<string, Record<string, number | null>>;
    spearman?: Record<string, Record<string, number | null>>;
    kendall_tau_b?: {
      matrix: Record<string, Record<string, number | null>>;
      skipped?: Array<Record<string, unknown>>;
      method?: string;
      max_exact_n?: number;
    };
  };
  rank_comparisons: Record<string, Record<string, unknown>>;
  top_overlap: {
    mode?: string;
    cuts?: number[];
    matrix?: Record<string, Record<string, Record<string, Record<string, number | null>>>>;
  };
  outliers: Record<string, Array<Record<string, unknown>>>;
  metric_scorecard: Record<string, Record<string, unknown>>;
  interpretation: Record<string, unknown>;
  findings?: ScientometricFinding[];
  finding_summary?: ScientometricFindingSummary;
  finding_thresholds?: Record<string, number>;
  conclusion_draft?: ScientometricConclusionDraft;
};

export type EntitySuggestion = {
  id: string;
  name: string;
  level?: string;
  level_label?: string;
  openalex_id?: string;
  description?: string;
  country_code?: string;
  ror?: string;
  orcid?: string;
  works_count?: number;
  cited_by_count?: number;
};

export type SliceDefinitionPayload = {
  entity_level: string;
  entity_id_short: string;
  entity_id_full: string;
  entity_display_name: string;
  filter_mode: string;
  keyword_id: string;
  keyword_display_name: string;
  text_search_query: string;
  author_id: string;
  author_display_name: string;
  author_orcid: string;
  institution_id: string;
  institution_display_name: string;
  institution_ror: string;
  source_id: string;
  source_display_name: string;
  source_type: string;
  language: string;
  open_access_is_oa: string;
  has_abstract: string;
  min_cited_by_count: number;
  doi: string;
  affiliation_mode: string;
  country_code: string;
  from_publication_date: string;
  to_publication_date: string;
  work_type: string;
  include_xpac: boolean;
  exclude_retracted: boolean;
  exclude_paratext: boolean;
};

export type AnalysisRunPayload = {
  fraction_modes: readonly string[];
  fraction_mode_default: string;
  iupv_n0: number;
  iupv_lambda: number;
  lrdi_p0: number;
  lrdi_lambda: number;
  analysis_year: number;
};

export type DownloadPolicy = {
  complete_slice_required: boolean;
  allow_incomplete_preview: boolean;
};

export type WorkbenchRun = {
  run_id?: string;
  action?: string;
  status?: "queued" | "running" | "completed" | "failed" | string;
  progress_percent?: number;
  progress_stage?: string;
  error?: string | null;
  result?: Record<string, unknown> | null;
};

export type WorkbenchActiveContext = {
  active_run_id?: string;
  active_dump_id?: string;
  source?: string;
  updated_at_utc?: string;
  analysis_eligibility_status?: string | null;
  allowed_for_final_analysis?: boolean | null;
  run_dir?: string;
  dump_dir?: string;
  tables_dir?: string;
};

export type WorkbenchWorkflow = {
  active_stage?: string;
  active_run_id?: string | null;
  active_dump_id?: string | null;
  active_context_source?: string | null;
  active_context_updated_at_utc?: string | null;
  current_slice?: Record<string, unknown>;
  quality_summary?: Record<string, unknown>;
};

export type WorkbenchState = {
  tables?: Record<string, { rows?: number }>;
  dumps?: Array<Record<string, unknown>>;
  workflow?: WorkbenchWorkflow;
  quality?: Record<string, unknown>;
  active_context?: WorkbenchActiveContext;
};

export type EffectiveUiScope = {
  runId: string;
  dumpId: string;
  source: "explicit" | "active_context" | "none";
};

export function effectiveUiScope(params: {
  runId?: string;
  dumpId?: string;
  activeContext?: WorkbenchActiveContext | null;
}): EffectiveUiScope {
  const explicitRunId = String(params.runId ?? "").trim();
  const explicitDumpId = String(params.dumpId ?? "").trim();
  const activeRunId = String(params.activeContext?.active_run_id ?? "").trim();
  const activeDumpId = String(params.activeContext?.active_dump_id ?? "").trim();
  if (explicitRunId || explicitDumpId) {
    return { runId: explicitRunId, dumpId: explicitDumpId, source: "explicit" };
  }
  if (activeRunId || activeDumpId) {
    return { runId: activeRunId, dumpId: activeDumpId, source: "active_context" };
  }
  return { runId: "", dumpId: "", source: "none" };
}

export type LocalDataScopePayload = {
  scope_status?: string;
  scope_warnings?: string[];
  warnings?: string[];
};

export function localDataNoScopeWarnings(...payloads: Array<LocalDataScopePayload | null | undefined>): string[] {
  const warnings: string[] = [];
  for (const payload of payloads) {
    if (payload?.scope_status !== "implicit_latest_preview") continue;
    const candidates = [...(payload.warnings ?? []), ...(payload.scope_warnings ?? [])];
    for (const warning of candidates) {
      if (warning && !warnings.includes(warning)) warnings.push(warning);
    }
  }
  return warnings;
}

export type LocalDataSummary = {
  kinds?: Array<{ kind: LocalDataKind; label: string }>;
  tables?: Record<LocalDataKind, Record<string, unknown>>;
  run_id?: string;
  dump_id?: string;
  scope_status?: string;
  reproducible?: boolean;
  scope_warnings?: string[];
  warnings?: string[];
};

export const LOCAL_DATA_KIND_OPTIONS: Array<{ value: LocalDataKind; label: string }> = [
  { value: "works", label: "Работы" },
  { value: "authorships", label: "Авторства" },
  { value: "work_topics", label: "Темы работ" },
  { value: "author_work", label: "Автор-работа" },
  { value: "indices", label: "Индексы авторов" },
  { value: "ratings", label: "Позиции рейтингов" },
];

export const VIEW_DEFINITIONS: Record<View, { label: string; lead: string }> = {
  slices: {
    label: "Срез и загрузка",
    lead: "В одном месте задается срез, выполняется оценка объема и настраивается скачивание локального пакета.",
  },
  data: {
    label: "Локальные данные",
    lead: "Контроль сохраненных JSONL/Parquet/витрин без смешения с логикой отбора.",
  },
  enrichment: {
    label: "Точечное обогащение",
    lead: "Дозагрузка отдельных авторов, организаций, ORCID/ROR и работ без смешения с локальными индексами среза.",
  },
  rankings: {
    label: "Индексы и рейтинги",
    lead: "Локальные индексы считаются только по работам выбранного среза.",
  },
  cohorts: {
    label: "Когорты авторов",
    lead: "Фиксируйте Top-N или ручную выборку авторов перед статистикой и отчетом.",
  },
  statistics: {
    label: "Сравнение и статистика",
    lead: "Корреляции, распределения и устойчивость рейтингов считаются для выбранной авторской когорты.",
  },
  reports: {
    label: "Отчеты",
    lead: "Экспорт таблиц, графиков и воспроизводимого пакета.",
  },
  passports: {
    label: "Паспорта",
    lead: "Паспорта среза, дампа, расчета и качества данных.",
  },
};

export function buildSliceDefinitionPayload(filters: ActiveFilters): SliceDefinitionPayload {
  return {
    entity_level: filters.subject_level,
    entity_id_short: filters.subject_id,
    entity_id_full: openAlexEntityUrl(filters.subject_level, filters.subject_id),
    entity_display_name: filters.subject_name,
    filter_mode: filters.filter_mode,
    keyword_id: filters.keyword_id,
    keyword_display_name: filters.keyword_name,
    text_search_query: filters.text_search_query,
    author_id: filters.author_id,
    author_display_name: filters.author_name,
    author_orcid: filters.author_orcid,
    institution_id: filters.institution_id,
    institution_display_name: filters.institution_name,
    institution_ror: filters.institution_ror,
    source_id: filters.source_id,
    source_display_name: filters.source_name,
    source_type: filters.source_type,
    language: filters.language,
    open_access_is_oa: filters.open_access_is_oa,
    has_abstract: filters.has_abstract,
    min_cited_by_count: Number(filters.min_cited_by_count || 0),
    doi: filters.doi,
    affiliation_mode: filters.affiliation_mode,
    country_code: filters.country_code.trim().toUpperCase(),
    from_publication_date: filters.from_publication_date,
    to_publication_date: filters.to_publication_date,
    work_type: filters.work_type,
    include_xpac: false,
    exclude_retracted: true,
    exclude_paratext: true,
  };
}

export function buildAnalysisRunPayload(fractionMode: string, fractionModes: readonly string[] = FRACTION_MODES): AnalysisRunPayload {
  return {
    fraction_modes: fractionModes,
    fraction_mode_default: fractionMode,
    iupv_n0: 5,
    iupv_lambda: 0.15,
    lrdi_p0: 5,
    lrdi_lambda: 0.15,
    analysis_year: 2026,
  };
}

export function buildDownloadPolicy(): DownloadPolicy {
  return {
    complete_slice_required: true,
    allow_incomplete_preview: false,
  };
}

export function humanSliceTitle(filters: ActiveFilters) {
  return `${sliceSubjectTitle(filters)} / ${filters.institution_name || (filters.country_code ? countryLabel(filters.country_code) : "все страны")} / ${filters.from_publication_date.slice(0, 4)}-${filters.to_publication_date.slice(0, 4)}`;
}

export function sliceSubjectTitle(filters: ActiveFilters) {
  if (filters.filter_mode === "keyword") return filters.keyword_name || filters.keyword_id || "ключевое слово";
  if (filters.filter_mode === "search") return filters.text_search_query || "поисковый запрос";
  return filters.subject_name || "все направления";
}

export function rankingChartRows(rows: Record<string, unknown>[], metric: string) {
  return rows.slice(0, 20).map((row, index) => ({
    label: String(index + 1),
    author: String(row.author_display_name ?? row.author_id ?? ""),
    score: Number(row.score ?? row[metric] ?? row[`${metric}_raw`] ?? 0),
  }));
}

export function bytesToMb(value: number) {
  return Math.round((Number(value || 0) / (1024 * 1024)) * 10) / 10;
}

export function mutationError(error: unknown) {
  return error instanceof Error ? error.message : "";
}

export function viewFromHash(hash: string): View {
  const raw = hash.replace(/^#/, "");
  if (raw === "estimate") return "slices";
  return Object.keys(VIEW_DEFINITIONS).includes(raw) ? (raw as View) : "slices";
}

export function pageTitle(view: View) {
  return VIEW_DEFINITIONS[view].label;
}

export function pageLead(view: View) {
  return VIEW_DEFINITIONS[view].lead;
}

export function progressForRun(run?: WorkbenchRun | null) {
  if (!run) return { percent: 0, label: "Ожидание запуска" };
  if (typeof run.progress_percent === "number") {
    return { percent: clampProgress(run.progress_percent), label: run.progress_stage || run.status || "Выполнение" };
  }
  if (run.status === "queued") return { percent: 8, label: "В очереди" };
  if (run.status === "running") return { percent: 55, label: "Выполнение" };
  if (run.status === "completed") return { percent: 100, label: "Готово" };
  if (run.status === "failed") return { percent: 100, label: "Ошибка" };
  return { percent: 0, label: run.status || "Ожидание" };
}

export function analyticsUrl(filters: ActiveFilters, fractionMode: string, metric: string, runId = "", dumpId = "", cohortId = "", cohortFilterPolicy: CohortFilterPolicy = "membership") {
  return `/analytics?${filterParams(filters, { fraction_mode: fractionMode, metric, limit: 60, run_id: runId, dump_id: dumpId, cohort_id: cohortId, cohort_filter_policy: cohortFilterPolicy }).toString()}`;
}

export function analyticsRankingUrl(filters: ActiveFilters, fractionMode: string, metric: string, runId = "", dumpId = "", limit = 100, cohortId = "", cohortFilterPolicy: CohortFilterPolicy = "membership") {
  return `/analytics/ranking?${filterParams(filters, { fraction_mode: fractionMode, metric, limit, run_id: runId, dump_id: dumpId, cohort_id: cohortId, cohort_filter_policy: cohortFilterPolicy }).toString()}`;
}

export function localDataSummaryUrl(runId = "", dumpId = "") {
  const params = new URLSearchParams();
  if (runId) params.set("run_id", runId);
  if (dumpId) params.set("dump_id", dumpId);
  const query = params.toString();
  return `/local-data/summary${query ? `?${query}` : ""}`;
}

export function localDataPreviewUrl(kind: LocalDataKind, params: { q?: string; runId?: string; dumpId?: string; limit?: number } = {}) {
  const query = new URLSearchParams({ kind });
  if (params.q?.trim()) query.set("q", params.q.trim());
  if (params.runId) query.set("run_id", params.runId);
  if (params.dumpId) query.set("dump_id", params.dumpId);
  if (params.limit) query.set("limit", String(params.limit));
  return `/local-data/preview?${query.toString()}`;
}

export function localDataPreviewCsvUrl(kind: LocalDataKind, params: { q?: string; runId?: string; dumpId?: string; limit?: number } = {}) {
  const query = new URLSearchParams({ kind });
  if (params.q?.trim()) query.set("q", params.q.trim());
  if (params.runId) query.set("run_id", params.runId);
  if (params.dumpId) query.set("dump_id", params.dumpId);
  if (params.limit) query.set("limit", String(params.limit));
  return `/local-data/preview.csv?${query.toString()}`;
}

export function scientometricsUrl(params: {
  filters: ActiveFilters;
  fractionMode: string;
  metrics: string[];
  baselineMetric: string;
  rankTopN: number;
  runId?: string;
  dumpId?: string;
  cohortId?: string;
  cohortFilterPolicy?: CohortFilterPolicy;
}) {
  const query = filterParams(params.filters, {
    fraction_mode: params.fractionMode,
    metrics: params.metrics.join(","),
    baseline_metric: params.baselineMetric,
    top_n: params.rankTopN,
    run_id: params.runId ?? "",
    dump_id: params.dumpId ?? "",
    cohort_id: params.cohortId ?? "",
    cohort_filter_policy: params.cohortFilterPolicy ?? "membership",
  });
  return `/analytics/scientometrics?${query.toString()}`;
}

export function cohortAuthorMetricsUrl(cohortId: string, filters: ActiveFilters, fractionMode: string, metric: string, runId = "", dumpId = "", format: "csv" | "json" = "csv", cohortFilterPolicy: CohortFilterPolicy = "membership") {
  return `/cohorts/${encodeURIComponent(cohortId)}/author-metrics.${format}?${filterParams(filters, { fraction_mode: fractionMode, metric, run_id: runId, dump_id: dumpId, cohort_filter_policy: cohortFilterPolicy }).toString()}`;
}

export function cohortStatisticsUrl(cohortId: string, filters: ActiveFilters, fractionMode: string, runId = "", dumpId = "", cohortFilterPolicy: CohortFilterPolicy = "membership") {
  return `/cohorts/${encodeURIComponent(cohortId)}/statistics?${filterParams(filters, { fraction_mode: fractionMode, run_id: runId, dump_id: dumpId, cohort_filter_policy: cohortFilterPolicy }).toString()}`;
}

function openAlexEntityUrl(level: string, id: string) {
  if (!level || !id) return "";
  return level === "topic" ? `https://openalex.org/${id}` : `https://openalex.org/${level}s/${id}`;
}

function clampProgress(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}
