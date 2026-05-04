export const METRICS = ["p", "c", "c_frac", "cpp", "h", "i10", "g", "m_local", "top1_share", "lrdi", "f5", "fm5", "iupv", "islv"] as const;
export const FRACTION_MODES = ["strict_authors_count", "renorm_valid_authors", "integer"] as const;
export const TABLES = ["authors_local_metrics", "authors_preview", "indices", "ratings", "works", "authorships", "author_work", "top1_sensitivity", "fraction_sensitivity"] as const;

export type Metric = (typeof METRICS)[number];
export type FractionMode = (typeof FRACTION_MODES)[number];
export type TableName = (typeof TABLES)[number];

export type ActiveFilters = {
  subject_level: string;
  subject_id: string;
  subject_name: string;
  filter_mode: string;
  keyword_id: string;
  keyword_name: string;
  text_search_query: string;
  author_id: string;
  author_name: string;
  author_orcid: string;
  institution_id: string;
  institution_name: string;
  institution_ror: string;
  source_id: string;
  source_name: string;
  source_type: string;
  language: string;
  open_access_is_oa: string;
  has_abstract: string;
  min_cited_by_count: string;
  doi: string;
  affiliation_mode: string;
  country_code: string;
  from_publication_date: string;
  to_publication_date: string;
  work_type: string;
};

export type SelectOption = {
  value: string;
  label: string;
  description?: string;
  example?: string;
};

export type ResearchAreaPreset = {
  value: string;
  label: string;
  description: string;
  subject_level: string;
  subject_id: string;
  subject_name: string;
  filter_mode: string;
  keyword_id?: string;
  keyword_name?: string;
  text_search_query?: string;
};

export type OrganizationPreset = {
  value: string;
  label: string;
  description: string;
  institution_id: string;
  institution_name: string;
  country_code?: string;
  ror?: string;
};

export type WorkflowStage = {
  id: string;
  label: string;
  description: string;
  status: "ready" | "pending" | string;
  ready: boolean;
};

export const DEFAULT_FILTERS: ActiveFilters = {
  subject_level: "",
  subject_id: "",
  subject_name: "",
  filter_mode: "primary_topic",
  keyword_id: "",
  keyword_name: "",
  text_search_query: "",
  author_id: "",
  author_name: "",
  author_orcid: "",
  institution_id: "",
  institution_name: "",
  institution_ror: "",
  source_id: "",
  source_name: "",
  source_type: "",
  language: "",
  open_access_is_oa: "",
  has_abstract: "",
  min_cited_by_count: "",
  doi: "",
  affiliation_mode: "historical",
  country_code: "",
  from_publication_date: "2020-01-01",
  to_publication_date: "2024-12-31",
  work_type: "article",
};

const metricLabels: Record<string, string> = {
  p: "Число работ",
  c: "Все цитирования",
  c_frac: "Фракционные цитирования",
  cpp: "Цитирований на работу",
  h: "Индекс Хирша",
  i10: "Индекс i10",
  g: "g-индекс",
  m_local: "m-индекс локальный",
  top1_share: "Доля top-1 работы",
  lrdi: "LRDI",
  f5: "f5 (операционный)",
  fm5: "fm5 (операционный)",
  iupv: "IUPV",
  islv: "ISLV",
  mean_authors_per_work: "Среднее число авторов",
  share_single_authored: "Доля одноавторских работ",
};

const metricDescriptions: Record<string, string> = {
  p: "Сортирует авторов по числу работ в выбранном срезе.",
  c: "Показывает суммарные цитирования без поправки на соавторство.",
  c_frac: "Учитывает цитирования пропорционально числу соавторов.",
  cpp: "Средняя цитируемость одной работы внутри среза: C / P.",
  h: "Классический индекс Хирша внутри выбранного среза.",
  i10: "Число работ автора с 10 и более цитированиями.",
  g: "g-индекс с большей чувствительностью к высокоцитируемым работам.",
  m_local: "Локальный m-index: h / длительность публикационного окна автора в срезе.",
  top1_share: "Показывает концентрацию цитирований в самой цитируемой работе автора.",
  lrdi: "Экспериментальный локальный робастный индекс с учетом соавторства и свежести публикаций.",
  f5: "Операционная версия: число работ с 5 и более цитированиями.",
  fm5: "Операционная версия: сумма авторских долей для работ с 5+ цитированиями.",
  iupv: "Индекс устойчивой предметной видимости: геометрическое среднее процентильных рангов P, h и C_frac.",
  islv: "Индекс сбалансированного локального вклада: h, C_frac, g, i10, P и штраф за top-1 концентрацию.",
  mean_authors_per_work: "Среднее число соавторов в работах автора.",
  share_single_authored: "Доля работ, где автор указан один.",
};

const modeLabels: Record<string, string> = {
  strict_authors_count: "Строгий фракционный счёт",
  renorm_valid_authors: "Перенормировка валидных авторов",
  integer: "Целочисленный счёт",
};

const modeDescriptions: Record<string, string> = {
  strict_authors_count: "Делит вклад на полное число авторов работы.",
  renorm_valid_authors: "Делит вклад только между валидно распознанными авторами.",
  integer: "Засчитывает работу каждому автору полностью.",
};

const tableLabels: Record<string, string> = {
  indices: "Индексы авторов",
  authors_local_metrics: "Локальные метрики авторов",
  authors_preview: "Быстрая витрина авторов",
  ratings: "Рейтинговые позиции",
  works: "Работы OpenAlex",
  authorships: "Авторства",
  author_work: "Плоская связь автор-работа",
  top1_sensitivity: "Чувствительность top-1",
  fraction_sensitivity: "Чувствительность фракционирования",
};

const tableDescriptions: Record<string, string> = {
  indices: "Готовые значения индексов по авторам.",
  authors_local_metrics: "Строгие локальные индексы, рассчитанные по works/authorships.",
  authors_preview: "Глобальные author profile поля OpenAlex для предварительного отбора.",
  ratings: "Ранги по метрикам и режимам учёта.",
  works: "Плоская таблица работ, полученных из OpenAlex.",
  authorships: "Авторства и организации из OpenAlex.",
  author_work: "Работа, автор, вклад и качество связи.",
  top1_sensitivity: "Проверка устойчивости лидера рейтинга.",
  fraction_sensitivity: "Сравнение режимов фракционирования.",
};

const columnLabels: Record<string, string> = {
  author_id: "ID автора",
  author_display_name: "Автор",
  country_code: "Страна",
  subject_name: "Предметная область",
  work_id: "ID работы",
  work_display_name: "Название работы",
  title: "Название",
  display_name: "Название",
  source_display_name: "Источник",
  publication_date: "Дата публикации",
  publication_year: "Год",
  cited_by_count: "Цитирования",
  works_count: "Работы",
  authors_count: "Число авторов",
  valid_authors_count: "Валидных авторов",
  author_seq: "Позиция автора",
  fraction_mode: "Режим фракционирования",
  metric_name: "Метрика",
  score: "Значение",
  rank_competition: "Ранг",
  rank_dense: "Плотный ранг",
  p: "P",
  c: "C",
  c_frac: "Фракц. цитирования",
  cpp: "CPP",
  h: "Хирш",
  i10: "i10",
  g: "g",
  m_local: "m локальный",
  top1_share: "Доля top-1",
  f5: "f5",
  fm5: "fm5",
  iupv: "IUPV",
  islv: "ISLV",
  lrdi: "LRDI",
  mean_authors_per_work: "Среднее число авторов",
  share_single_authored: "Доля одноавторских",
  rank: "Ранг",
  spearman_vs_base: "Spearman к базе",
  top20_retention: "Сохранение top-20",
};

export const LOAD_LIMIT_OPTIONS: SelectOption[] = [
  { value: "100", label: "100 работ", description: "Быстрая проверка фильтров.", example: "для первого запуска" },
  { value: "500", label: "500 работ", description: "Небольшой аналитический срез.", example: "для черновой оценки" },
  { value: "1000", label: "1 000 работ", description: "Стандартный стартовый объём.", example: "рекомендуется" },
  { value: "2500", label: "2 500 работ", description: "Более устойчивый рейтинг.", example: "для сравнения авторов" },
  { value: "5000", label: "5 000 работ", description: "Рекомендуемый baseline из методологии.", example: "для финального цикла" },
  { value: "10000", label: "10 000 работ", description: "Крупный срез через API.", example: "дольше загружается" },
];

export const DUMP_SIZE_OPTIONS: SelectOption[] = [
  { value: "104857600", label: "100 МБ", description: "Безопасный smoke-дамп для проверки фильтра.", example: "первый запуск" },
  { value: "524288000", label: "500 МБ", description: "Рекомендуемый MVP-лимит для ноутбука.", example: "стандартный срез" },
  { value: "1073741824", label: "1 ГБ", description: "Расширенный локальный срез.", example: "если хватает места" },
  { value: "2147483648", label: "2 ГБ", description: "Крупный API-срез; лучше запускать осознанно.", example: "долгая загрузка" },
];

export const METRIC_OPTIONS: SelectOption[] = METRICS.map((value) => ({
  value,
  label: metricLabels[value],
  description: metricDescriptions[value],
  example: value === "iupv" ? "для итогового топа" : undefined,
}));

export const CORE_METRIC_OPTIONS: SelectOption[] = METRIC_OPTIONS.filter((item) => ["p", "c", "c_frac", "cpp", "h", "i10", "g", "m_local"].includes(item.value));
export const PRIMARY_METRIC_OPTIONS: SelectOption[] = METRIC_OPTIONS.filter((item) => ["islv", "iupv", "p", "c", "c_frac", "cpp", "h", "i10", "g", "m_local"].includes(item.value));

export const WORKFLOW_MODE_OPTIONS: SelectOption[] = [
  { value: "strict_works", label: "Строгий срез", description: "Works API, локальные индексы и доказательная аналитика." },
  { value: "author_preview", label: "Быстрая витрина", description: "Authors API для предварительного отбора и сравнения с глобальным профилем." },
];

export const FILTER_MODE_OPTIONS: SelectOption[] = [
  { value: "primary_topic", label: "Точная тематическая принадлежность", description: "Работа относится к выбранному направлению как к основной теме." },
  { value: "topics_any", label: "Расширенное тематическое покрытие", description: "Работа может относиться к направлению как к одной из тем." },
  { value: "keyword", label: "По ключевому слову", description: "Для ручной исследовательской настройки." },
  { value: "search", label: "По текстовому запросу", description: "Для редких случаев, когда нет подходящей темы." },
];

export const AFFILIATION_MODE_OPTIONS: SelectOption[] = [
  { value: "historical", label: "Историческая аффилиация", description: "Организация указана в authorships/affiliations." },
  { value: "current", label: "Текущая организация", description: "Только last_known_institutions в Authors API." },
];

export const FRACTION_MODE_OPTIONS: SelectOption[] = FRACTION_MODES.map((value) => ({
  value,
  label: modeLabels[value],
  description: modeDescriptions[value],
}));

export const TABLE_OPTIONS: SelectOption[] = TABLES.filter((table) => table !== "ratings").map((value) => ({
  value,
  label: tableLabels[value],
  description: tableDescriptions[value],
}));

export function metricLabel(value: string) {
  return metricLabels[value] ?? value;
}

export function modeLabel(value: string) {
  return modeLabels[value] ?? value;
}

export function tableLabel(value: string) {
  return tableLabels[value] ?? value;
}

export function columnLabel(value: string) {
  return columnLabels[value] ?? value;
}

export function countryLabel(value: string) {
  return value;
}

export function resolveCountryInput(value: string) {
  const text = value.trim();
  if (!text) return "";
  const codeFromLabel = text.match(/\(([A-Za-z]{2})\)\s*$/);
  if (codeFromLabel) return codeFromLabel[1].toUpperCase();
  const upper = text.toUpperCase();
  if (/^[A-Z]{2}$/.test(upper)) return upper;
  return "";
}

export function fmt(v: unknown) {
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v ?? "");
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 3 }).format(n);
}

export function filterParams(filters: ActiveFilters, extra?: Record<string, string | number | undefined | null>) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (String(value ?? "").trim()) params.set(key, String(value).trim());
  });
  Object.entries(extra ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim()) params.set(key, String(value).trim());
  });
  return params;
}

export function filterSummary(filters: ActiveFilters) {
  const subject = filters.filter_mode === "keyword"
    ? (filters.keyword_name || "ключевое слово не выбрано")
    : filters.filter_mode === "search"
      ? (filters.text_search_query || "поисковый запрос не задан")
      : (filters.subject_name || "предметная область не выбрана");
  const country = filters.country_code ? countryLabel(filters.country_code) : "все страны";
  const institution = filters.institution_name ? ` · ${filters.institution_name}` : "";
  const author = filters.author_name ? ` · ${filters.author_name}` : "";
  const source = filters.source_name ? ` · ${filters.source_name}` : "";
  const period = [filters.from_publication_date, filters.to_publication_date].filter(Boolean).join("—");
  return `${subject} · ${country}${institution}${author}${source}${period ? ` · ${period}` : ""}`;
}
