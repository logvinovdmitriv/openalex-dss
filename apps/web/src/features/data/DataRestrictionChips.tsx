import type { TableColumnFilters } from "../../api";
import { columnLabel, fmt } from "../../domain";

export function DataRestrictionChips({
  filters,
  sortField,
  sortDirection,
  search,
  selectedAuthorIds,
  limit,
  onResetSearch,
  onRemoveFilter,
  onResetSort,
}: {
  filters: TableColumnFilters;
  sortField: string;
  sortDirection: "asc" | "desc";
  search: string;
  selectedAuthorIds: string[];
  limit: number;
  onResetSearch: () => void;
  onRemoveFilter: (field: string) => void;
  onResetSort: () => void;
}) {
  const filterEntries = Object.entries(filters);
  const hasSearch = Boolean(search.trim());
  const hasSelectedAuthors = selectedAuthorIds.length > 0;
  if (!filterEntries.length && !sortField && !hasSearch && !hasSelectedAuthors) {
    return (
      <div className="selection-summary">
        <span>Ограничений по столбцам нет</span>
        <span>{limitLabel(limit)}</span>
      </div>
    );
  }
  return (
    <div className="selection-summary active" aria-live="polite">
      <b>Активная выборка</b>
      {sortField && (
        <button type="button" className="selection-chip" onClick={onResetSort}>
          Сортировка: {columnLabel(sortField)} {sortDirection === "asc" ? "по возрастанию" : "по убыванию"} ×
        </button>
      )}
      {hasSearch && (
        <button type="button" className="selection-chip" onClick={onResetSearch}>
          Поиск: “{search.trim()}” ×
        </button>
      )}
      {hasSelectedAuthors && <span className="selection-chip passive">Точки на графиках: {fmt(selectedAuthorIds.length)}</span>}
      {filterEntries.map(([field, filter]) => (
        <button key={field} type="button" className="selection-chip" onClick={() => onRemoveFilter(field)}>
          {columnLabel(field)}: {columnFilterSummary(filter)} ×
        </button>
      ))}
      <span>{limit > 0 ? `${limitLabel(limit)} после сортировки и ограничений` : "Берутся все строки после сортировки и ограничений"}</span>
    </div>
  );
}

function columnFilterSummary(filter: { contains?: string; min?: string; max?: string }) {
  const parts: string[] = [];
  if (filter.contains) parts.push(`содержит “${filter.contains}”`);
  if (filter.min) parts.push(`от ${filter.min}`);
  if (filter.max) parts.push(`до ${filter.max}`);
  return parts.join(", ") || "ограничение";
}

function limitLabel(limit: number) {
  return Number(limit) > 0 ? `Берется до ${fmt(limit)} строк` : "Берутся все строки";
}

