import { DEFAULT_FILTERS, FRACTION_MODES, type ActiveFilters, countryLabel, filterParams } from "./domain";
import type { CustomMetricDefinition, TableColumnFilters } from "./api";

export type View = "slices" | "data" | "rankings" | "statistics" | "reports";
export type ResolverTab = "subject" | "organization" | "author" | "source";
export type LocalDataKind = "works" | "authorships" | "work_topics" | "author_work" | "indices" | "ratings";
export type ScientometricFindingSeverity = "high" | "medium" | "low" | "informational";
export type DataSelectionParams = {
  sort?: string;
  direction?: "asc" | "desc";
  limit?: number;
  filters?: TableColumnFilters;
  search?: string;
  authorIds?: string[];
};

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
  schema?: string;
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
  schema?: string;
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
  schema: string;
  scope: Record<string, unknown>;
  cohort_context?: Record<string, unknown> | null;
  metrics: string[];
  custom_metrics?: Array<{ value: string; label: string; description?: string; formula?: string }>;
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
  doi?: string;
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
  lrdi_p0: number;
  lrdi_lambda: number;
  analysis_year: number;
};

export type DownloadPolicy = {
  complete_slice_required: boolean;
  allow_incomplete_preview: boolean;
};

export type EstimatePayload = {
  decision?: {
    status?: string;
    strategy?: string;
    can_execute?: boolean;
    records_to_fetch?: number;
    estimated_raw_mb?: number;
    reasons?: string[];
    warnings?: string[];
    [key: string]: unknown;
  };
  estimate?: {
    estimate_count?: number;
    planned_records?: number;
    api_requests_planned?: number;
    estimated_cost_usd?: number;
    estimated_cli_metadata_bytes?: number;
    estimated_raw_bytes_p90?: number;
    estimated_raw_bytes?: number;
    estimated_selected_api_bytes?: number;
    estimated_cli_metadata_mb?: number;
    estimated_selected_api_mb?: number;
    estimated_raw_mb?: number;
    estimated_raw_mb_p90?: number;
    estimated_parquet_mb?: number;
    rate_limit?: { remaining?: number; limit?: number; [key: string]: unknown };
    facets?: Record<string, { rows?: Array<{ key?: string; label?: string; count?: number }> }>;
    [key: string]: unknown;
  };
  estimate_cache?: { status?: string; [key: string]: unknown };
  [key: string]: unknown;
};

export type MaterializationPlanPayload = {
  materialization_id?: string;
  profile?: { label?: string; description?: string; [key: string]: unknown };
  [key: string]: unknown;
};

export type WorkbenchSlice = SliceDefinitionPayload & {
  slice_id?: string;
  state?: string;
  title?: string;
  current_estimate?: EstimatePayload | null;
  current_materialization_plan?: MaterializationPlanPayload | null;
  [key: string]: unknown;
};

export type WorkbenchDump = {
  dump_id?: string;
  slice_id?: string;
  title?: string;
  slice_title?: string;
  subject_name?: string;
  records_downloaded?: number;
  records_expected?: number;
  bytes_written?: number;
  raw_size_bytes?: number;
  updated_at_utc?: string;
  created_at_utc?: string;
  created_at?: string;
  health?: Record<string, unknown>;
  storage_summary?: Record<string, unknown>;
  storage?: Record<string, unknown>;
  signatures?: Record<string, unknown>;
  filters?: Record<string, unknown>;
  [key: string]: unknown;
};

export type RateLimitPayload = {
  daily_remaining_usd?: number;
  daily_budget_usd?: number;
  [key: string]: unknown;
};

export type RegistryPayload = {
  domain_presets?: Array<Record<string, unknown>>;
  organization_presets?: Array<Record<string, unknown>>;
  [key: string]: unknown;
};

export type CatalogPayload = {
  metrics?: Array<Record<string, unknown>>;
  fraction_modes?: Array<Record<string, unknown>>;
  storage_profiles?: Array<Record<string, unknown>>;
  ui_options?: Record<string, unknown>;
  data_sources?: Array<Record<string, unknown>>;
  openalex_cli?: { api_key_configured?: boolean; [key: string]: unknown };
  [key: string]: unknown;
};

export type WorkbenchRun = {
  run_id?: string;
  action?: string;
  status?: "queued" | "running" | "cancelling" | "cancelled" | "completed" | "failed" | string;
  progress_percent?: number | null;
  progress_stage?: string;
  progress?: Record<string, unknown> | null;
  progress_phases?: Array<{ id?: string; label?: string; state?: string; percent?: number | null; determinate?: boolean }>;
  error?: string | null;
  payload?: Record<string, unknown> | null;
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
  slices?: WorkbenchSlice[];
  materializations?: MaterializationPlanPayload[];
  dumps?: WorkbenchDump[];
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

export type LocalDataMissingScopeState = {
  missing: boolean;
  detail: string;
};

export function localDataMissingScopeState(params: {
  runId?: string;
  dumpId?: string;
  activeContext?: WorkbenchActiveContext | null;
}): LocalDataMissingScopeState {
  const runId = String(params.runId ?? "").trim();
  const dumpId = String(params.dumpId ?? "").trim();
  if (runId || dumpId) {
    return { missing: false, detail: "" };
  }
  const hasActiveContext = Boolean(params.activeContext);
  const activeHasScope = Boolean(
    String(params.activeContext?.active_run_id ?? "").trim() ||
      String(params.activeContext?.active_dump_id ?? "").trim(),
  );
  if (hasActiveContext && !activeHasScope) {
    return {
      missing: true,
      detail: "Выбранный контекст существует, но не содержит расчета или локального среза. Скачайте срез заново либо выберите уже скачанный срез.",
    };
  }
  return {
    missing: true,
    detail: "Для просмотра локальных данных нужен активный расчет или уже скачанный локальный срез. Материализуйте срез либо выберите существующий локальный срез.",
  };
}

export type LocalDataSummary = {
  kinds?: Array<{ kind: LocalDataKind; label: string }>;
  tables?: Record<LocalDataKind, Record<string, unknown>>;
  run_id?: string;
  dump_id?: string;
  scope_status?: string;
  reproducible?: boolean;
  warnings?: string[];
};

export const LOCAL_DATA_KIND_OPTIONS: Array<{ value: LocalDataKind; label: string }> = [
  { value: "indices", label: "Авторы и индексы" },
  { value: "ratings", label: "Рейтинговые позиции" },
  { value: "works", label: "Работы" },
  { value: "authorships", label: "Авторства" },
  { value: "work_topics", label: "Темы работ" },
  { value: "author_work", label: "Автор-работа" },
];

export const VIEW_DEFINITIONS: Record<View, { label: string; lead: string }> = {
  slices: {
    label: "Срез",
    lead: "В одном месте задается срез, выбирается уже скачанная версия, выполняется оценка объема и запускается скачивание.",
  },
  data: {
    label: "Данные",
    lead: "Единая таблица выбранного среза: выбор таблицы, фильтр, min/max, сортировка по столбцам и TOP-N.",
  },
  rankings: {
    label: "Индексы и рейтинги",
    lead: "Индексы показываются по выборке, настроенной во вкладке “Данные”.",
  },
  statistics: {
    label: "Аналитика",
    lead: "Распределения, корреляции и выводы считаются по выборке, настроенной во вкладке “Данные”.",
  },
  reports: {
    label: "Отчеты",
    lead: "Пакет отчета, локальные выгрузки и паспорта воспроизводимости.",
  },
};

export function buildSliceDefinitionPayload(filters: ActiveFilters): SliceDefinitionPayload {
  const subjectId = shortOpenAlexId(filters.subject_id);
  return {
    entity_level: filters.subject_level,
    entity_id_short: subjectId,
    entity_id_full: openAlexEntityUrl(filters.subject_level, subjectId || filters.subject_id),
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

export function filtersFromSlicePayload(payload: Record<string, unknown> | null | undefined, fallback: ActiveFilters = DEFAULT_FILTERS): ActiveFilters {
  const raw = payload && typeof payload === "object" && "technical_payload" in payload && typeof payload.technical_payload === "object"
    ? payload.technical_payload as Record<string, unknown>
    : payload ?? {};
  return {
    ...fallback,
    subject_level: stringField(raw.entity_level, fallback.subject_level),
    subject_id: stringField(raw.entity_id_short, stringField(raw.entity_id_full, fallback.subject_id)),
    subject_name: stringField(raw.entity_display_name, fallback.subject_name),
    filter_mode: stringField(raw.filter_mode, fallback.filter_mode || "all"),
    keyword_id: stringField(raw.keyword_id, fallback.keyword_id),
    keyword_name: stringField(raw.keyword_display_name, fallback.keyword_name),
    text_search_query: stringField(raw.text_search_query, fallback.text_search_query),
    author_id: stringField(raw.author_id, fallback.author_id),
    author_name: stringField(raw.author_display_name, fallback.author_name),
    author_orcid: stringField(raw.author_orcid, fallback.author_orcid),
    institution_id: stringField(raw.institution_id, fallback.institution_id),
    institution_name: stringField(raw.institution_display_name, fallback.institution_name),
    institution_ror: stringField(raw.institution_ror, fallback.institution_ror),
    source_id: stringField(raw.source_id, fallback.source_id),
    source_name: stringField(raw.source_display_name, fallback.source_name),
    source_type: stringField(raw.source_type, fallback.source_type),
    language: stringField(raw.language, fallback.language),
    open_access_is_oa: stringField(raw.open_access_is_oa, fallback.open_access_is_oa),
    has_abstract: stringField(raw.has_abstract, fallback.has_abstract),
    min_cited_by_count: numericStringField(raw.min_cited_by_count, fallback.min_cited_by_count),
    doi: stringField(raw.doi, fallback.doi),
    affiliation_mode: stringField(raw.affiliation_mode, fallback.affiliation_mode),
    country_code: stringField(raw.country_code, fallback.country_code).toUpperCase(),
    from_publication_date: stringField(raw.from_publication_date, fallback.from_publication_date),
    to_publication_date: stringField(raw.to_publication_date, fallback.to_publication_date),
    work_type: stringField(raw.work_type, fallback.work_type),
  };
}

export function buildAnalysisRunPayload(fractionMode: string, fractionModes: readonly string[] = FRACTION_MODES): AnalysisRunPayload {
  return {
    fraction_modes: fractionModes,
    fraction_mode_default: fractionMode,
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
  if (error instanceof Error && error.message.trim()) return error.message;
  if (typeof error === "string") return error;
  return "Действие не выполнено. Проверьте параметры и повторите попытку.";
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
  if (!run) return { percent: null as number | null, label: "Ожидание запуска" };
  if (typeof run.progress_percent === "number") {
    return { percent: clampProgress(run.progress_percent), label: humanRunStage(run.progress_stage, run.status, run.action) };
  }
  if (run.status === "queued") return { percent: null as number | null, label: "В очереди" };
  if (run.status === "running") return { percent: null as number | null, label: humanRunStage(run.progress_stage, run.status, run.action) };
  if (run.status === "cancelling") return { percent: null as number | null, label: "Остановка" };
  if (run.status === "completed") return { percent: 100, label: "Готово" };
  if (run.status === "cancelled") return { percent: null as number | null, label: "Остановлено" };
  if (run.status === "failed") return { percent: null as number | null, label: "Ошибка" };
  return { percent: null as number | null, label: run.status || "Ожидание" };
}

function humanRunStage(stage: unknown, status?: string, action?: string) {
  const raw = String(stage || "").trim();
  if (status === "completed") return "Готово";
  if (status === "cancelled") return "Остановлено";
  if (status === "cancelling") return action === "repair_dump" ? "Остановка восстановления" : "Остановка загрузки";
  if (status === "failed") return "Ошибка";
  if (
    raw.includes("OpenAlex") ||
    raw.includes("Упаковано") ||
    raw.includes("Упаковка") ||
    raw.includes("Нормализация") ||
    raw.includes("Подготовка таблиц") ||
    raw.includes("Восстановление")
  ) {
    return raw.replaceAll("OpenAlex CLI", "загрузчик OpenAlex").replaceAll("CLI", "OpenAlex");
  }
  const known: Record<string, string> = {
    queued: "В очереди",
    starting: "Запуск",
    preparing: "Подготовка",
    running: "Выполнение",
    "fetching mini-dump": "Загрузка локального среза",
    "fetching and building local mart": "Загрузка и построение локального среза",
    "computing indices": "Расчет индексов",
    "normalizing local file": "Нормализация локального среза",
    "packing CLI JSON files": "Упаковка файлов OpenAlex",
    "Восстановление локального среза": "Восстановление локального среза",
  };
  if (known[raw]) return known[raw];
  if (status === "running" && (action === "build_from_openalex" || action === "fetch_slice_dump")) return "Загрузка среза";
  if (status === "running" && action === "repair_dump") return "Восстановление среза";
  if (status === "running" && action === "recalculate") return "Расчет индексов";
  return raw || status || "Выполнение";
}

export function analyticsRankingUrl(filters: ActiveFilters, fractionMode: string, metric: string, runId = "", dumpId = "", limit = 100, dataQuery = "", dataSelection?: DataSelectionParams, customMetrics?: CustomMetricDefinition[], rankDirection: "asc" | "desc" = "desc") {
  return `/analytics/ranking?${filterParams(filters, { fraction_mode: fractionMode, metric, limit, rank_direction: rankDirection, run_id: runId, dump_id: dumpId, q: dataQuery, ...dataSelectionQuery(dataSelection), custom_metric_defs: customMetricDefsQuery(customMetrics) }).toString()}`;
}

export function localDataSummaryUrl(runId = "", dumpId = "") {
  const params = new URLSearchParams();
  if (runId) params.set("run_id", runId);
  if (dumpId) params.set("dump_id", dumpId);
  const query = params.toString();
  return `/local-data/summary${query ? `?${query}` : ""}`;
}

export function localDataSchemaUrl(kind: LocalDataKind, runId = "", dumpId = "") {
  const params = new URLSearchParams({ kind });
  if (runId) params.set("run_id", runId);
  if (dumpId) params.set("dump_id", dumpId);
  return `/local-data/schema?${params.toString()}`;
}

export function localDataPreviewUrl(kind: LocalDataKind, params: { q?: string; runId?: string; dumpId?: string; limit?: number; offset?: number; sort?: string; direction?: string; fractionMode?: string; dataFilters?: TableColumnFilters } = {}) {
  const query = new URLSearchParams({ kind });
  if (params.q?.trim()) query.set("q", params.q.trim());
  if (params.runId) query.set("run_id", params.runId);
  if (params.dumpId) query.set("dump_id", params.dumpId);
  if (params.limit !== undefined) query.set("limit", String(Math.max(0, Number(params.limit) || 0)));
  if (params.offset !== undefined) query.set("offset", String(Math.max(0, Number(params.offset) || 0)));
  if (params.sort) {
    query.set("sort", params.sort);
    if (params.direction) query.set("direction", params.direction);
  }
  if (params.fractionMode) query.set("fraction_mode", params.fractionMode);
  const encodedFilters = encodeColumnFilters(params.dataFilters);
  if (encodedFilters) query.set("data_filters", encodedFilters);
  return `/local-data/preview?${query.toString()}`;
}

export function localDataPreviewCsvUrl(kind: LocalDataKind, params: { q?: string; runId?: string; dumpId?: string; limit?: number; offset?: number; sort?: string; direction?: string; fractionMode?: string; dataFilters?: TableColumnFilters } = {}) {
  const query = new URLSearchParams({ kind });
  if (params.q?.trim()) query.set("q", params.q.trim());
  if (params.runId) query.set("run_id", params.runId);
  if (params.dumpId) query.set("dump_id", params.dumpId);
  if (params.limit !== undefined) query.set("limit", String(Math.max(0, Number(params.limit) || 0)));
  if (params.offset !== undefined) query.set("offset", String(Math.max(0, Number(params.offset) || 0)));
  if (params.sort) {
    query.set("sort", params.sort);
    if (params.direction) query.set("direction", params.direction);
  }
  if (params.fractionMode) query.set("fraction_mode", params.fractionMode);
  const encodedFilters = encodeColumnFilters(params.dataFilters);
  if (encodedFilters) query.set("data_filters", encodedFilters);
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
  dataQuery?: string;
  dataSelection?: DataSelectionParams;
  customMetrics?: CustomMetricDefinition[];
}) {
  const query = filterParams(params.filters, {
    fraction_mode: params.fractionMode,
    metrics: params.metrics.join(","),
    baseline_metric: params.baselineMetric,
    top_n: params.rankTopN,
    run_id: params.runId ?? "",
    dump_id: params.dumpId ?? "",
    q: params.dataQuery ?? "",
    ...dataSelectionQuery(params.dataSelection),
    custom_metric_defs: customMetricDefsQuery(params.customMetrics),
  });
  return `/analytics/scientometrics?${query.toString()}`;
}

export function customMetricDefsQuery(customMetrics?: CustomMetricDefinition[]) {
  const clean = (customMetrics ?? [])
    .map((item) => ({
      id: String(item.id ?? "").trim(),
      label: String(item.label ?? "").trim(),
      description: String(item.description ?? "").trim(),
      expression: String(item.expression ?? "").trim(),
    }))
    .filter((item) => item.id && item.label && item.expression);
  return clean.length ? JSON.stringify(clean) : "";
}

export function customMetricModelsUrl(runId = "") {
  const query = new URLSearchParams();
  if (runId) query.set("run_id", runId);
  const suffix = query.toString();
  return `/analytics/custom-metrics${suffix ? `?${suffix}` : ""}`;
}

export function dataSelectionQuery(selection?: DataSelectionParams) {
  const encodedFilters = encodeColumnFilters(selection?.filters);
  const sort = String(selection?.sort ?? "").trim();
  const limit = Number(selection?.limit ?? 0);
  const search = String(selection?.search ?? "").trim();
  const authorIds = (selection?.authorIds ?? []).map((item) => String(item).trim()).filter(Boolean);
  return {
    data_filters: encodedFilters,
    data_search: search,
    data_sort: sort,
    data_direction: sort ? selection?.direction ?? "desc" : "",
    data_limit: Number.isFinite(limit) ? String(Math.max(0, limit)) : "0",
    author_ids: authorIds.join(","),
  };
}

export function encodeColumnFilters(filters?: TableColumnFilters) {
  const clean: TableColumnFilters = {};
  for (const [field, filter] of Object.entries(filters ?? {})) {
    const contains = String(filter.contains ?? "").trim();
    const min = String(filter.min ?? "").trim();
    const max = String(filter.max ?? "").trim();
    if (!contains && !min && !max) continue;
    clean[field] = {};
    if (contains) clean[field].contains = contains;
    if (min) clean[field].min = min;
    if (max) clean[field].max = max;
  }
  return Object.keys(clean).length ? JSON.stringify(clean) : "";
}

function openAlexEntityUrl(level: string, id: string) {
  if (!level || !id) return "";
  if (/^https?:\/\//i.test(id)) return id;
  return level === "topic" ? `https://openalex.org/${id}` : `https://openalex.org/${level}s/${id}`;
}

function stringField(value: unknown, fallback = "") {
  const clean = String(value ?? "").trim();
  return clean || fallback;
}

function numericStringField(value: unknown, fallback = "") {
  if (value === null || value === undefined || value === "") return fallback;
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric !== 0 ? String(numeric) : fallback;
}

function shortOpenAlexId(value: string) {
  return value.trim().replace(/\/+$/, "").split("/").pop() ?? "";
}

function clampProgress(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}
