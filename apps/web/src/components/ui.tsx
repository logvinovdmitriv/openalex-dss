import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import type { CellContext } from "@tanstack/react-table";
import { CheckCircle2, Download, ListFilter } from "lucide-react";
import type { TableColumnFilter, TableColumnFilters, TableColumnSchema, TableResponse } from "../api";
import { columnLabel, countryLabel, fmt, languageLabel, modeLabel, metricLabel, sourceTypeLabel, workTypeLabel } from "../domain";

type DataGridSortDirection = "asc" | "desc";
type DataGridSortChange = (field: string, direction: DataGridSortDirection | "") => void;

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div className="field"><span>{label}</span>{children}</div>;
}

export function JsonPanel({ title, value }: { title: string; value: unknown }) {
  return (
    <section className="panel json-panel">
      <h2>{title}</h2>
      <pre>{JSON.stringify(value ?? {}, null, 2)}</pre>
    </section>
  );
}

export function DownloadLink({ href, label, compact = false }: { href: string; label: string; compact?: boolean }) {
  return <a className={compact ? "download-action compact" : "download-action"} href={href}><Download size={15} /> {label}</a>;
}

export function MetricCard({ label, value }: { label: string; value: string | number }) {
  return <div className="metric-card"><span>{label}</span><b>{value}</b></div>;
}

export function KeyValue({ label, value }: { label: string; value: string }) {
  return <div className="key-value"><span>{label}</span><b>{value || "не задано"}</b></div>;
}

export function CheckPill({ active, label }: { active: boolean; label: string }) {
  return <span className={active ? "check-pill active" : "check-pill"}>{active && <CheckCircle2 size={14} />}{label}</span>;
}

export function DataGrid({
  data,
  onSelect,
  compact = false,
  hiddenFields = [],
  selectableRows = false,
  selectedIds = [],
  selectionField = "author_id",
  onSelectedIdsChange,
  sortField,
  sortDirection = "desc",
  onSortChange,
  enableColumnFilters = false,
  columnFilters,
  onColumnFiltersChange,
  columnSchema = [],
  fieldLabels = {},
}: {
  data?: TableResponse;
  onSelect: (v: { kind: "author" | "work"; id: string }) => void;
  compact?: boolean;
  hiddenFields?: string[];
  selectableRows?: boolean;
  selectedIds?: string[];
  selectionField?: string;
  onSelectedIdsChange?: (ids: string[]) => void;
  sortField?: string;
  sortDirection?: DataGridSortDirection;
  onSortChange?: DataGridSortChange;
  enableColumnFilters?: boolean;
  columnFilters?: TableColumnFilters;
  onColumnFiltersChange?: (value: TableColumnFilters) => void;
  columnSchema?: TableColumnSchema[];
  fieldLabels?: Record<string, string>;
}) {
  const [openColumn, setOpenColumn] = useState<string | null>(null);
  const [columnMenuPosition, setColumnMenuPosition] = useState<ColumnMenuPosition | null>(null);
  const columnMenuRef = useRef<HTMLDivElement | null>(null);
  const fields = (data?.fields ?? []).filter((field) => !hiddenFields.includes(field));
  const columnSchemaByField = useMemo(() => new Map(columnSchema.map((column) => [column.field, column])), [columnSchema]);
  const rows = data?.rows ?? [];
  const selectedSet = useMemo(() => new Set(selectedIds.map(String)), [selectedIds.join("|")]);
  const effectiveColumnFilters = columnFilters ?? {};
  const backendSorting = Boolean(onSortChange);
  const backendFiltering = Boolean(onColumnFiltersChange);
  const activeSortField = backendSorting ? sortField : "";
  const activeSortDirection: DataGridSortDirection | "" = onSortChange
    ? (sortField ? sortDirection : "")
    : "";
  const controlledSorting = backendSorting && sortField ? [{ id: sortField, desc: sortDirection !== "asc" }] : [];
  const setColumnFilters = onColumnFiltersChange;
  const setColumnFilter = (field: string, patch: TableColumnFilter) => {
    if (!setColumnFilters) return;
    const current = effectiveColumnFilters[field] ?? {};
    const nextFilter = cleanColumnFilter({ ...current, ...patch });
    const next = { ...effectiveColumnFilters };
    if (Object.keys(nextFilter).length) next[field] = nextFilter;
    else delete next[field];
    setColumnFilters(next);
  };
  const resetColumnFilter = (field: string) => {
    if (!setColumnFilters) return;
    const next = { ...effectiveColumnFilters };
    delete next[field];
    setColumnFilters(next);
  };
  const closeColumnMenu = () => {
    setOpenColumn(null);
    setColumnMenuPosition(null);
  };
  const toggleColumnMenu = (field: string, rect: DOMRect) => {
    if (openColumn === field) {
      closeColumnMenu();
      return;
    }
    setOpenColumn(field);
    setColumnMenuPosition(columnMenuPositionFromRect(rect));
  };
  const applySort = (field: string, direction: DataGridSortDirection | "") => {
    if (onSortChange) onSortChange(field, direction);
    closeColumnMenu();
  };
  const toggleSort = (field: string) => {
    if (activeSortField !== field) {
      applySort(field, "desc");
      return;
    }
    if (activeSortDirection === "desc") {
      applySort(field, "asc");
      return;
    }
    applySort("", "");
  };
  useEffect(() => {
    if (!openColumn) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (columnMenuRef.current?.contains(target)) return;
      if ((target as HTMLElement).closest?.(".table-sort-button, .column-filter-button")) return;
      closeColumnMenu();
    };
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") closeColumnMenu();
    };
    const onViewportChange = () => closeColumnMenu();
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", onViewportChange);
    window.addEventListener("scroll", onViewportChange, true);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onViewportChange);
      window.removeEventListener("scroll", onViewportChange, true);
    };
  }, [openColumn]);
  const columns = useMemo(() => fields.map((field) => ({
    accessorKey: field,
    header: fieldLabels[field] ?? columnLabel(field),
    cell: (info: CellContext<Record<string, unknown>, unknown>) => renderCell(field, info.getValue(), onSelect, info.row.original),
  })), [fields, hiddenFields, onSelect, JSON.stringify(fieldLabels)]);
  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting: controlledSorting },
    manualSorting: Boolean(onSortChange),
    getCoreRowModel: getCoreRowModel(),
  });
  if (!fields.length) {
    return <EmptyState title="Нет данных для отображения" detail="Проверьте выбранный источник, фильтр или состояние пайплайна." />;
  }
  const visibleRows = table.getRowModel().rows;
  const visibleSelectionIds = selectableRows
    ? visibleRows.map((row) => rowSelectionId(row.original, selectionField)).filter(Boolean)
    : [];
  const allVisibleSelected = visibleSelectionIds.length > 0 && visibleSelectionIds.every((id) => selectedSet.has(id));
  const toggleVisibleRows = () => {
    if (!onSelectedIdsChange) return;
    const next = new Set(selectedSet);
    if (allVisibleSelected) visibleSelectionIds.forEach((id) => next.delete(id));
    else visibleSelectionIds.forEach((id) => next.add(id));
    onSelectedIdsChange([...next]);
  };
  const toggleRow = (id: string) => {
    if (!onSelectedIdsChange || !id) return;
    const next = new Set(selectedSet);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onSelectedIdsChange([...next]);
  };
  return (
    <div className={compact ? "table-wrap compact" : "table-wrap"}>
      <table>
        <thead>{table.getHeaderGroups().map((hg) => (
          <tr key={hg.id}>
            {selectableRows && (
              <th className="select-column">
                <input
                  type="checkbox"
                  aria-label={allVisibleSelected ? "Снять выделение с показанных строк" : "Выделить показанные строки"}
                  checked={allVisibleSelected}
                  disabled={!visibleSelectionIds.length}
                  onChange={toggleVisibleRows}
                />
              </th>
            )}
            {hg.headers.map((h) => {
              const field = String(h.column.id);
              const schema = columnSchemaByField.get(field);
              const active = hasColumnFilter(effectiveColumnFilters[field]) || activeSortField === field;
              const sortable = backendSorting && schema?.sortable === true;
              const filterable = enableColumnFilters && backendFiltering && schema?.filterable === true;
              return (
              <th key={h.id} className={active ? "column-active" : undefined}>
                <div className="table-header-controls">
                  <button type="button" className="table-sort-button" disabled={!sortable} onClick={() => toggleSort(field)} aria-label={sortable ? `Сортировать столбец ${String(h.column.columnDef.header)}` : `Столбец ${String(h.column.columnDef.header)} не сортируется`}>
                    <span>{flexRender(h.column.columnDef.header, h.getContext())}</span>
                    {sortable && <SortMark value={activeSortField === field && activeSortDirection ? activeSortDirection : false} />}
                  </button>
                  {filterable && (
                    <button type="button" className="column-filter-button" onClick={(event) => toggleColumnMenu(field, event.currentTarget.getBoundingClientRect())} aria-label={`Фильтр столбца ${String(h.column.columnDef.header)}`}>
                      <ListFilter size={14} />
                      {hasColumnFilter(effectiveColumnFilters[String(h.column.id)]) && <span className="filter-mark" aria-label="Есть ограничение" />}
                    </button>
                  )}
                </div>
                {openColumn === String(h.column.id) && (
                  <ColumnMenu
                    menuRef={columnMenuRef}
                    field={String(h.column.id)}
                    label={String(h.column.columnDef.header)}
                    description={schema?.description ?? ""}
                    filter={effectiveColumnFilters[String(h.column.id)] ?? {}}
                    type={schema?.type ?? (rows.some((row) => isFiniteTableNumber((row as Record<string, unknown>)[String(h.column.id)])) ? "number" : "text")}
                    enableFilters={filterable}
                    position={columnMenuPosition}
                    onSort={applySort}
                    onFilter={setColumnFilter}
                    onReset={resetColumnFilter}
                    onClose={closeColumnMenu}
                  />
                )}
              </th>
            );
            })}
          </tr>
        ))}</thead>
        <tbody>
          {visibleRows.map((row) => {
            const id = rowSelectionId(row.original, selectionField);
            const checked = Boolean(id && selectedSet.has(id));
            return (
              <tr key={row.id} className={checked ? "row-selected" : undefined}>
                {selectableRows && (
                  <td className="select-column">
                    <input
                      type="checkbox"
                      aria-label={checked ? "Снять автора из выборки" : "Добавить автора в выборку"}
                      checked={checked}
                      disabled={!id}
                      onChange={() => toggleRow(id)}
                    />
                  </td>
                )}
                {row.getVisibleCells().map((cell) => <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}
              </tr>
            );
          })}
          {visibleRows.length === 0 && <tr><td colSpan={fields.length + (selectableRows ? 1 : 0)}>По текущему фильтру строк нет.</td></tr>}
        </tbody>
      </table>
      <p className="muted">Показано: {fmt(visibleRows.length)} из {fmt(data?.total ?? rows.length)}. Сортировка и ограничения выполняются на сервере по всему выбранному срезу.</p>
    </div>
  );
}

function rowSelectionId(row: Record<string, unknown>, field: string) {
  return String(row[field] ?? row.author_id ?? "").trim();
}

type ColumnMenuPosition = {
  left: number;
  top: number;
  width: number;
  maxHeight: number;
  placement: "top" | "bottom";
};

function columnMenuPositionFromRect(rect: DOMRect): ColumnMenuPosition {
  const gutter = 12;
  const width = Math.min(280, window.innerWidth - gutter * 2);
  const left = clampNumber(rect.left, gutter, Math.max(gutter, window.innerWidth - width - gutter));
  const spaceBelow = window.innerHeight - rect.bottom - gutter;
  const spaceAbove = rect.top - gutter;
  const placement: "top" | "bottom" = spaceBelow < 280 && spaceAbove > spaceBelow ? "top" : "bottom";
  const availableHeight = Math.max(180, placement === "bottom" ? spaceBelow - 8 : spaceAbove - 8);
  return {
    left,
    top: placement === "bottom" ? rect.bottom + 6 : rect.top - 6,
    width,
    maxHeight: Math.min(380, availableHeight),
    placement,
  };
}

function clampNumber(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function ColumnMenu({
  menuRef,
  field,
  label,
  description,
  filter,
  type,
  enableFilters,
  position,
  onSort,
  onFilter,
  onReset,
  onClose,
}: {
  menuRef: RefObject<HTMLDivElement | null>;
  field: string;
  label: string;
  description: string;
  filter: TableColumnFilter;
  type: string;
  enableFilters: boolean;
  position: ColumnMenuPosition | null;
  onSort: DataGridSortChange;
  onFilter: (field: string, patch: TableColumnFilter) => void;
  onReset: (field: string) => void;
  onClose: () => void;
}) {
  const style: CSSProperties = position
    ? { left: position.left, top: position.top, width: position.width, maxHeight: position.maxHeight }
    : {};
  return createPortal(
    <div ref={menuRef} className={`column-menu ${position?.placement ?? "bottom"}`} style={style} role="dialog" aria-label={`Настройка столбца ${label}`}>
      <div className="column-menu-head">
        <div>
          <b>{label}</b>
          {description && <small>{description}</small>}
        </div>
        <button type="button" className="icon-mini" onClick={onClose} aria-label="Закрыть">×</button>
      </div>
      <button type="button" onClick={() => onSort(field, "asc")}>По возрастанию</button>
      <button type="button" onClick={() => onSort(field, "desc")}>По убыванию</button>
      <button type="button" onClick={() => onSort("", "")}>Без сортировки</button>
      {enableFilters && (
        <div className="column-filter-form">
          {type === "number" ? (
            <>
              <label>
                <span>От</span>
                <input inputMode="decimal" value={filter.min ?? ""} onChange={(event) => onFilter(field, { min: event.target.value })} />
              </label>
              <label>
                <span>До</span>
                <input inputMode="decimal" value={filter.max ?? ""} onChange={(event) => onFilter(field, { max: event.target.value })} />
              </label>
            </>
          ) : (
            <label>
              <span>Содержит</span>
              <input value={filter.contains ?? ""} onChange={(event) => onFilter(field, { contains: event.target.value })} />
            </label>
          )}
          {hasColumnFilter(filter) && <button type="button" className="ghost-button" onClick={() => onReset(field)}>Сбросить столбец</button>}
        </div>
      )}
    </div>,
    document.body,
  );
}

export function DetailDrawer({ selected, onClose, detail }: { selected: { kind: "author" | "work"; id: string }; onClose: () => void; detail: unknown }) {
  const title = selected.kind === "author" ? "Автор" : "Работа";
  return (
    <aside className="drawer">
      <div className="drawer-head"><h2>{title}: {selected.id}</h2><button onClick={onClose}>Закрыть</button></div>
      <pre>{JSON.stringify(detail ?? {}, null, 2)}</pre>
    </aside>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><b>{title}</b><span>{detail}</span></div>;
}

function renderCell(field: string, value: unknown, onSelect: (v: { kind: "author" | "work"; id: string }) => void, row: Record<string, unknown>) {
  const text = String(value ?? "");
  if (field === "author_id" && text) return <button className="link" onClick={() => onSelect({ kind: "author", id: text })}>{text}</button>;
  if (field === "work_id" && text) return <button className="link" onClick={() => onSelect({ kind: "work", id: text })}>{text}</button>;
  if (field === "author_display_name" && text && row.author_id) return <button className="link" onClick={() => onSelect({ kind: "author", id: String(row.author_id) })}>{text}</button>;
  const interpreted = interpretedCellValue(field, value);
  if (interpreted !== null) return <span title={text}>{interpreted}</span>;
  const numeric = Number(value);
  if (text && Number.isFinite(numeric) && !field.endsWith("_year") && field !== "author_seq") {
    return <span title={text}>{fmt(numeric)}</span>;
  }
  return <span title={text}>{text.length > 72 ? `${text.slice(0, 71)}...` : text}</span>;
}

function interpretedCellValue(field: string, value: unknown) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  if (field === "fraction_mode") return modeLabel(text);
  if (field === "metric_name" || field === "rank_metric" || field.endsWith("_metric")) return metricLabel(text);
  if (field === "type" || field === "work_type") return workTypeLabel(text);
  if (field === "source_type") return sourceTypeLabel(text);
  if (field === "language") return languageLabel(text);
  if (field === "country_code" || field === "author_country_code" || field === "country_codes_csv") return formatCountryCodes(text);
  if (field === "open_access_is_oa" || field === "has_abstract" || field === "is_primary" || field.endsWith("_flag") || field.startsWith("qf_")) return booleanLabel(value);
  return null;
}

function formatCountryCodes(value: string) {
  const parts = value.split("|").map((item) => item.trim()).filter(Boolean);
  if (!parts.length) return value;
  return parts.map(countryLabel).join(", ");
}

function booleanLabel(value: unknown) {
  const raw = String(value ?? "").trim().toLowerCase();
  if (["1", "true", "yes", "y"].includes(raw)) return "Да";
  if (["0", "false", "no", "n"].includes(raw)) return "Нет";
  return String(value ?? "");
}

function SortMark({ value }: { value: false | "asc" | "desc" }) {
  return <span className="sort-mark" aria-hidden="true">{value === "asc" ? "↑" : value === "desc" ? "↓" : "↕"}</span>;
}

function cleanColumnFilter(filter: TableColumnFilter): TableColumnFilter {
  const next: TableColumnFilter = {};
  const contains = String(filter.contains ?? "").trim();
  const min = String(filter.min ?? "").trim();
  const max = String(filter.max ?? "").trim();
  if (contains) next.contains = contains;
  if (min) next.min = min;
  if (max) next.max = max;
  return next;
}

function hasColumnFilter(filter: TableColumnFilter | undefined) {
  if (!filter) return false;
  return Boolean(String(filter.contains ?? "").trim() || String(filter.min ?? "").trim() || String(filter.max ?? "").trim());
}

function isFiniteTableNumber(value: unknown) {
  return Number.isFinite(tableNumber(value));
}

function tableNumber(value: unknown) {
  if (typeof value === "number") return value;
  if (typeof value === "string" && value.trim()) return Number(value.trim().replace(",", "."));
  return Number.NaN;
}
