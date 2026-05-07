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

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  const data = await safeJson(res);
  if (!res.ok) throw new Error(errorMessage(data, res.status));
  return data as T;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await safeJson(res);
  if (!res.ok) throw new Error(errorMessage(data, res.status));
  return data as T;
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
  }
  return `HTTP ${status}`;
}
