import { useMemo } from "react";

import type { TableColumnFilters } from "../api";

export function useDataSelection(params: {
  filters: TableColumnFilters;
  search: string;
  sort: string;
  direction: "asc" | "desc";
  limit: number;
  authorIds?: string[];
}) {
  return useMemo(
    () => ({
      filters: params.filters,
      search: params.search,
      sort: params.sort,
      direction: params.direction,
      limit: params.limit,
      authorIds: params.authorIds ?? [],
    }),
    [params.filters, params.search, params.sort, params.direction, params.limit, params.authorIds],
  );
}
