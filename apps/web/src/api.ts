export const API_BASE = import.meta.env.VITE_API_URL ?? "/api/v1";

export type TableResponse = {
  table: string;
  fields: string[];
  rows: Record<string, unknown>[];
  total: number;
  limit: number;
  offset: number;
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

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  const data = await safeJson(res);
  if (!res.ok) throw new ApiError(errorMessage(data, res.status), res.status, data);
  return data as T;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await safeJson(res);
  if (!res.ok) throw new ApiError(errorMessage(data, res.status), res.status, data);
  return data as T;
}

export async function deleteJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
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
    const detail = payload.detail ?? payload.error;
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
    500: "Внутренняя ошибка сервера. Подробности есть в журнале backend.",
  };
  return labels[status] ?? `Ошибка сервера: ${status}`;
}
