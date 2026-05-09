import type { ReactNode } from "react";
import { BarChart3, Database, Download, Layers3, Sigma } from "lucide-react";
import type { View } from "../../workbench";

export type WorkflowNavItem = {
  id: View;
  label: string;
  icon: ReactNode;
  index: number;
  unlocked: boolean;
  complete: boolean;
  active: boolean;
  reason: string;
  fallback: View;
};

const NAV: Array<{ id: View; label: string; icon: ReactNode }> = [
  { id: "slices", label: "Срез", icon: <Layers3 size={17} /> },
  { id: "data", label: "Данные", icon: <Database size={17} /> },
  { id: "rankings", label: "Индексы", icon: <Sigma size={17} /> },
  { id: "statistics", label: "Аналитика", icon: <BarChart3 size={17} /> },
  { id: "reports", label: "Отчеты", icon: <Download size={17} /> },
];

export function buildWorkflowNav({
  view,
  scopeReady,
  hasAvailableLocalTables,
  hasAuthorIndices,
  running,
}: {
  view: View;
  scopeReady: boolean;
  hasAvailableLocalTables: boolean;
  hasAuthorIndices: boolean;
  running: boolean;
}): WorkflowNavItem[] {
  const reasons: Partial<Record<View, string>> = {
    data: "Сначала выберите или скачайте срез",
    rankings: "Сначала выберите или скачайте срез",
    statistics: running ? "Дождитесь завершения текущей задачи" : "Сначала рассчитайте индексы",
    reports: running ? "Дождитесь завершения текущей задачи" : "Сначала рассчитайте индексы",
  };
  const unlocked: Record<View, boolean> = {
    slices: true,
    data: scopeReady,
    rankings: scopeReady,
    statistics: scopeReady && hasAuthorIndices && !running,
    reports: scopeReady && hasAuthorIndices && !running,
  };
  const complete: Record<View, boolean> = {
    slices: scopeReady,
    data: scopeReady && hasAvailableLocalTables,
    rankings: scopeReady && hasAuthorIndices,
    statistics: scopeReady && hasAuthorIndices,
    reports: scopeReady && hasAuthorIndices,
  };
  return NAV.map((item, index) => {
    const fallback: View = !scopeReady ? "slices" : !hasAuthorIndices && (item.id === "statistics" || item.id === "reports") ? "rankings" : "slices";
    return {
      ...item,
      index: index + 1,
      unlocked: unlocked[item.id],
      complete: complete[item.id] && item.id !== view && !running,
      active: item.id === view,
      reason: reasons[item.id] ?? "",
      fallback,
    };
  });
}

export function nextUnlockedNavIndex(items: WorkflowNavItem[], current: number, key: string) {
  const direction = key === "ArrowDown" || key === "ArrowRight" ? 1 : key === "ArrowUp" || key === "ArrowLeft" ? -1 : 0;
  if (key === "Home") return items.findIndex((item) => item.unlocked);
  if (key === "End") {
    const reversedIndex = [...items].reverse().findIndex((item) => item.unlocked);
    return reversedIndex < 0 ? undefined : items.length - 1 - reversedIndex;
  }
  if (!direction) return undefined;
  for (let index = current + direction; index >= 0 && index < items.length; index += direction) {
    if (items[index].unlocked) return index;
  }
  return current;
}
