export const METRICS = ["p", "c", "c_frac", "cpp", "h", "i10", "g", "m_local", "top1_share", "lrdi", "f5", "fm5", "iupv", "islv"] as const;
export const FRACTION_MODES = ["strict_authors_count", "renorm_valid_authors", "integer"] as const;
export const TABLES = ["indices", "ratings", "works", "authorships", "work_topics", "author_work"] as const;

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
  formula?: string;
  custom?: boolean;
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

const CURRENT_YEAR = new Date().getFullYear();

export const DEFAULT_FILTERS: ActiveFilters = {
  subject_level: "",
  subject_id: "",
  subject_name: "",
  filter_mode: "all",
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
  from_publication_date: `${CURRENT_YEAR - 5}-01-01`,
  to_publication_date: `${CURRENT_YEAR}-12-31`,
  work_type: "",
};

const metricLabels: Record<string, string> = {
  p: "Публикации",
  c: "Цитирования",
  c_frac: "Цитирования с долевым учетом",
  cpp: "Средняя цитируемость",
  h: "Индекс Хирша",
  i10: "Работы с 10+ цитированиями",
  g: "Индекс g",
  m_local: "Индекс m внутри среза",
  top1_share: "Доля цитирований самой цитируемой работы",
  lrdi: "Индекс устойчивости результата",
  f5: "Работы с 5+ цитированиями",
  fm5: "Долевой вклад в работы с 5+ цитированиями",
  iupv: "PCI: процентильный композит",
  islv: "Процентильная формула: сбалансированный вклад",
  mean_authors_per_work: "Среднее число авторов",
  share_single_authored: "Доля одноавторских работ",
};

const metricDescriptions: Record<string, string> = {
  p: "Сколько публикаций автора попало в выбранный срез.",
  c: "Сколько раз эти публикации процитированы в OpenAlex.",
  c_frac: "Цитирования с поправкой на число соавторов публикации.",
  cpp: "Среднее число цитирований на одну публикацию внутри среза.",
  h: "Классический индекс Хирша внутри выбранного среза.",
  i10: "Число работ автора с 10 и более цитированиями.",
  g: "Показатель, который сильнее учитывает высокоцитируемые работы автора.",
  m_local: "Индекс Хирша с учетом длительности публикационного окна автора в срезе.",
  top1_share: "Показывает концентрацию цитирований в самой цитируемой работе автора.",
  lrdi: "Показывает устойчивость результата с учетом соавторства и свежести публикаций.",
  f5: "Дополнительный пороговый показатель: сколько публикаций автора имеют 5 и более цитирований.",
  fm5: "Дополнительный пороговый показатель с долевым учетом вклада автора в публикации с 5 и более цитированиями.",
  iupv: "Экспериментальная формула рейтинга на процентильной шкале: объединяет число публикаций, индекс Хирша и долевые цитирования внутри выбранного среза.",
  islv: "Экспериментальная формула рейтинга на процентильной шкале: объединяет индекс Хирша, долевые цитирования, индекс g, i10 и публикации с поправкой на концентрацию цитирований.",
  mean_authors_per_work: "Среднее число соавторов в работах автора.",
  share_single_authored: "Доля работ, где автор указан один.",
};

const metricFormulas: Record<string, string> = {
  p: "P(a) = |W_a|",
  c: "C(a) = Σ c_i",
  c_frac: "Cд(a) = Σ c_i / n_i",
  cpp: "CPP(a) = C(a) / P(a)",
  h: "h(a) = max h: не менее h работ имеют ≥ h цитирований",
  i10: "i10(a) = |{i: c_i ≥ 10}|",
  g: "g(a) = max g: Σ_{i=1..g} c_i ≥ g²",
  m_local: "m(a) = h(a) / T_a",
  top1_share: "S₁(a) = max(c_i) / C(a)",
  f5: "f5(a) = |{i: c_i ≥ 5}|",
  fm5: "fm5(a) = Σ w_i для работ, где c_i ≥ 5",
  iupv: "PCI(a) = 100 · (pr(P) · pr(h) · pr(Cд))^(1/3)",
  islv: "R₂(a) = 100 · G_w(pr(h), pr(Cд), pr(g), pr(i10), pr(P)) · штраф(S₁)",
  lrdi: "LRDI(a) = shrink(P) · Σ [ln(1 + c_i) / n_i] · exp(-λ · age_i)",
};

const modeLabels: Record<string, string> = {
  strict_authors_count: "Долевой учет по всем авторам",
  renorm_valid_authors: "Долевой учет по распознанным авторам",
  integer: "Каждый автор учитывается полностью",
};

const modeDescriptions: Record<string, string> = {
  strict_authors_count: "Вклад публикации делится на всех авторов, указанных в работе.",
  renorm_valid_authors: "Вклад публикации делится только между авторами, которых удалось надежно распознать.",
  integer: "Публикация полностью засчитывается каждому автору.",
};

const tableLabels: Record<string, string> = {
  indices: "Авторы и индексы",
  ratings: "Рейтинговые позиции",
  works: "Работы OpenAlex",
  authorships: "Авторства",
  work_topics: "Темы работ",
  author_work: "Плоская связь автор-работа",
};

const tableDescriptions: Record<string, string> = {
  indices: "Авторская таблица: один автор на строку и рассчитанные показатели.",
  ratings: "Места авторов по показателям и режимам учета.",
  works: "Плоская таблица работ, полученных из OpenAlex.",
  authorships: "Авторства и организации из OpenAlex.",
  work_topics: "Развернутый список OpenAlex topics для локального topics_any.",
  author_work: "Работа, автор, вклад и качество связи.",
};

const columnLabels: Record<string, string> = {
  id: "Идентификатор",
  run_id: "ID расчета",
  source_run_id: "Исходный расчет",
  dump_id: "ID среза",
  source_dump_id: "Исходный срез",
  slice_id: "ID описания среза",
  cohort_id: "ID выборки авторов",
  schema: "Схема данных",
  status: "Статус",
  source: "Источник",
  source_path: "Путь к файлу",
  resolved_path: "Фактический путь",
  path: "Путь",
  exists: "Есть файл",
  rows: "Строк",
  total: "Всего строк",
  limit: "Лимит строк",
  offset: "Смещение",
  kind: "Тип таблицы",
  label: "Название",
  author_id: "ID автора",
  author_display_name: "Автор",
  author_orcid: "ORCID автора",
  author_country_code: "Страна автора",
  country_codes_csv: "Страны автора",
  institution_ids_csv: "Организации автора",
  institution_id: "ID организации",
  institution_display_name: "Организация",
  institution_ror: "ROR организации",
  country_code: "Страна",
  subject_name: "Предметная область",
  work_id: "ID работы",
  work_display_name: "Название работы",
  title: "Название",
  display_name: "Название",
  doi: "DOI",
  type: "Тип публикации",
  work_type: "Тип публикации",
  source_id: "ID источника",
  source_display_name: "Источник",
  source_type: "Тип источника",
  language: "Язык",
  open_access_is_oa: "Открытый доступ",
  has_abstract: "Есть аннотация",
  publication_date: "Дата публикации",
  publication_year: "Год",
  cited_by_count: "Цитирования",
  updated_date: "Дата обновления",
  created_date: "Дата создания",
  primary_topic_id: "ID основной темы",
  primary_topic_display_name: "Основная тема",
  primary_subfield_short_id: "Код подобласти",
  primary_subfield_id: "ID подобласти",
  primary_field_id: "ID области",
  topic_id: "ID темы",
  topic_display_name: "Тема",
  subfield_id: "ID подобласти",
  field_id: "ID области",
  domain_id: "ID домена",
  is_primary: "Основная тема",
  score_topic: "Оценка темы",
  score_topic_relevance: "Релевантность темы",
  works_count: "Работы",
  authors_count: "Число авторов",
  valid_authors_count: "Валидных авторов",
  author_seq: "Позиция автора",
  authors_count_used: "Авторов учтено",
  actual_authors_count: "Фактическое число авторов",
  authors_count_reported: "Авторов указано в OpenAlex",
  credit_weight: "Доля вклада",
  cited_credit: "Долевые цитирования",
  single_authored_flag: "Один автор",
  qf_any: "Есть замечание к данным",
  qf_authorship_truncated: "Список авторов неполный",
  n_flagged_works: "Работ с замечаниями к данным",
  n_truncated_works: "Работ с неполным списком авторов",
  fraction_mode: "Учет вклада авторов",
  metric_name: "Показатель",
  rank_metric: "Показатель рейтинга",
  score: "Значение",
  value: "Значение",
  rank_competition: "Место",
  rank_dense: "Место без пропусков",
  position: "Позиция",
  rank_ordinal: "Позиция",
  p: "Публикации",
  c: "Цитирования",
  c_frac: "Долевые цитирования",
  cpp: "Средняя цитируемость",
  h: "Индекс Хирша",
  i10: "Работы с 10+ цитированиями",
  g: "Индекс g",
  m_local: "Индекс m",
  top1_share: "Доля самой цитируемой работы",
  f5: "Работы с 5+ цитированиями",
  fm5: "Долевой вклад в работы с 5+ цитированиями",
  iupv: "PCI: процентильный композит",
  islv: "Процентильная формула: сбалансированный вклад",
  lrdi: "Индекс устойчивости результата",
  mean_authors_per_work: "Среднее число авторов",
  share_single_authored: "Доля одноавторских",
  rank: "Место",
  baseline_metric: "Основной показатель",
  compare_metric: "Сравниваемый показатель",
  baseline_rank: "Место по основному показателю",
  metric_rank: "Место по показателю",
  rank_delta: "Изменение места",
  abs_rank_delta: "Абсолютное изменение места",
  method: "Метод",
  left_metric: "Первый показатель",
  right_metric: "Второй показатель",
  min: "Минимум",
  max: "Максимум",
  q1: "Первый квартиль",
  q3: "Третий квартиль",
  median: "Медиана",
  mean: "Среднее",
  stddev: "Стандартное отклонение",
  coefficient_of_variation: "Коэффициент вариации",
  iqr: "Межквартильный размах",
  p90: "90-й процентиль",
  p95: "95-й процентиль",
  p99: "99-й процентиль",
  n: "Наблюдений",
  n_authors: "Авторов",
  missing_count: "Пропущено значений",
  zero_count: "Нулевых значений",
  zero_rate: "Доля нулевых значений",
  skewness: "Перекос распределения",
  excess_kurtosis: "Резкие крайние значения",
  tie_rate: "Доля совпадающих значений",
  unique_count: "Уникальных значений",
  outlier_count_iqr: "Выбросов по правилу IQR",
  outlier_share_iqr: "Доля выбросов по правилу IQR",
  rule: "Правило",
  lower_fence: "Нижняя граница",
  upper_fence: "Верхняя граница",
  severity: "Важность",
  text: "Текст",
  recommendation: "Рекомендация",
  evidence_json: "Основания",
  spearman_vs_base: "Связь с основным показателем",
  top20_retention: "Совпадение первых 20 строк",
};

export const WORK_TYPE_LABELS: Record<string, string> = {
  article: "Статья",
  review: "Обзор",
  "conference-paper": "Материалы конференции",
  book: "Книга",
  "book-chapter": "Глава книги",
  "book-section": "Раздел книги",
  preprint: "Препринт",
  dissertation: "Диссертация",
  report: "Отчет",
  "report-component": "Раздел отчета",
  dataset: "Набор данных",
  database: "База данных",
  software: "Программное обеспечение",
  standard: "Стандарт",
  editorial: "Редакционная статья",
  erratum: "Исправление",
  letter: "Письмо в редакцию",
  "peer-review": "Рецензия",
  "reference-entry": "Справочная статья",
  retraction: "Сообщение об отзыве",
  paratext: "Служебный текст",
  other: "Другое",
  libguides: "Библиотечный путеводитель",
  "supplementary-materials": "Дополнительные материалы",
  grant: "Грант",
};

export const SOURCE_TYPE_LABELS: Record<string, string> = {
  journal: "Журнал",
  repository: "Репозиторий",
  conference: "Конференция",
  "ebook platform": "Платформа электронных книг",
  "book series": "Книжная серия",
  metadata: "Метаданные",
  other: "Другое",
};

export const METRIC_OPTIONS: SelectOption[] = METRICS.map((value) => ({
  value,
  label: metricLabels[value],
  description: metricDescriptions[value],
  example: ["p", "c", "c_frac", "h", "i10", "g"].includes(value) ? "базовый контур" : "дополнительно",
}));

export const CORE_METRIC_OPTIONS: SelectOption[] = METRIC_OPTIONS.filter((item) => ["p", "c", "c_frac", "h", "i10", "g"].includes(item.value));
export const PRIMARY_METRIC_OPTIONS: SelectOption[] = METRIC_OPTIONS.filter((item) => ["p", "c", "c_frac", "h", "i10", "g"].includes(item.value));

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

export function metricDescription(value: string) {
  return metricDescriptions[value] ?? "";
}

export function metricFormula(value: string) {
  return metricFormulas[value] ?? metricDescriptions[value] ?? "";
}

export function modeLabel(value: string) {
  return modeLabels[value] ?? value;
}

export function tableLabel(value: string) {
  return tableLabels[value] ?? value;
}

export function columnLabel(value: string) {
  return columnLabels[value] ?? metricLabels[value] ?? humanizeColumnName(value);
}

export function workTypeLabel(value: string) {
  const code = String(value || "").trim();
  if (!code) return "";
  return `${WORK_TYPE_LABELS[code] ?? humanizeToken(code)} (${code})`;
}

export function sourceTypeLabel(value: string) {
  const code = String(value || "").trim();
  if (!code) return "";
  return `${SOURCE_TYPE_LABELS[code] ?? humanizeToken(code)} (${code})`;
}

export function languageLabel(value: string) {
  const code = String(value || "").trim().toLowerCase();
  if (!code) return "";
  try {
    const name = new Intl.DisplayNames(["ru"], { type: "language" }).of(code);
    return name && name !== code ? `${name} (${code})` : code;
  } catch {
    return code;
  }
}

export function humanizeToken(value: string) {
  return String(value || "")
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(" ");
}

function humanizeColumnName(value: string) {
  const clean = String(value || "").trim();
  if (!clean) return "";
  const expanded = clean
    .replace(/_id$/i, "_identifier")
    .replace(/_csv$/i, "")
    .replace(/_/g, " ");
  return expanded
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => COLUMN_WORDS[part] ?? part)
    .join(" ")
    .replace(/^./, (char) => char.toUpperCase());
}

const COLUMN_WORDS: Record<string, string> = {
  abs: "модуль",
  analysis: "анализ",
  author: "автор",
  authors: "авторы",
  authorship: "авторство",
  authorships: "авторства",
  baseline: "базовый",
  checksum: "контрольная сумма",
  cited: "цитирования",
  cohort: "выборка",
  compare: "сравнение",
  count: "число",
  current: "текущий",
  data: "данные",
  dense: "плотный",
  display: "отображаемое",
  dump: "срез",
  evidence: "основания",
  field: "область",
  filter: "фильтр",
  fraction: "доля",
  identifier: "ID",
  institution: "организация",
  local: "локальный",
  metric: "показатель",
  mode: "режим",
  name: "название",
  outlier: "статистический выброс",
  publication: "публикация",
  rank: "место",
  report: "отчет",
  run: "расчет",
  scope: "область",
  score: "значение",
  source: "источник",
  status: "статус",
  table: "таблица",
  topic: "тема",
  type: "тип",
  value: "значение",
  work: "работа",
  works: "работы",
};

export function countryLabel(value: string) {
  const code = value.trim().toUpperCase();
  if (!/^[A-Z]{2}$/.test(code)) return value;
  try {
    const name = new Intl.DisplayNames(["ru"], { type: "region" }).of(code);
    return name && name !== code ? `${name} (${code})` : code;
  } catch {
    return code;
  }
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
