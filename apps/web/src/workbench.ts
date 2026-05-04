import { FRACTION_MODES, type ActiveFilters, type SelectOption, countryLabel, filterParams, fmt } from "./domain";

export type View = "slices" | "estimate" | "data" | "enrichment" | "rankings" | "statistics" | "reports" | "passports";
export type ResolverTab = "subject" | "organization" | "author" | "source";

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

export type PipelinePayload = {
  slice_name: string;
  workflow_mode: "strict_works" | "author_preview";
  entity_level: string;
  entity_id_short: string;
  entity_id_full: string;
  entity_display_name: string;
  filter_mode: string;
  keyword_id: string;
  keyword_display_name: string;
  text_search_query: string;
  raw_openalex_filter?: string;
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
  sort: string;
  max_works: number;
  max_dump_bytes?: number;
  fraction_modes: readonly string[];
  fraction_mode_default: string;
  lrdi_p0: number;
  lrdi_lambda: number;
  analysis_year: number;
  api_key?: string;
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

export type WorkbenchState = {
  tables?: Record<string, { rows?: number }>;
  workflow?: Record<string, unknown>;
  quality?: Record<string, unknown>;
};

export const VIEW_DEFINITIONS: Record<View, { label: string; lead: string }> = {
  slices: {
    label: "Срезы",
    lead: "Сначала задается логический предметный срез. Дамп и API-запросы являются производными артефактами.",
  },
  estimate: {
    label: "Оценка и загрузка",
    lead: "Оцените объем, выберите профиль материализации и только затем создавайте физический мини-дамп.",
  },
  data: {
    label: "Локальные данные",
    lead: "Контроль сохраненных JSONL/Parquet/витрин без смешения с логикой отбора.",
  },
  enrichment: {
    label: "Обогащение",
    lead: "Точечная дозагрузка авторов, организаций, ORCID/ROR и недостающих справочников.",
  },
  rankings: {
    label: "Индексы и рейтинги",
    lead: "Локальные индексы считаются только по работам выбранного среза.",
  },
  statistics: {
    label: "Сравнение и статистика",
    lead: "Корреляции, распределения и устойчивость рейтингов для математического вывода.",
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

export const MATERIALIZATION_PROFILES: SelectOption[] = [
  { value: "minimal_analytics", label: "Минимальный для рейтингов", description: "Работы, авторства, темы и цитирования. Профиль по умолчанию." },
  { value: "evidence_package", label: "Расширенный для отчета", description: "Добавляет OpenAlex IDs и даты обновления для паспорта." },
];

export const TOP_N_OPTIONS: SelectOption[] = [
  { value: "25", label: "Top-25 авторов" },
  { value: "50", label: "Top-50 авторов" },
  { value: "100", label: "Top-100 авторов" },
  { value: "250", label: "Top-250 авторов" },
  { value: "500", label: "Top-500 авторов" },
];

export function buildPayload(filters: ActiveFilters, fractionMode: string, maxWorks: number, maxDumpBytes: number, apiKey = ""): PipelinePayload {
  return {
    slice_name: sliceName(filters),
    workflow_mode: "strict_works",
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
    sort: "publication_date:asc,openalex:asc",
    max_works: maxWorks,
    max_dump_bytes: maxDumpBytes,
    fraction_modes: FRACTION_MODES,
    fraction_mode_default: fractionMode,
    lrdi_p0: 5,
    lrdi_lambda: 0.15,
    analysis_year: 2026,
    ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
  };
}

export function sliceName(filters: ActiveFilters) {
  return [
    filters.subject_level,
    filters.subject_id,
    filters.country_code || "all",
    filters.institution_id ? "org" : "all_orgs",
    filters.from_publication_date.slice(0, 4),
    filters.to_publication_date.slice(0, 4),
    filters.work_type || "all_types",
  ].join("_").replace(/[^A-Za-z0-9_.-]+/g, "_").slice(0, 120);
}

export function humanSliceTitle(filters: ActiveFilters) {
  return `${filters.subject_name || "направление не выбрано"} / ${filters.institution_name || (filters.country_code ? countryLabel(filters.country_code) : "все страны")} / ${filters.from_publication_date.slice(0, 4)}-${filters.to_publication_date.slice(0, 4)}`;
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

export function analyticsUrl(filters: ActiveFilters, fractionMode: string, metric: string) {
  return `/analytics?${filterParams(filters, { fraction_mode: fractionMode, metric, limit: 60 }).toString()}`;
}

function openAlexEntityUrl(level: string, id: string) {
  if (!level || !id) return "";
  return level === "topic" ? `https://openalex.org/${id}` : `https://openalex.org/${level}s/${id}`;
}

function clampProgress(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}
