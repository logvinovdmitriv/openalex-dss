import type { ActiveFilters } from "../domain";
import { fmt } from "../domain";
import { bytesToMb, humanSliceTitle, progressForRun, type WorkbenchRun } from "../workbench";

export function ProgressPanel({ filters, estimate, materialization, run }: { filters: ActiveFilters; estimate: any; materialization: any; run: any }) {
  const steps = [
    { id: "draft", label: "Срез", ready: true },
    { id: "estimated", label: "Оценка", ready: Boolean(estimate) },
    { id: "planned", label: "План", ready: Boolean(materialization) },
    { id: "materializing", label: "Загрузка", ready: run?.status === "completed" || run?.status === "running" },
    { id: "analyzed", label: "Аналитика", ready: run?.result?.build || run?.status === "completed" },
  ];
  return (
    <section className="panel">
      <div className="panel-head">
        <span className="step-badge">Ход работы</span>
        <h2>{humanSliceTitle(filters)}</h2>
      </div>
      <div className="state-line">
        {steps.map((step) => <span key={step.id} className={step.ready ? "ready" : ""}>{step.label}</span>)}
      </div>
      {run && <RunCard run={run} />}
    </section>
  );
}

export function RunCard({ run }: { run: WorkbenchRun }) {
  if (!run) return null;
  const progress = progressForRun(run);
  const details = (run as any).progress ?? {};
  const fetchedWorks = Number(details.fetched ?? 0);
  const targetWorks = Number(details.target_records ?? details.total_available ?? 0);
  const hasWorkCounter = fetchedWorks > 0 || targetWorks > 0;
  const hasFilesCounter = details.files_seen || details.bytes_written;
  const live = runLiveState(run);
  const phases = runProgressPhases(run, details);
  return (
    <div className={`run-card ${run.status === "failed" ? "error" : ""} ${live.active ? "live" : ""}`}>
      <div className="run-live-head">
        <span className={`live-dot ${live.active ? "active" : ""}`} aria-hidden="true" />
        <div>
          <b>{live.title}</b>
          <small>{live.detail}</small>
        </div>
      </div>
      <span className="run-id-line">{runActionTitle(run.action)}: {run.run_id}</span>
      <ProgressBar percent={progress.percent} label={progress.label} tone={run.status === "failed" ? "error" : "normal"} />
      {phases.length > 0 && (
        <div className="run-phase-grid" aria-label="Подробный ход выполнения">
          {phases.map((phase) => (
            <PhaseBar key={phase.id} phase={phase} />
          ))}
        </div>
      )}
      {Object.keys(details).length > 0 && (
        <div className="run-progress-details">
          {hasWorkCounter && <span>{fmt(fetchedWorks)} / {fmt(targetWorks)} работ</span>}
          {details.page_count ? <span>{fmt(details.page_count)} страниц</span> : null}
          {details.files_seen ? <span>{fmt(details.files_seen)} файлов OpenAlex</span> : null}
          {hasFilesCounter ? <span>{fmt(bytesToMb(details.bytes_written ?? 0))} МБ на диске</span> : null}
          {details.elapsed_seconds ? <span>{formatElapsed(details.elapsed_seconds)}</span> : null}
        </div>
      )}
      {run.error && <small>{run.error}</small>}
    </div>
  );
}

export function runActionTitle(action: unknown) {
  const value = String(action ?? "");
  if (value === "recalculate") return "Расчет индексов";
  if (value === "build_from_openalex") return "Скачивание и расчет среза";
  if (value === "fetch_slice_dump") return "Скачивание среза";
  if (value === "repair_dump") return "Восстановление среза";
  return "Задача";
}

export function runCompletedTitle(action: unknown) {
  const value = String(action ?? "");
  if (value === "repair_dump") return "Срез восстановлен";
  if (value === "recalculate") return "Индексы рассчитаны";
  if (value === "fetch_slice_dump") return "Срез скачан";
  if (value === "build_from_openalex") return "Срез скачан и рассчитан";
  return "Задача завершена";
}

function runLiveState(run: WorkbenchRun) {
  const action = String(run.action ?? "");
  const status = String(run.status ?? "");
  const isSliceLoad = action === "build_from_openalex" || action === "fetch_slice_dump";
  if (status === "queued" && action === "repair_dump") return { active: true, title: "Восстановление в очереди", detail: "Операция начнется автоматически." };
  if (status === "queued") return { active: true, title: "Срез в очереди", detail: "Загрузка начнется автоматически." };
  if (status === "running" && action === "repair_dump") return { active: true, title: "Восстановление среза", detail: "Проверка, упаковка, таблицы и расчет отображаются отдельными этапами." };
  if (status === "running" && isSliceLoad) return { active: true, title: "Загрузка среза", detail: "Статус обновляется в реальном времени." };
  if (status === "running") return { active: true, title: "Выполнение", detail: "Статус обновляется в реальном времени." };
  if (status === "cancelling") return {
    active: true,
    title: action === "repair_dump" ? "Остановка восстановления" : "Остановка загрузки",
    detail: action === "repair_dump" ? "Текущий срез останется в списке с текущим состоянием." : "Система сохраняет уже скачанные записи как частичный срез.",
  };
  if (status === "cancelled") return {
    active: false,
    title: action === "repair_dump" ? "Восстановление остановлено" : "Загрузка остановлена",
    detail: action === "repair_dump" ? "Срез можно восстановить повторно из списка срезов." : "Частичный срез будет доступен, если успели скачаться записи.",
  };
  if (status === "completed" && action === "repair_dump") return { active: false, title: "Срез восстановлен", detail: "Локальные таблицы и индексы доступны." };
  if (status === "completed" && isSliceLoad) return { active: false, title: "Срез готов", detail: "Локальные таблицы доступны для анализа." };
  if (status === "completed") return { active: false, title: "Готово", detail: "Задача завершена." };
  if (status === "failed") return {
    active: false,
    title: action === "repair_dump" ? "Восстановление не выполнено" : "Ошибка выполнения",
    detail: "Подробности показаны ниже и в уведомлении.",
  };
  return { active: false, title: action || "Run", detail: status || "нет статуса" };
}

type RunPhase = {
  id: string;
  label: string;
  percent: number | null;
  determinate: boolean;
  state: "pending" | "active" | "done" | "error";
};

function runProgressPhases(run: WorkbenchRun, details: Record<string, any>): RunPhase[] {
  if (Array.isArray(run.progress_phases) && run.progress_phases.length > 0) {
    return run.progress_phases.map((phase, index) => {
      const state = String(phase.state ?? "pending");
      const normalizedState: RunPhase["state"] = state === "active" || state === "done" || state === "error" ? state : "pending";
      const rawPercent = typeof phase.percent === "number" ? Math.max(0, Math.min(100, Math.round(phase.percent))) : null;
      const determinate = phase.determinate === true && rawPercent !== null;
      return {
        id: String(phase.id ?? `phase_${index}`),
        label: String(phase.label ?? "Этап"),
        percent: determinate ? rawPercent : null,
        determinate,
        state: normalizedState,
      };
    });
  }
  const action = String(run.action ?? "");
  const status = String(run.status ?? "");
  const failed = status === "failed";
  const completed = status === "completed";
  const queued = status === "queued";
  const currentStage = String(run.progress_stage ?? details.stage ?? "");
  const phasePercent = (value: unknown) => {
    if (typeof value !== "number") return null;
    return Math.max(0, Math.min(100, Math.round(value)));
  };
  const phase = (id: string, label: string, percentValue: unknown = null): RunPhase => ({
    id,
    label,
    percent: completed ? 100 : phasePercent(percentValue),
    determinate: completed || phasePercent(percentValue) !== null,
    state: failed ? "error" : completed ? "done" : currentStage.includes(label) ? "active" : "pending",
  });
  if (action === "build_from_openalex") {
    return [
      {
        id: "download",
        label: "Скачивание файлов",
        percent: completed ? 100 : phasePercent(details.download_percent),
        determinate: completed || phasePercent(details.download_percent) !== null,
        state: failed ? "error" : completed ? "done" : queued ? "pending" : (currentStage.includes("Загрузка") ? "active" : "pending"),
      },
      phase("pack", "Упаковка среза", details.pack_percent),
      phase("normalize", "Подготовка таблиц"),
      phase("compute", "Расчет индексов"),
    ];
  }
  if (action === "fetch_slice_dump") {
    return [
      {
        id: "download",
        label: "Скачивание файлов",
        percent: completed ? 100 : phasePercent(details.download_percent),
        determinate: completed || phasePercent(details.download_percent) !== null,
        state: failed ? "error" : completed ? "done" : queued ? "pending" : "active",
      },
      phase("pack", "Упаковка среза", details.pack_percent),
    ];
  }
  if (action === "repair_dump") {
    return [
      phase("check", "Проверка файлов"),
      phase("pack", "Упаковка", details.pack_percent),
      phase("normalize", "Подготовка таблиц"),
      phase("compute", "Расчет индексов"),
    ];
  }
  if (action === "recalculate") {
    return [
      phase("check", "Проверка таблиц"),
      phase("compute", "Расчет индексов"),
      phase("report", "Паспорт и отчет"),
    ];
  }
  return [];
}

function PhaseBar({ phase }: { phase: RunPhase }) {
  return (
    <div className={`run-phase ${phase.state}`}>
      <div className="progress-meta">
        <span>{phase.label}</span>
        <b>{phase.determinate && phase.percent !== null ? `${phase.percent}%` : phaseStateLabel(phase.state)}</b>
      </div>
      <div className={`progress-track ${phase.state === "error" ? "error" : ""}`}>
        <span className={!phase.determinate && phase.state === "active" ? "indeterminate" : ""} style={{ width: phase.determinate && phase.percent !== null ? `${phase.percent}%` : (phase.state === "done" ? "100%" : "0%") }} />
      </div>
    </div>
  );
}

function phaseStateLabel(state: RunPhase["state"]) {
  if (state === "done") return "готово";
  if (state === "active") return "выполняется";
  if (state === "error") return "ошибка";
  return "ожидает";
}

function ProgressBar({ percent, label, tone = "normal" }: { percent: number | null; label: string; tone?: "normal" | "error" }) {
  return (
    <div className="progress-group" aria-label={percent === null ? label : `${label}: ${percent}%`}>
      <div className="progress-meta">
        <span>{label}</span>
        <b>{percent === null ? "выполняется" : `${percent}%`}</b>
      </div>
      <div className={`progress-track ${tone}`}>
        <span className={percent === null ? "indeterminate" : ""} style={{ width: percent === null ? "0%" : `${percent}%` }} />
      </div>
    </div>
  );
}

function formatElapsed(seconds: unknown) {
  const value = Number(seconds || 0);
  if (!Number.isFinite(value) || value <= 0) return "";
  const rounded = Math.round(value);
  const minutes = Math.floor(rounded / 60);
  const rest = rounded % 60;
  if (minutes <= 0) return `${rest} сек`;
  return `${minutes} мин ${rest} сек`;
}
