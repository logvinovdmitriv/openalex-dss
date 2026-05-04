import { useMemo } from "react";
import { flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import type { CellContext } from "@tanstack/react-table";
import type { TableResponse } from "../api";
import { columnLabel, fmt } from "../domain";

export function DataGrid({ data, onSelect, compact = false, hiddenFields = [] }: { data?: TableResponse; onSelect: (v: { kind: "author" | "work"; id: string }) => void; compact?: boolean; hiddenFields?: string[] }) {
  const fields = (data?.fields ?? []).filter((field) => !hiddenFields.includes(field));
  const rows = data?.rows ?? [];
  const columns = useMemo(() => fields.map((field) => ({
    accessorKey: field,
    header: columnLabel(field),
    cell: (info: CellContext<Record<string, unknown>, unknown>) => renderCell(field, info.getValue(), onSelect, info.row.original),
  })), [fields, hiddenFields, onSelect]);
  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() });
  if (!fields.length) {
    return <EmptyState title="Нет данных для отображения" detail="Проверьте выбранный источник, фильтр или состояние пайплайна." />;
  }
  return (
    <div className={compact ? "table-wrap compact" : "table-wrap"}>
      <table>
        <thead>{table.getHeaderGroups().map((hg) => <tr key={hg.id}>{hg.headers.map((h) => <th key={h.id}>{flexRender(h.column.columnDef.header, h.getContext())}</th>)}</tr>)}</thead>
        <tbody>{table.getRowModel().rows.map((row) => <tr key={row.id}>{row.getVisibleCells().map((cell) => <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}</tr>)}</tbody>
      </table>
      <p className="muted">Строк: {fmt(data?.total ?? 0)}</p>
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
  const numeric = Number(value);
  if (text && Number.isFinite(numeric) && !field.endsWith("_year") && field !== "author_seq") {
    return <span title={text}>{fmt(numeric)}</span>;
  }
  return <span title={text}>{text.length > 72 ? `${text.slice(0, 71)}...` : text}</span>;
}
