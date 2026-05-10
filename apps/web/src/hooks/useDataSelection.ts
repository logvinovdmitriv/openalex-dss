import { useMemo } from "react";

import type { TableColumnFilters } from "../api";
import type { LocalDataKind } from "../workbench";

export function useDataSelection(params: {
  kind?: LocalDataKind;
  filters: TableColumnFilters;
  search: string;
  sort: string;
  direction: "asc" | "desc";
  limit: number;
  authorIds?: string[];
}) {
  return useMemo(
    () => ({
      kind: params.kind,
      filters: params.filters,
      search: params.search,
      sort: params.sort,
      direction: params.direction,
      limit: params.limit,
      authorIds: params.authorIds ?? [],
    }),
    [params.kind, params.filters, params.search, params.sort, params.direction, params.limit, params.authorIds],
  );
}
