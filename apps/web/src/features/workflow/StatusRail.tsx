import { Database, Gauge, Sigma } from "lucide-react";
import { fmt } from "../../domain";
import { progressForRun, type WorkbenchRun, type WorkbenchState } from "../../workbench";

export function StatusRail({ state, run, running }: { state?: WorkbenchState; run?: WorkbenchRun; running: boolean }) {
  const tables = state?.tables ?? {};
  const progress = progressForRun(run);
  return (
    <div className="status-rail">
      <span><Database size={15} /> Работы: {fmt(tables?.works?.rows ?? 0)}</span>
      <span><Sigma size={15} /> Авторы: {fmt(tables?.indices?.rows ?? 0)}</span>
      <span><Gauge size={15} /> {running ? (progress.percent === null ? progress.label : `${progress.label} · ${progress.percent}%`) : run?.status ?? state?.workflow?.active_stage ?? "idle"}</span>
    </div>
  );
}

