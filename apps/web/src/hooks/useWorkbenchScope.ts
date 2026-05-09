import { useMemo } from "react";

import { effectiveUiScope, type WorkbenchActiveContext } from "../workbench";

export function useWorkbenchScope(params: {
  runId: string;
  dumpId: string;
  activeContext?: WorkbenchActiveContext | null;
}) {
  return useMemo(
    () => effectiveUiScope({ runId: params.runId, dumpId: params.dumpId, activeContext: params.activeContext }),
    [params.runId, params.dumpId, params.activeContext],
  );
}
