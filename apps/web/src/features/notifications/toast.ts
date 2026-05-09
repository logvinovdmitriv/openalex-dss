export type ToastTone = "error" | "success" | "info";
export type ToastPayload = { title: string; message: string; tone?: ToastTone; key?: string };
export type ToastItem = ToastPayload & { id: string; tone: ToastTone };

export const TOAST_EVENT = "openalex-dss-toast";

const toastDedupe = new Map<string, number>();

export function emitToast(payload: ToastPayload) {
  if (typeof window === "undefined") return;
  const message = String(payload.message || "").trim();
  if (!message) return;
  const key = payload.key ?? `${payload.title}:${message}`;
  const now = Date.now();
  if (now - (toastDedupe.get(key) ?? 0) < 5_000) return;
  toastDedupe.set(key, now);
  window.dispatchEvent(new CustomEvent<ToastPayload>(TOAST_EVENT, { detail: { ...payload, message, key } }));
}
