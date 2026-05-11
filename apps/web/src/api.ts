export const API_BASE = import.meta.env.VITE_API_URL ?? "/api/v1";

export type TableResponse = {
  table: string;
  fields: string[];
  rows: Record<string, unknown>[];
  total?: number | null;
  total_exact?: boolean;
  has_more?: boolean;
  next_offset?: number | null;
  next_cursor?: string | null;
  cursor?: string;
  limit: number;
  offset: number;
  scope_status?: string;
  reproducible?: boolean;
  warnings?: string[];
};

export type TableColumnSchema = {
  field: string;
  label: string;
  description?: string;
  type: "text" | "number" | "boolean" | "date" | string;
  physical_type?: string;
  sortable?: boolean;
  filterable?: boolean;
};

export type TableSchemaResponse = {
  kind: string;
  label: string;
  columns: TableColumnSchema[];
  run_id?: string;
  dump_id?: string;
  scope_status?: string;
  reproducible?: boolean;
  warnings?: string[];
};

export type TableColumnFilter = {
  contains?: string;
  min?: string;
  max?: string;
};

export type TableColumnFilters = Record<string, TableColumnFilter>;

export type CustomMetricDefinition = {
  id: string;
  label: string;
  description?: string;
  expression: string;
  enabled?: boolean;
};

export async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await safeFetch(path, init);
  const data = await safeJson(res);
  if (!res.ok) throw new ApiError(errorMessage(data, res.status), res.status, data);
  return data as T;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await safeFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await safeJson(res);
  if (!res.ok) throw new ApiError(errorMessage(data, res.status), res.status, data);
  return data as T;
}

export async function deleteJson<T>(path: string): Promise<T> {
  const res = await safeFetch(path, { method: "DELETE" });
  const data = await safeJson(res);
  if (!res.ok) throw new ApiError(errorMessage(data, res.status), res.status, data);
  return data as T;
}

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

async function safeFetch(path: string, init?: RequestInit) {
  try {
    return await fetch(`${API_BASE}${path}`, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(networkErrorMessage(), 0, {
      detail: error instanceof Error ? error.message : String(error),
      path,
    });
  }
}

function networkErrorMessage() {
  if (API_BASE.startsWith("/")) {
    return "Сервер приложения недоступен. Запустите backend на 127.0.0.1:8000 и обновите страницу.";
  }
  return `Сервер приложения недоступен по адресу ${API_BASE}. Проверьте запуск backend и обновите страницу.`;
}

async function safeJson(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

function errorMessage(data: unknown, status: number) {
  if (data && typeof data === "object") {
    const payload = data as Record<string, unknown>;
    const envelope = payload.error;
    if (envelope && typeof envelope === "object") {
      const error = envelope as Record<string, unknown>;
      const message = String(error.message ?? "").trim();
      const action = String(error.action ?? "").trim();
      if (message && action) return `${message} ${action}`;
      if (message) return message;
    }
    const detail = payload.detail ?? envelope;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const message = detail
        .map((item) => validationIssueMessage(item))
        .filter(Boolean)
        .join("; ");
      if (message) return message;
    }
    const message = validationIssueMessage(payload);
    if (message) return message;
  }
  return httpStatusMessage(status);
}

function validationIssueMessage(item: unknown) {
  if (!item || typeof item !== "object") return "";
  const payload = item as Record<string, unknown>;
  const rawMessage = String(payload.msg ?? payload.message ?? "").trim();
  const loc = Array.isArray(payload.loc)
    ? payload.loc.map((part) => String(part)).filter((part) => part !== "query" && part !== "body").join(".")
    : "";
  const fieldLabel = loc ? apiFieldLabel(loc.split(".").at(-1) || loc) : "";
  if (!rawMessage && !fieldLabel) return "";
  const message = translateValidationMessage(rawMessage);
  return [fieldLabel, message].filter(Boolean).join(": ");
}

function translateValidationMessage(message: string) {
  const text = message.toLowerCase();
  if (text.includes("greater than or equal")) return "значение меньше допустимого";
  if (text.includes("less than or equal")) return "значение больше допустимого";
  if (text.includes("field required")) return "обязательное поле не заполнено";
  if (text.includes("valid integer")) return "нужно целое число";
  if (text.includes("valid number")) return "нужно число";
  if (text.includes("string should have")) return "строка не соответствует ограничению";
  return message || "некорректное значение";
}

function apiFieldLabel(field: string) {
  const labels: Record<string, string> = {
    limit: "Количество строк",
    top_n: "Количество авторов",
    rank_top_n: "Количество авторов для сравнения",
    data_limit: "Ограничение из таблицы “Данные”",
    run_id: "Расчет",
    dump_id: "Срез",
    metrics: "Показатели",
    baseline_metric: "Основной показатель",
    custom_metric_defs: "Собственные формулы",
  };
  return labels[field] ?? field;
}

function httpStatusMessage(status: number) {
  const labels: Record<number, string> = {
    400: "Проверьте параметры запроса.",
    401: "Нет доступа. Проверьте ключ или авторизацию.",
    403: "Действие запрещено для текущих настроек.",
    404: "Данные не найдены.",
    409: "Действие конфликтует с текущим состоянием данных.",
    422: "Некорректные параметры запроса.",
    429: "Слишком много запросов. Повторите позже.",
    500: "Сервер не смог обработать запрос. Попробуйте обновить данные или изменить параметры.",
  };
  return labels[status] ?? `Ошибка сервера: ${status}`;
}
