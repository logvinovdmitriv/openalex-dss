import { X } from "lucide-react";
import type { ToastItem } from "./toast";

export function ToastViewport({ toasts, onClose }: { toasts: ToastItem[]; onClose: (id: string) => void }) {
  if (toasts.length === 0) return null;
  return (
    <div className="toast-viewport" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <section key={toast.id} className={`toast-card ${toast.tone}`}>
          <div>
            <b>{toast.title}</b>
            <span>{toast.message}</span>
          </div>
          <button type="button" aria-label="Закрыть уведомление" onClick={() => onClose(toast.id)}>
            <X size={15} />
          </button>
        </section>
      ))}
    </div>
  );
}
