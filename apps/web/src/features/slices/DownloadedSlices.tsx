import { Info, Loader2, Wrench, X } from "lucide-react";

import { KeyValue } from "../../components/ui";
import { fmt } from "../../domain";
import { bytesToMb, type WorkbenchDump } from "../../workbench";

export type DownloadedSliceStatus = {
  status: string;
  label: string;
  tone: "ok" | "warn" | "error" | "info";
  reason?: string;
  repairAction?: string;
};

export type DownloadedSliceRow = {
  key: string;
  title: string;
  meta: string;
  detail: string;
  action: string;
  status: DownloadedSliceStatus;
  selectDisabled?: boolean;
  repairAction?: string;
  sliceId: string;
  dumpIds: string[];
  dump?: WorkbenchDump;
};

export function DownloadedSlicesPanel({
  downloadedDumps,
  selectedDumpId,
  repairingDumpId,
  deletingDumpId,
  onSelectDownloadedDump,
  onShowDumpInfo,
  onRepairDownloadedDump,
  onDeleteDownloadedDump,
  onBlocked,
}: {
  downloadedDumps: WorkbenchDump[];
  selectedDumpId: string;
  repairingDumpId: string;
  deletingDumpId: string;
  onSelectDownloadedDump: (dump: WorkbenchDump) => void;
  onShowDumpInfo: (dump: WorkbenchDump) => void;
  onRepairDownloadedDump: (dumpId: string) => void;
  onDeleteDownloadedDump: (dumpId: string) => void;
  onBlocked?: (row: DownloadedSliceRow) => void;
}) {
  const sliceRows = buildDownloadedSliceRows(downloadedDumps).slice(0, 20);
  const selectSliceRow = (row: DownloadedSliceRow) => {
    if (row.selectDisabled) {
      onBlocked?.(row);
      return;
    }
    if (row.dump) onSelectDownloadedDump(row.dump);
  };
  const deleteSliceRow = (row: DownloadedSliceRow) => {
    if (!window.confirm(`Удалить локальный срез “${row.title}”? Будут удалены скачанные файлы и таблицы этого среза.`)) return;
    row.dumpIds.forEach(onDeleteDownloadedDump);
  };
  const repairSliceRow = (row: DownloadedSliceRow) => {
    const dumpId = row.dumpIds[0];
    if (dumpId) onRepairDownloadedDump(dumpId);
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <span className="step-badge">Выбор среза</span>
        <h2>Срезы</h2>
        <p>Здесь показаны только скачанные локальные срезы. Черновики фильтров и история оценок не выводятся как отдельные записи, чтобы не дублировать понятия.</p>
      </div>
      <div className="artifact-picker-column unified-slice-list">
        <b>Скачанные срезы</b>
        {sliceRows.length === 0 && <small>Срезов пока нет. Задайте фильтры, оцените объем и скачайте локальную версию.</small>}
        {sliceRows.map((row) => (
          <ArtifactChoice
            key={row.key}
            title={row.title}
            meta={row.meta}
            detail={row.detail}
            action={row.action}
            status={row.status}
            selected={Boolean(row.dumpIds.length && row.dumpIds.includes(selectedDumpId))}
            onClick={() => selectSliceRow(row)}
            actionDisabled={row.selectDisabled}
            actionHint={row.status.reason}
            onInfo={() => row.dump && onShowDumpInfo(row.dump)}
            repairAction={row.repairAction}
            repairing={row.dumpIds.includes(repairingDumpId)}
            onRepair={() => repairSliceRow(row)}
            deleteAction="Удалить"
            deleting={row.dumpIds.includes(deletingDumpId)}
            onDelete={() => deleteSliceRow(row)}
          />
        ))}
      </div>
    </section>
  );
}

export function buildDownloadedSliceRows(downloadedDumps: WorkbenchDump[]): DownloadedSliceRow[] {
  return downloadedDumps
    .map((dump, index) => {
      const dumpId = String(dump?.dump_id ?? "").trim();
      const sliceId = String(dump?.slice_id ?? "").trim();
      const records = Number(dump?.records_downloaded ?? 0);
      const mb = bytesToMb(Number(dump?.bytes_written ?? dump?.raw_size_bytes ?? 0));
      const updated = String(dump?.updated_at_utc ?? dump?.created_at_utc ?? dump?.created_at ?? "").trim();
      const health = dumpHealth(dump);
      const disabled = health.status === "broken" || health.status === "needs_repair";
      const detail = [
        records ? `${fmt(records)} работ` : "",
        Number.isFinite(mb) && mb > 0 ? `${fmt(mb)} МБ` : "",
        updated ? `обновлен: ${updated}` : "",
        health.reason && health.tone !== "ok" ? health.reason : "",
      ].filter(Boolean).join(" · ") || "локальные файлы готовы";
      return {
        key: dumpId || sliceId || String(dump?.raw_jsonl ?? index),
        title: downloadedSliceTitle(dump),
        meta: health.label,
        detail,
        action: disabled ? "Недоступен" : "Выбрать",
        status: health,
        selectDisabled: disabled,
        repairAction: health.repairAction,
        sliceId,
        dumpIds: dumpId ? [dumpId] : [],
        dump,
      };
    })
    .sort((left, right) => left.title.localeCompare(right.title, "ru"));
}

export function dumpHealth(dump: WorkbenchDump): DownloadedSliceStatus {
  const health = dump?.health ?? {};
  const status = String(health.status ?? "").trim();
  const label = String(health.label ?? "").trim();
  const reason = String(health.reason ?? "").trim();
  if (status === "broken") return { status, label: label || "поврежден", tone: "error", reason };
  if (status === "needs_repair") return { status, label: label || "требует восстановления", tone: "warn", reason, repairAction: "Восстановить" };
  if (status === "ready" && health.repairable) return { status, label: label || "данные готовы", tone: "info", reason, repairAction: "Рассчитать индексы" };
  if (status === "partial") return { status, label: label || "частичный срез", tone: "warn", reason };
  if (status === "analyzed") return { status, label: label || "готов", tone: "ok", reason };
  if (String(dump?.scientific_completeness ?? "") === "partial") return { status: "partial", label: "частичный срез", tone: "warn", reason };
  return { status: status || "downloaded", label: "скачан", tone: "ok", reason };
}

export function downloadedSliceTitle(dump: WorkbenchDump) {
  const title = String(dump?.title ?? dump?.slice_title ?? "").trim();
  if (title) return title;
  const filters = (dump?.filters ?? {}) as Record<string, unknown>;
  const subject = String(dump?.subject_name ?? filters.subject_name ?? "").trim();
  const period = [dump?.from_publication_date, dump?.to_publication_date].map((item) => String(item ?? "").trim()).filter(Boolean).join("–");
  const dumpId = String(dump?.dump_id ?? "").trim();
  return [subject || "Локальный срез", period, dumpId ? dumpId.replace(/^dump_/, "") : ""].filter(Boolean).join(" · ");
}

function ArtifactChoice({
  title,
  meta,
  detail,
  action,
  status,
  onClick,
  actionDisabled = false,
  actionHint,
  selected = false,
  onInfo,
  repairAction,
  repairing = false,
  onRepair,
  deleteAction,
  deleting = false,
  onDelete,
}: {
  title: string;
  meta: string;
  detail: string;
  action: string;
  status?: { label: string; tone: "ok" | "warn" | "error" | "info"; reason?: string };
  onClick: () => void;
  actionDisabled?: boolean;
  actionHint?: string;
  selected?: boolean;
  onInfo?: () => void;
  repairAction?: string;
  repairing?: boolean;
  onRepair?: () => void;
  deleteAction?: string;
  deleting?: boolean;
  onDelete?: () => void;
}) {
  return (
    <div className={`artifact-choice ${selected ? "selected" : ""} ${status ? `status-${status.tone}` : ""}`}>
      <div>
        <strong>{title}</strong>
        <span className={`status-chip ${status?.tone ?? "info"}`}>{status?.label ?? meta}</span>
        <small>{detail}</small>
      </div>
      <div className="artifact-choice-actions">
        {selected && <span className="status-chip ok">выбран</span>}
        {onInfo && (
          <button type="button" className="icon-button" onClick={onInfo} title="Информация о срезе" aria-label="Информация о срезе">
            <Info size={16} />
          </button>
        )}
        <button type="button" onClick={onClick} disabled={actionDisabled} title={actionHint}>{action}</button>
        {onRepair && repairAction && (
          <button type="button" onClick={onRepair} disabled={repairing}>
            {repairing ? <Loader2 size={16} className="spin" /> : <Wrench size={16} />} {repairing ? "Запуск..." : repairAction}
          </button>
        )}
        {onDelete && (
          <button type="button" className="danger-button" onClick={onDelete} disabled={deleting || !deleteAction}>
            {deleting ? "Удаление..." : deleteAction}
          </button>
        )}
      </div>
    </div>
  );
}

export function DumpInfoModal({ dump, onClose }: { dump: WorkbenchDump; onClose: () => void }) {
  const health = dumpHealth(dump);
  const request = (dump?.openalex_request ?? {}) as Record<string, unknown>;
  const storage = (dump?.storage_plan ?? {}) as Record<string, unknown>;
  const storageSummary = (dump?.storage ?? {}) as Record<string, unknown>;
  const signatures = (dump?.signatures ?? {}) as Record<string, unknown>;
  const rawPath = String(dump?.raw_jsonl ?? "");
  const manifestPath = String(dump?.dump_manifest ?? dump?.manifest_path ?? "");
  const filter = String(request?.filter ?? dump?.openalex_filter ?? "");
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Информация о локальном срезе">
      <div className="modal dump-info-modal">
        <div className="modal-head">
          <div>
            <span className={`status-chip ${health.tone}`}>{health.label}</span>
            <h2>{downloadedSliceTitle(dump)}</h2>
            <p>Служебная информация о скачанном локальном срезе, его расположении, объеме и параметрах отбора.</p>
          </div>
          <button type="button" className="icon-button" onClick={onClose} title="Закрыть"><X size={18} /></button>
        </div>
        <div className="key-grid">
          <KeyValue label="Идентификатор среза" value={String(dump?.dump_id ?? "—")} />
          <KeyValue label="Работ" value={fmt(Number(dump?.records_downloaded ?? 0))} />
          <KeyValue label="Ожидалось работ" value={dump?.records_expected ? fmt(Number(dump.records_expected)) : "—"} />
          <KeyValue label="Пакет загрузки" value={`${fmt(bytesToMb(Number(storageSummary?.download_base_bytes ?? storageSummary?.raw_bytes ?? dump?.bytes_written ?? 0)))} МБ`} />
          <KeyValue label="Размер файла среза" value={`${fmt(bytesToMb(Number(storageSummary?.raw_package_bytes ?? dump?.bytes_written ?? 0)))} МБ`} />
          <KeyValue label="Размер таблиц" value={`${fmt(bytesToMb(Number(storageSummary?.tables_bytes ?? 0)))} МБ`} />
          <KeyValue label="Кэш аналитики" value={`${fmt(bytesToMb(Number(storageSummary?.analytics_cache_bytes ?? 0)))} МБ`} />
          <KeyValue label="Всего для этого среза" value={`${fmt(bytesToMb(Number(storageSummary?.total_known_bytes ?? dump?.bytes_written ?? 0)))} МБ`} />
          <KeyValue label="Все хранилище" value={`${fmt(bytesToMb(Number(storageSummary?.data_root_bytes ?? 0)))} МБ`} />
          <KeyValue label="Скачан" value={String(dump?.created_at_utc ?? dump?.download_finished_at_utc ?? "—")} />
          <KeyValue label="Время загрузки" value={dump?.elapsed_seconds ? `${fmt(Number(dump.elapsed_seconds))} сек.` : "—"} />
          <KeyValue label="Полнота" value={dumpCompletenessLabel(String(dump?.scientific_completeness ?? ""))} />
          <KeyValue label="Причина остановки" value={dumpStopReasonLabel(String(dump?.stop_reason ?? ""))} />
          <KeyValue label="Состояние" value={health.reason || "Срез готов к работе."} />
          <KeyValue label="Файлов загрузчика" value={dump?.health?.files_seen ? fmt(Number(dump.health.files_seen)) : "—"} />
          <KeyValue label="Финальный анализ" value={dump?.allowed_for_final_analysis ? "доступен" : "только предварительный"} />
          <KeyValue label="Индексы" value={dump?.health?.indices_ready ? "рассчитаны" : "не рассчитаны"} />
        </div>
        <div className="key-grid">
          <KeyValue label="Папка загрузки" value={String(storageSummary?.download_base_path ?? storage?.download_base_dir ?? "—")} />
          <KeyValue label="Файл среза" value={rawPath || "—"} />
          <KeyValue label="Папка файлов OpenAlex" value={String(dump?.cli_files_dir ?? storage?.cli_output_dir ?? "—")} />
          <KeyValue label="Паспорт загрузки" value={manifestPath || "—"} />
          <KeyValue label="Список файлов" value={String(dump?.files_manifest ?? "—")} />
          <KeyValue label="Папка хранилища" value={String(storageSummary?.data_root_path ?? "—")} />
        </div>
        <details className="technical-details" open>
          <summary>Параметры отбора OpenAlex</summary>
          <pre>{filter || "Фильтр не найден в паспорте среза."}</pre>
        </details>
        <details className="technical-details">
          <summary>Контрольные подписи</summary>
          <div className="key-grid">
            <KeyValue label="Подпись оценки" value={String(signatures?.estimate_signature ?? dump?.estimate_signature ?? "—")} />
            <KeyValue label="Подпись загрузки" value={String(signatures?.download_signature ?? dump?.download_signature ?? "—")} />
            <KeyValue label="SHA-256 файла" value={String(dump?.raw_jsonl_sha256 ?? dump?.sha256 ?? "—")} />
          </div>
        </details>
      </div>
    </div>
  );
}

function dumpCompletenessLabel(value: string) {
  if (value === "complete") return "полный";
  if (value === "partial") return "частичный";
  if (value === "empty") return "пустой";
  if (value === "failed") return "ошибка";
  return value || "не указано";
}

function dumpStopReasonLabel(value: string) {
  if (value === "cli_completed") return "загрузка завершена";
  if (value === "user_cancelled") return "остановлено пользователем";
  if (value === "size_limit_reached") return "достигнут лимит размера";
  if (value === "cli_pack_failed") return "ошибка упаковки";
  return value || "не указано";
}
