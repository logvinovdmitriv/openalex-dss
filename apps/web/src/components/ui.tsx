import { useMemo, useState, type ReactNode } from "react";
import { flexRender, getCoreRowModel, getSortedRowModel, useReactTable } from "@tanstack/react-table";
import type { CellContext, SortingState } from "@tanstack/react-table";
import type { TableColumnFilter, TableColumnFilters, TableResponse } from "../api";
import { columnLabel, countryLabel, fmt, languageLabel, modeLabel, metricLabel, sourceTypeLabel, workTypeLabel } from "../domain";

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
  sortDirection?: "asc" | "desc";
  onSortChange?: (field: string, direction: "asc" | "desc") => void;
  enableColumnFilters?: boolean;
  columnFilters?: TableColumnFilters;
  onColumnFiltersChange?: (value: TableColumnFilters) => void;
  fieldLabels?: Record<string, string>;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [localColumnFilters, setLocalColumnFilters] = useState<TableColumnFilters>({});
  const [openColumn, setOpenColumn] = useState<string | null>(null);
  const fields = (data?.fields ?? []).filter((field) => !hiddenFields.includes(field));
  const rows = data?.rows ?? [];
  const selectedSet = useMemo(() => new Set(selectedIds.map(String)), [selectedIds.join("|")]);
  const effectiveColumnFilters = columnFilters ?? localColumnFilters;
  const filteredRows = useMemo(() => rows.filter((row) => rowMatchesColumnFilters(row as Record<string, unknown>, effectiveColumnFilters)), [rows, effectiveColumnFilters]);
  const controlledSorting = sortField ? [{ id: sortField, desc: sortDirection !== "asc" }] : sorting;
  const setColumnFilters = onColumnFiltersChange ?? setLocalColumnFilters;
  const setColumnFilter = (field: string, patch: TableColumnFilter) => {
    const current = effectiveColumnFilters[field] ?? {};
    const nextFilter = cleanColumnFilter({ ...current, ...patch });
    const next = { ...effectiveColumnFilters };
    if (Object.keys(nextFilter).length) next[field] = nextFilter;
    else delete next[field];
    setColumnFilters(next);
  };
  const resetColumnFilter = (field: string) => {
    const next = { ...effectiveColumnFilters };
    delete next[field];
    setColumnFilters(next);
  };
  const applySort = (field: string, direction: "asc" | "desc") => {
    if (onSortChange) onSortChange(field, direction);
    else setSorting([{ id: field, desc: direction === "desc" }]);
    setOpenColumn(null);
  };
  const columns = useMemo(() => fields.map((field) => ({
    accessorKey: field,
    header: fieldLabels[field] ?? columnLabel(field),
    sortingFn: (rowA: any, rowB: any, columnId: string) => compareSortValues(rowA.original?.[columnId], rowB.original?.[columnId]),
    cell: (info: CellContext<Record<string, unknown>, unknown>) => renderCell(field, info.getValue(), onSelect, info.row.original),
  })), [fields, hiddenFields, onSelect, JSON.stringify(fieldLabels)]);
  const table = useReactTable({
    data: filteredRows,
    columns,
    state: { sorting: controlledSorting },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
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
              const active = hasColumnFilter(effectiveColumnFilters[field]) || sortField === field;
              return (
              <th key={h.id} className={active ? "column-active" : undefined}>
                <button type="button" className="table-sort-button" onClick={() => setOpenColumn(openColumn === String(h.column.id) ? null : String(h.column.id))} aria-label={`Настроить столбец ${String(h.column.columnDef.header)}`}>
                  <span>{flexRender(h.column.columnDef.header, h.getContext())}</span>
                  <SortMark value={h.column.getIsSorted()} />
                  {hasColumnFilter(effectiveColumnFilters[String(h.column.id)]) && <span className="filter-mark" aria-label="Есть ограничение">●</span>}
                </button>
                {openColumn === String(h.column.id) && (
                  <ColumnMenu
                    field={String(h.column.id)}
                    label={String(h.column.columnDef.header)}
                    filter={effectiveColumnFilters[String(h.column.id)] ?? {}}
                    numeric={rows.some((row) => isFiniteTableNumber((row as Record<string, unknown>)[String(h.column.id)]))}
                    enableFilters={enableColumnFilters}
                    onSort={applySort}
                    onFilter={setColumnFilter}
                    onReset={resetColumnFilter}
                    onClose={() => setOpenColumn(null)}
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
      <p className="muted">Показано: {fmt(visibleRows.length)} из {fmt(data?.total ?? rows.length)}. Нажмите на заголовок столбца, чтобы выбрать сортировку{enableColumnFilters ? " или ограничение" : ""}.</p>
    </div>
  );
}

function rowSelectionId(row: Record<string, unknown>, field: string) {
  return String(row[field] ?? row.author_id ?? "").trim();
}

function ColumnMenu({
  field,
  label,
  filter,
  numeric,
  enableFilters,
  onSort,
  onFilter,
  onReset,
  onClose,
}: {
  field: string;
  label: string;
  filter: TableColumnFilter;
  numeric: boolean;
  enableFilters: boolean;
  onSort: (field: string, direction: "asc" | "desc") => void;
  onFilter: (field: string, patch: TableColumnFilter) => void;
  onReset: (field: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="column-menu" role="dialog" aria-label={`Настройка столбца ${label}`}>
      <div className="column-menu-head">
        <b>{label}</b>
        <button type="button" className="icon-mini" onClick={onClose} aria-label="Закрыть">×</button>
      </div>
      <button type="button" onClick={() => onSort(field, "asc")}>По возрастанию</button>
      <button type="button" onClick={() => onSort(field, "desc")}>По убыванию</button>
      {enableFilters && (
        <div className="column-filter-form">
          {numeric ? (
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
    </div>
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

function rowMatchesColumnFilters(row: Record<string, unknown>, filters: TableColumnFilters) {
  return Object.entries(filters).every(([field, filter]) => {
    const contains = String(filter.contains ?? "").trim().toLowerCase();
    if (contains && !textIncludes(row[field], contains)) return false;
    const minText = String(filter.min ?? "").trim().replace(",", ".");
    const maxText = String(filter.max ?? "").trim().replace(",", ".");
    if (!minText && !maxText) return true;
    const value = tableNumber(row[field]);
    if (!Number.isFinite(value)) return false;
    const min = minText ? Number(minText) : Number.NEGATIVE_INFINITY;
    const max = maxText ? Number(maxText) : Number.POSITIVE_INFINITY;
    if (Number.isFinite(min) && value < min) return false;
    if (Number.isFinite(max) && value > max) return false;
    return true;
  });
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

function textIncludes(value: unknown, normalizedQuery: string) {
  return String(value ?? "").toLowerCase().includes(normalizedQuery);
}

function isFiniteTableNumber(value: unknown) {
  return Number.isFinite(tableNumber(value));
}

function tableNumber(value: unknown) {
  if (typeof value === "number") return value;
  if (typeof value === "string" && value.trim()) return Number(value.trim().replace(",", "."));
  return Number.NaN;
}

function compareSortValues(left: unknown, right: unknown) {
  const leftNumber = typeof left === "number" ? left : Number(String(left ?? "").replace(",", "."));
  const rightNumber = typeof right === "number" ? right : Number(String(right ?? "").replace(",", "."));
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) return leftNumber - rightNumber;
  return String(left ?? "").localeCompare(String(right ?? ""), "ru", { numeric: true, sensitivity: "base" });
}
