import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  CheckCircle2,
  Database,
  Gauge,
  Lock,
  Loader2,
  Search,
  Settings2,
  UploadCloud,
  X,
} from "lucide-react";
import { API_BASE, deleteJson, getJson, postJson, type CustomMetricDefinition, type TableColumnFilters, type TableResponse, type TableSchemaResponse } from "./api";
import {
  DEFAULT_FILTERS,
  CORE_METRIC_OPTIONS,
  FRACTION_MODE_OPTIONS,
  countryLabel,
  filterParams,
  fmt,
  resolveCountryInput,
  workTypeLabel,
  type ActiveFilters,
  type OrganizationPreset,
  type ResearchAreaPreset,
  type SelectOption,
} from "./domain";
import { CheckPill, DetailDrawer, EmptyState, Field, KeyValue, MetricCard } from "./components/ui";
import { ProgressPanel, RunCard, runActionTitle, runCompletedTitle } from "./components/JobProgress";
import { useDataSelection } from "./hooks/useDataSelection";
import { useWorkbenchScope } from "./hooks/useWorkbenchScope";
import {
  analyticsRankingUrl,
  buildAnalysisRunPayload,
  buildDownloadPolicy,
  buildSliceDefinitionPayload,
  filtersFromSlicePayload,
  humanSliceTitle,
  localDataPreviewCsvUrl,
  localDataPreviewUrl,
  localDataSchemaUrl,
  localDataSummaryUrl,
  mutationError,
  pageLead,
  pageTitle,
  scientometricsUrl,
  dataSelectionQuery,
  customMetricDefsQuery,
  customMetricModelsUrl,
  sliceSubjectTitle,
  viewFromHash,
  type CatalogPayload,
  type EntitySuggestion,
  type EstimatePayload,
  type LocalDataKind,
  type LocalDataSummary,
  type MaterializationPlanPayload,
  type RateLimitPayload,
  type RegistryPayload,
  type ResolverTab,
  type ScientometricAnalysisPayload,
  type SliceDefinitionPayload,
  type View,
  type WorkbenchActiveContext,
  type WorkbenchDump,
  type WorkbenchRun,
  type WorkbenchSlice,
  type WorkbenchState,
} from "./workbench";
import { buildWorkflowNav, nextUnlockedNavIndex } from "./features/workflow/workflowNav";
import { StatusRail } from "./features/workflow/StatusRail";
import { DataView } from "./features/data/DataView";
import { AnalyticsView } from "./features/analytics/AnalyticsView";
import { IndicesView } from "./features/indices/IndicesView";
import { DownloadedSlicesPanel, DumpInfoModal } from "./features/slices/DownloadedSlices";
import { EstimateBudget, EstimateFacets, RateLimitPanel } from "./features/slices/EstimatePanels";
import { DEFAULT_CUSTOM_METRICS } from "./features/formulas/defaultCustomMetrics";
import { metricLabelMap as buildMetricLabelMap, rankingMetricOptions } from "./features/metrics/metricCatalog";
import { TOAST_EVENT, emitToast, type ToastItem, type ToastPayload } from "./features/notifications/toast";
import { ToastViewport } from "./features/notifications/ToastViewport";
import { ReportsPage } from "./features/reports/ReportsView";
import "./styles.css";

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error) => {
      const message = mutationError(error);
      emitToast({ title: "Данные не загрузились", message, tone: "error", key: `query-${message}` });
    },
  }),
  mutationCache: new MutationCache({
    onError: (error) => {
      const message = mutationError(error);
      emitToast({ title: "Действие не выполнено", message, tone: "error", key: `mutation-${message}` });
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 20_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const DATA_PREVIEW_PAGE_SIZE = 100;
const DATA_ONLY_ANALYSIS_FILTERS: ActiveFilters = {
  ...DEFAULT_FILTERS,
  filter_mode: "",
  from_publication_date: "",
  to_publication_date: "",
  affiliation_mode: "",
};
type ListPayload<T = Record<string, unknown>> = {
  results?: T[];
};
export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Workbench />
    </QueryClientProvider>
  );
}

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

function Workbench() {
  const qc = useQueryClient();
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [view, setView] = useState<View>(() => viewFromHash(window.location.hash));
  const [filters, setFilters] = useState<ActiveFilters>(DEFAULT_FILTERS);
  const [metric, setMetric] = useState("h");
  const [rankingDirection, setRankingDirection] = useState<"asc" | "desc">("desc");
  const [fractionMode, setFractionMode] = useState("strict_authors_count");
  const [dataOffset, setDataOffset] = useState(0);
  const [dataPageCursors, setDataPageCursors] = useState<Record<number, string>>({ 0: "" });
  const [customMetrics, setCustomMetrics] = useState<CustomMetricDefinition[]>(DEFAULT_CUSTOM_METRICS);
  const [scientometricMetrics, setScientometricMetrics] = useState<string[]>(["p", "c", "c_frac", "h", "i10", "g", "custom_added_rating"]);
  const [baselineMetric, setBaselineMetric] = useState("h");
  const [storageProfileId, setStorageProfileId] = useState("");
  const [downloadDir, setDownloadDir] = useState("");
  const [maxDownloadMb, setMaxDownloadMb] = useState("");
  const [dataSort, setDataSort] = useState("");
  const [dataDirection, setDataDirection] = useState<"asc" | "desc">("desc");
  const [dataSearch, setDataSearch] = useState("");
  const [selectedAuthorIds, setSelectedAuthorIds] = useState<string[]>([]);
  const [selectedAuthorRows, setSelectedAuthorRows] = useState<Record<string, unknown>[]>([]);
  const [sourceStrategy, setSourceStrategy] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [sliceDoc, setSliceDoc] = useState<WorkbenchSlice | null>(null);
  const [estimate, setEstimate] = useState<EstimatePayload | null>(null);
  const [materialization, setMaterialization] = useState<MaterializationPlanPayload | null>(null);
  const [runId, setRunId] = useState("");
  const [dumpId, setDumpId] = useState("");
  const [resolverOpen, setResolverOpen] = useState(false);
  const [selected, setSelected] = useState<{ kind: "author" | "work"; id: string } | null>(null);
  const [localDataKind, setLocalDataKind] = useState<LocalDataKind>("indices");
  const [dataColumnFilters, setDataColumnFilters] = useState<TableColumnFilters>({});
  const [dumpInfo, setDumpInfo] = useState<WorkbenchDump | null>(null);
  const navRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    const onHashChange = () => setView(viewFromHash(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    const onToast = (event: Event) => {
      const detail = (event as CustomEvent<ToastPayload>).detail;
      const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const next: ToastItem = { id, title: detail.title, message: detail.message, tone: detail.tone ?? "info", key: detail.key };
      setToasts((items) => {
        if (next.key && items.some((item) => item.key === next.key)) return items;
        return [next, ...items].slice(0, 4);
      });
      window.setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 7_000);
    };
    window.addEventListener(TOAST_EVENT, onToast);
    return () => window.removeEventListener(TOAST_EVENT, onToast);
  }, []);

  const navigate = (next: View) => {
    setView(next);
    window.history.replaceState(null, "", `#${next}`);
  };

  const registry = useQuery({ queryKey: ["registry"], queryFn: () => getJson<RegistryPayload>("/registry") });
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => getJson<CatalogPayload>("/catalog") });
  const workbench = useQuery({ queryKey: ["workbench"], queryFn: () => getJson<WorkbenchState>("/workbench") });
  const dumps = useQuery({
    queryKey: ["dumps"],
    queryFn: () => getJson<{ dumps?: WorkbenchDump[] }>("/dumps?limit=50"),
    refetchInterval: (query) => {
      const active = (query.state.data?.dumps ?? []).some((dump) => ["materializing", "downloading", "repairing", "partial"].includes(String(dump.status ?? "")));
      return active ? 5000 : 30000;
    },
    refetchOnWindowFocus: true,
  });
  const countries = useQuery({ queryKey: ["countries"], queryFn: () => getJson<ListPayload>("/openalex/countries?limit=50") });
  const workTypes = useQuery({ queryKey: ["work-types"], queryFn: () => getJson<ListPayload>("/openalex/work-types?limit=50") });
  const rateLimit = useQuery({
    queryKey: ["openalex-rate-limit", apiKey],
    queryFn: () => getJson<RateLimitPayload>(`/openalex/rate-limit?api_key=${encodeURIComponent(apiKey.trim())}`),
    enabled: Boolean(apiKey.trim()),
  });
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getJson<WorkbenchRun>(`/runs/${runId}`),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" || status === "cancelling" ? 1000 : false;
    },
  });
  const running = run.data?.status === "queued" || run.data?.status === "running" || run.data?.status === "cancelling";

  const notifiedRunRef = useRef("");
  useEffect(() => {
    const current = run.data;
    if (!current?.run_id || current.status === "queued" || current.status === "running") return;
    const key = `${current.run_id}:${current.status}:${current.error ?? ""}`;
    if (notifiedRunRef.current === key) return;
    notifiedRunRef.current = key;
    if (current.status === "failed") {
      emitToast({ title: `${runActionTitle(current.action)} завершился ошибкой`, message: String(current.error || "Проверьте параметры среза и журнал run."), tone: "error", key });
    } else if (current.status === "completed") {
      emitToast({ title: runCompletedTitle(current.action), message: "Локальные данные обновлены и доступны для выбора.", tone: "success", key });
    }
  }, [run.data?.run_id, run.data?.status, run.data?.error]);

  useEffect(() => {
    if (run.data?.status !== "completed") return;
    qc.invalidateQueries({ queryKey: ["workbench"] });
    qc.invalidateQueries({ queryKey: ["local-data-summary"] });
    qc.invalidateQueries({ queryKey: ["local-data-preview"] });
    qc.invalidateQueries({ queryKey: ["author-index-table"] });
    qc.invalidateQueries({ queryKey: ["analytics"] });
    qc.invalidateQueries({ queryKey: ["analytics-ranking"] });
    qc.invalidateQueries({ queryKey: ["scientometrics"] });
    qc.invalidateQueries({ queryKey: ["dumps"] });
  }, [qc, run.data?.run_id, run.data?.status]);
  const activeDumpId = dumpId || extractDumpId(run.data);
  const uiScope = useWorkbenchScope({
    runId,
    dumpId: activeDumpId,
    activeContext: workbench.data?.active_context,
  });
  const effectiveRunId = uiScope.runId;
  const effectiveDumpId = uiScope.dumpId;
  const usingActiveContextScope = uiScope.source === "active_context";
  const scopeReady = Boolean(effectiveRunId || effectiveDumpId);
  const savedMetricModels = useQuery({
    queryKey: ["custom-metric-models", effectiveRunId],
    queryFn: () => getJson<{ models: CustomMetricDefinition[] }>(customMetricModelsUrl(effectiveRunId)),
    enabled: Boolean(effectiveRunId),
    staleTime: 30_000,
  });
  useEffect(() => {
    const models = savedMetricModels.data?.models ?? [];
    if (models.length) setCustomMetrics(models);
    if (!models.length && effectiveRunId) setCustomMetrics(DEFAULT_CUSTOM_METRICS);
  }, [effectiveRunId, savedMetricModels.data?.models]);
  const dataFilterKey = useMemo(() => JSON.stringify(dataColumnFilters), [dataColumnFilters]);
  const debouncedDataSearch = useDebouncedValue(dataSearch, 250);
  const debouncedDataColumnFilters = useDebouncedValue(dataColumnFilters, 250);
  const debouncedDataFilterKey = useMemo(() => JSON.stringify(debouncedDataColumnFilters), [debouncedDataColumnFilters]);
  const customMetricKey = useMemo(() => JSON.stringify(customMetrics), [customMetrics]);
  const analysisFilters = useMemo(() => DATA_ONLY_ANALYSIS_FILTERS, []);
  const analysisDataSelection = useDataSelection({
    kind: localDataKind,
    filters: debouncedDataColumnFilters,
    search: debouncedDataSearch,
    sort: "",
    direction: "desc",
    limit: 0,
    authorIds: [],
  });
  const scientometricMetricKey = useMemo(() => scientometricMetrics.join(","), [scientometricMetrics]);
  const localDataSummary = useQuery({
    queryKey: ["local-data-summary", effectiveRunId, effectiveDumpId],
    queryFn: () => getJson<LocalDataSummary>(localDataSummaryUrl(effectiveRunId, effectiveDumpId)),
    enabled: scopeReady,
  });
  const localDataKindOptions = useMemo(() => {
    const tables = (localDataSummary.data?.tables ?? {}) as Partial<Record<LocalDataKind, Record<string, unknown>>>;
    return (localDataSummary.data?.kinds ?? [])
      .filter((item) => Boolean(tables[item.kind]?.exists))
      .map((item) => ({ value: item.kind, label: item.label }));
  }, [localDataSummary.data]);
  const localDataKindKey = localDataKindOptions.map((item) => item.value).join("|");
  const localDataKindAvailable = localDataKindOptions.some((item) => item.value === localDataKind);
  const hasAvailableLocalTables = localDataKindOptions.length > 0;
  const hasAuthorIndices = Boolean(localDataSummary.data?.tables?.indices?.exists);
  const hasLocalAnalyticsData = scopeReady && hasAuthorIndices;
  const dataViewActive = view === "data";
  const rankingsViewActive = view === "rankings";
  const analyticsViewActive = view === "statistics";
  const workflowNav = useMemo(() => buildWorkflowNav({
    view,
    scopeReady,
    hasAvailableLocalTables,
    hasAuthorIndices,
    running,
  }), [view, scopeReady, hasAvailableLocalTables, hasAuthorIndices, running]);
  const guardedNavigate = (next: View) => {
    const step = workflowNav.find((item) => item.id === next);
    if (step && !step.unlocked) {
      emitToast({ title: "Шаг пока недоступен", message: step.reason, tone: "info", key: `locked-${step.id}` });
      navigate(step.fallback);
      return;
    }
    navigate(next);
  };
  const onNavKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const current = workflowNav.findIndex((item) => item.id === view);
    if (current < 0) return;
    const nextIndex = nextUnlockedNavIndex(workflowNav, current, event.key);
    if (nextIndex === undefined) return;
    event.preventDefault();
    const next = workflowNav[nextIndex].id;
    guardedNavigate(next);
    navRefs.current[nextIndex]?.focus();
  };
  useEffect(() => {
    if (!workbench.isFetched && !workbench.isError) return;
    const current = workflowNav.find((item) => item.id === view);
    if (current && !current.unlocked) navigate(current.fallback);
  }, [workbench.isFetched, workbench.isError, workflowNav.map((item) => `${item.id}:${item.unlocked}`).join("|"), view]);
  useEffect(() => {
    setDataOffset(0);
    setDataPageCursors({ 0: "" });
  }, [localDataKind, dataSearch, dataFilterKey, dataSort, dataDirection, fractionMode, effectiveRunId, effectiveDumpId]);
  useEffect(() => {
    const selected = new Set(selectedAuthorIds.map(String));
    setSelectedAuthorRows((rows) => rows.filter((row) => selected.has(String(row.author_id ?? ""))));
  }, [selectedAuthorIds.join("|")]);
  const effectiveDataOffset = dataOffset;
  const effectiveDataCursor = dataPageCursors[effectiveDataOffset] ?? "";
  const dataPreviewLimit = DATA_PREVIEW_PAGE_SIZE;
  const previewPageKey = `${effectiveDataOffset}:${dataPreviewLimit}:${effectiveDataCursor}`;
  const rankingPreviewLimit = DATA_PREVIEW_PAGE_SIZE;
  const analysisRankTopN = 0;
  const table = useQuery({
    queryKey: ["local-data-preview", localDataKind, debouncedDataSearch, debouncedDataFilterKey, dataSort, dataDirection, fractionMode, effectiveRunId, effectiveDumpId, previewPageKey],
    queryFn: ({ signal }) => getJson<TableResponse>(localDataPreviewUrl(localDataKind, { q: debouncedDataSearch, runId: effectiveRunId, dumpId: effectiveDumpId, limit: dataPreviewLimit, offset: effectiveDataOffset, cursor: effectiveDataCursor, sort: dataSort, direction: dataDirection, fractionMode, dataFilters: debouncedDataColumnFilters }), { signal }),
    enabled: dataViewActive && scopeReady && localDataKindAvailable,
    placeholderData: (previous) => previous,
    staleTime: 60_000,
  });
  useEffect(() => {
    const nextCursor = String(table.data?.next_cursor ?? "");
    if (!nextCursor || !table.data?.has_more) return;
    const nextOffset = effectiveDataOffset + dataPreviewLimit;
    setDataPageCursors((current) => current[nextOffset] === nextCursor ? current : { ...current, [nextOffset]: nextCursor });
  }, [table.data?.next_cursor, table.data?.has_more, effectiveDataOffset, dataPreviewLimit]);
  const tableSchema = useQuery({
    queryKey: ["local-data-schema", localDataKind, effectiveRunId, effectiveDumpId],
    queryFn: ({ signal }) => getJson<TableSchemaResponse>(localDataSchemaUrl(localDataKind, effectiveRunId, effectiveDumpId), { signal }),
    enabled: dataViewActive && scopeReady && localDataKindAvailable,
    staleTime: 5 * 60_000,
  });
  const ranking = useQuery({
    queryKey: ["analytics-ranking", metric, rankingDirection, fractionMode, effectiveRunId, effectiveDumpId, localDataKind, debouncedDataSearch, debouncedDataFilterKey, customMetricKey],
    queryFn: ({ signal }) => getJson<TableResponse>(analyticsRankingUrl(
      analysisFilters,
      fractionMode,
      metric,
      effectiveRunId,
      effectiveDumpId,
      rankingPreviewLimit,
      "",
      analysisDataSelection,
      customMetrics,
      rankingDirection,
    ), { signal }),
    enabled: (rankingsViewActive || analyticsViewActive) && hasLocalAnalyticsData,
    placeholderData: (previous) => previous,
    staleTime: 60_000,
  });
  const authorIndexTable = ranking;
  const scientometrics = useQuery({
    queryKey: ["scientometrics", scientometricMetricKey, baselineMetric, fractionMode, effectiveRunId, effectiveDumpId, localDataKind, debouncedDataSearch, debouncedDataFilterKey, customMetricKey],
    queryFn: ({ signal }) => getJson<ScientometricAnalysisPayload>(scientometricsUrl({
      filters: analysisFilters,
      fractionMode,
      metrics: scientometricMetrics,
      baselineMetric,
      rankTopN: analysisRankTopN,
      runId: effectiveRunId,
      dumpId: effectiveDumpId,
      dataSelection: analysisDataSelection,
      customMetrics,
    }), { signal }),
    enabled: analyticsViewActive && hasLocalAnalyticsData && scientometricMetrics.length > 0,
    placeholderData: (previous) => previous,
    staleTime: 10 * 60_000,
    gcTime: 30 * 60_000,
  });
  const detail = useQuery({
    queryKey: ["detail", selected, effectiveRunId, effectiveDumpId],
    queryFn: () => getJson<Record<string, unknown>>(
      selected?.kind === "author"
        ? `/authors/${encodeURIComponent(selected.id)}?run_id=${encodeURIComponent(effectiveRunId)}&dump_id=${encodeURIComponent(effectiveDumpId)}`
        : `/works/${encodeURIComponent(selected?.id ?? "")}?run_id=${encodeURIComponent(effectiveRunId)}&dump_id=${encodeURIComponent(effectiveDumpId)}`,
    ),
    enabled: Boolean(selected) && scopeReady,
    placeholderData: (previous) => previous,
    staleTime: 60_000,
  });

  const domainPresets = (registry.data?.domain_presets ?? []) as ResearchAreaPreset[];
  const organizationPresets = (registry.data?.organization_presets ?? []) as OrganizationPreset[];
  const countryOptions = catalogOptions(countries.data?.results ?? []);
  const workTypeOptions = catalogOptions(workTypes.data?.results ?? []).map((item) => ({ ...item, label: workTypeLabel(item.value) }));
  const storageProfileOptions = configuredOptions(catalog.data?.storage_profiles ?? []);
  const metricCatalogOptions = configuredOptions(catalog.data?.metrics ?? []);
  const primaryMetricOptions = rankingMetricOptions(metricCatalogOptions, CORE_METRIC_OPTIONS);
  const customMetricOptions: SelectOption[] = customMetrics.map((item) => ({
    value: item.id,
    label: item.label,
    description: item.description || "Собственная формула по данным выбранного среза.",
    formula: item.expression,
    custom: true,
  }));
  const allMetricOptions = [...primaryMetricOptions, ...customMetricOptions];
  const metricLabelMap = buildMetricLabelMap(allMetricOptions);
  const fractionModeOptions = configuredOptions(catalog.data?.fraction_modes ?? []);
  const displayFractionModeOptions = fractionModeOptions.length ? fractionModeOptions : FRACTION_MODE_OPTIONS;
  const sourceStrategyOptions = configuredOptions(catalog.data?.data_sources ?? [])
    .filter((item) => ["openalex_cli"].includes(item.value));
  const backendCliApiKeyConfigured = Boolean(catalog.data?.openalex_cli?.api_key_configured);
  const openAlexDownloadKeyRequired = Boolean(catalog.data?.openalex_cli?.api_key_required_for_remote_download ?? true);
  const defaultStorageProfileId = String(defaultOption(storageProfileOptions)?.value ?? "minimal_analytics");
  const defaultSourceStrategy = String(defaultOption(sourceStrategyOptions)?.value ?? "openalex_cli");
  const activeStorageProfileId = storageProfileId || defaultStorageProfileId;
  const activeSourceStrategy = sourceStrategy || defaultSourceStrategy;
  const slicePayload = useMemo(() => buildSliceDefinitionPayload(filters), [filters]);
  const analysisRunPayload = useMemo(() => buildAnalysisRunPayload(fractionMode, displayFractionModeOptions.map((item) => item.value)), [fractionMode, displayFractionModeOptions]);
  const downloadConfigReady = Boolean(activeStorageProfileId && activeSourceStrategy);
  const downloadPolicy = useMemo(() => buildDownloadPolicy(), []);

  const pickDownloadDir = useMutation({
    mutationFn: () => postJson<{ path?: string }>("/system/select-directory", { initial_dir: downloadDir || String(catalog.data?.data_root ?? "") }),
    onSuccess: (result) => {
      if (result.path) setDownloadDir(result.path);
    },
  });

  const saveCustomMetric = useMutation({
    mutationFn: (metricModel: CustomMetricDefinition) => postJson<{ model: CustomMetricDefinition }>("/analytics/custom-metrics", { ...metricModel, run_id: effectiveRunId, enabled: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["custom-metric-models", effectiveRunId] });
    },
  });

  const deleteCustomMetric = useMutation({
    mutationFn: (metricId: string) => {
      const query = new URLSearchParams({ run_id: effectiveRunId });
      return deleteJson<{ deleted: boolean }>(`/analytics/custom-metrics/${encodeURIComponent(metricId)}?${query.toString()}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["custom-metric-models", effectiveRunId] });
    },
  });

  useEffect(() => {
    if (!storageProfileId && defaultStorageProfileId) setStorageProfileId(defaultStorageProfileId);
  }, [storageProfileId, defaultStorageProfileId]);

  useEffect(() => {
    if (!sourceStrategy && defaultSourceStrategy) setSourceStrategy(defaultSourceStrategy);
  }, [sourceStrategy, defaultSourceStrategy]);

  useEffect(() => {
    if (!scopeReady) return;
    const available = localDataKindOptions.map((item) => item.value);
    if (!available.length || available.includes(localDataKind)) return;
    setLocalDataKind(available[0] as LocalDataKind);
    setDataColumnFilters({});
    setDataSort("");
    setDataDirection("desc");
    setSelectedAuthorIds([]);
  }, [scopeReady, localDataKindKey, localDataKind]);

  useEffect(() => {
    const available = new Set(allMetricOptions.map((item) => item.value));
    if (!available.has(metric)) setMetric("h");
    setScientometricMetrics((prev) => {
      const next = prev.filter((item) => available.has(item));
      const normalized = next.length ? next : ["p", "c", "c_frac", "h"];
      return normalized.length === prev.length && normalized.every((item, index) => item === prev[index]) ? prev : normalized;
    });
    if (!available.has(baselineMetric)) setBaselineMetric("h");
  }, [customMetricKey, allMetricOptions.map((item) => item.value).join("|"), metric, baselineMetric]);

  useEffect(() => {
    setScientometricMetrics((prev) => {
      if (!baselineMetric || prev.includes(baselineMetric)) return prev;
      return [baselineMetric, ...prev];
    });
  }, [baselineMetric]);

  const createSlice = useMutation({
    mutationFn: (body: SliceDefinitionPayload & { title?: string }) => postJson<WorkbenchSlice>("/slices", body),
    onSuccess: (doc) => {
      setSliceDoc(doc);
      qc.invalidateQueries({ queryKey: ["workbench"] });
    },
  });
  const estimateSlice = useMutation({
    mutationFn: async (options: { refresh?: boolean } = {}) => {
      const doc = await postJson<WorkbenchSlice>("/slices", { ...slicePayload, title: humanSliceTitle(filters) });
      setSliceDoc(doc);
      const result = await postJson<EstimatePayload>(`/slices/${encodeURIComponent(doc.slice_id ?? "")}/estimate`, { download_policy: downloadPolicy, refresh_estimate: Boolean(options.refresh) });
      return { doc, result };
    },
    onSuccess: ({ doc, result }) => {
      setSliceDoc({ ...doc, current_estimate: result, state: "estimated" });
      setEstimate(result);
      qc.invalidateQueries({ queryKey: ["workbench"] });
      navigate("slices");
    },
  });
  const createMaterialization = useMutation({
    mutationFn: async () => {
      const doc = sliceDoc ?? (await postJson<WorkbenchSlice>("/slices", { ...slicePayload, title: humanSliceTitle(filters) }));
      const sliceId = String(doc.slice_id ?? "");
      setSliceDoc(doc);
      return postJson<MaterializationPlanPayload>(`/slices/${encodeURIComponent(sliceId)}/materialization-plans`, { storage_profile_id: activeStorageProfileId, source_strategy: activeSourceStrategy, download_policy: downloadPolicy, download_dir: downloadDir.trim() || undefined });
    },
    onSuccess: (plan) => {
      setMaterialization(plan);
      qc.invalidateQueries({ queryKey: ["workbench"] });
    },
  });
  const runMaterialization = useMutation({
    mutationFn: async () => {
      const plan = materialization ?? (await createMaterialization.mutateAsync());
      const materializationId = String(plan.materialization_id ?? "");
      return postJson<{ run?: WorkbenchRun }>(`/materializations/${encodeURIComponent(materializationId)}/run`, materializationRunPayload(apiKey, downloadDir, maxDownloadMb));
    },
    onSuccess: (result) => {
      setApiKey("");
      setRunId(result?.run?.run_id ?? "");
      setDumpId("");
      qc.invalidateQueries({ queryKey: ["workbench"] });
      navigate("data");
    },
  });
  const downloadSlice = useMutation({
    mutationFn: async () => {
      const doc = await postJson<WorkbenchSlice>("/slices", { ...slicePayload, title: humanSliceTitle(filters) });
      setSliceDoc(doc);
      const estimateResult = await postJson<EstimatePayload>(`/slices/${encodeURIComponent(doc.slice_id ?? "")}/estimate`, { download_policy: downloadPolicy });
      setEstimate(estimateResult);
      setSliceDoc({ ...doc, current_estimate: estimateResult, state: "estimated" });
      const decision = estimateResult?.decision ?? {};
      if (decision.can_execute === false) {
        const reason = [...(decision.reasons ?? []), ...(decision.warnings ?? [])].filter(Boolean).join(" ");
        throw new Error(reason || "OpenAlex не вернул работ для выбранных фильтров.");
      }
      const plan = await postJson<MaterializationPlanPayload>(`/slices/${encodeURIComponent(doc.slice_id ?? "")}/materialization-plans`, { storage_profile_id: activeStorageProfileId, source_strategy: activeSourceStrategy, download_policy: downloadPolicy, download_dir: downloadDir.trim() || undefined });
      const materializationId = String(plan.materialization_id ?? "");
      setMaterialization(plan);
      return postJson<{ run?: WorkbenchRun }>(`/materializations/${encodeURIComponent(materializationId)}/run`, materializationRunPayload(apiKey, downloadDir, maxDownloadMb));
    },
    onSuccess: (result) => {
      setApiKey("");
      setRunId(result?.run?.run_id ?? "");
      setDumpId("");
      qc.invalidateQueries({ queryKey: ["workbench"] });
      navigate("data");
    },
  });
  const deleteDownloadedDump = useMutation({
    mutationFn: (nextDumpId: string) => deleteJson<{ deleted?: boolean }>(`/dumps/${encodeURIComponent(nextDumpId)}`),
    onSuccess: (_result, nextDumpId) => {
      if (dumpId === nextDumpId || effectiveDumpId === nextDumpId) {
        setDumpId("");
        setRunId("");
      }
      qc.invalidateQueries({ queryKey: ["workbench"] });
      qc.invalidateQueries({ queryKey: ["dumps"] });
    },
  });
  const selectDownloadedDumpRemote = useMutation({
    mutationFn: (nextDumpId: string) => postJson<{ associated_run_id?: string; active_context?: WorkbenchActiveContext; dump?: WorkbenchDump }>(`/dumps/${encodeURIComponent(nextDumpId)}/select`, {}),
    onSuccess: (result, nextDumpId) => {
      const nextRunId = String(result?.associated_run_id ?? result?.active_context?.active_run_id ?? "");
      const selectedDumpId = String(result?.dump?.dump_id ?? result?.active_context?.active_dump_id ?? nextDumpId);
      setRunId(nextRunId);
      setDumpId(selectedDumpId);
      qc.invalidateQueries({ queryKey: ["workbench"] });
      qc.invalidateQueries({ queryKey: ["local-data-summary"] });
      qc.invalidateQueries({ queryKey: ["analytics"] });
      qc.invalidateQueries({ queryKey: ["analytics-ranking"] });
      qc.invalidateQueries({ queryKey: ["scientometrics"] });
    },
  });
  const repairDownloadedDump = useMutation({
    mutationFn: (nextDumpId: string) => postJson<{ run?: WorkbenchRun & { payload?: Record<string, unknown> }; dump?: WorkbenchDump }>(`/dumps/${encodeURIComponent(nextDumpId)}/repair`, {}),
    onSuccess: (result) => {
      const nextRunId = String(result?.run?.run_id ?? "");
      const nextDumpId = String(result?.dump?.dump_id ?? result?.run?.payload?.dump_id ?? "");
      if (nextRunId) setRunId(nextRunId);
      if (nextDumpId && !nextDumpId.startsWith("dump_pending_")) setDumpId(nextDumpId);
      if (nextRunId) qc.invalidateQueries({ queryKey: ["run", nextRunId] });
      qc.invalidateQueries({ queryKey: ["workbench"] });
      qc.invalidateQueries({ queryKey: ["dumps"] });
      navigate("data");
    },
  });
  const recalculate = useMutation({
    mutationFn: () => {
      if (!effectiveDumpId) {
        throw new Error("Для пересчета индексов нужен выбранный локальный срез.");
      }
      return postJson<WorkbenchRun>("/runs", {
        action: "recalculate",
        payload: {
          dump_id: effectiveDumpId,
          ...analysisRunPayload,
        },
      });
    },
    onSuccess: (result) => {
      setRunId(String(result.run_id ?? ""));
      setDumpId("");
      navigate("rankings");
    },
  });
  const cancelRun = useMutation({
    mutationFn: (nextRunId: string) => postJson<WorkbenchRun>(`/runs/${encodeURIComponent(nextRunId)}/cancel`, {}),
    onSuccess: (result) => {
      setRunId(String(result?.run_id ?? runId));
      qc.invalidateQueries({ queryKey: ["run", result?.run_id ?? runId] });
    },
  });
  const buildReport = useMutation({
    mutationFn: () => postJson<Record<string, unknown>>(`/reports/build?${filterParams(analysisFilters, {
      metric,
      fraction_mode: fractionMode,
      run_id: runId,
      dump_id: activeDumpId,
      limit: 0,
      scientometric_metrics: scientometricMetrics.join(","),
      baseline_metric: baselineMetric,
      rank_top_n: analysisRankTopN,
      custom_metric_defs: customMetricDefsQuery(customMetrics),
      ...dataSelectionQuery({
        filters: dataColumnFilters,
        search: dataSearch,
        sort: "",
        direction: "desc",
        limit: 0,
        authorIds: selectedAuthorIds,
      }),
    }).toString()}`, {}),
    onSuccess: () => qc.invalidateQueries(),
  });
  const selectDownloadedDump = (dump: WorkbenchDump) => {
    const nextDumpId = String(dump?.dump_id ?? "");
    const slice = (workbench.data?.slices ?? []).find((item) => String(item.slice_id ?? "") === String(dump?.slice_id ?? ""));
    if (slice) {
      setSliceDoc(slice);
      setFilters(filtersFromSlicePayload((slice?.technical_payload ?? {}) as Record<string, unknown>, filters));
      setEstimate(slice?.current_estimate ?? null);
      setMaterialization(slice?.current_materialization_plan ?? null);
    }
    setRunId("");
    setDumpId(nextDumpId);
    if (nextDumpId) selectDownloadedDumpRemote.mutate(nextDumpId);
    navigate("data");
  };

  const errors = [
    createSlice.error,
    estimateSlice.error,
    createMaterialization.error,
    runMaterialization.error,
    downloadSlice.error,
    selectDownloadedDumpRemote.error,
    repairDownloadedDump.error,
    deleteDownloadedDump.error,
    recalculate.error,
  ].filter(Boolean).map(mutationError);
  const queryErrors = [
    registry.error,
    catalog.error,
    workbench.error,
    dumps.error,
    countries.error,
    workTypes.error,
    rateLimit.error,
    run.error,
    localDataSummary.error,
    table.error,
    ranking.error,
    scientometrics.error,
    detail.error,
  ].filter(Boolean);

  useEffect(() => {
    queryErrors.forEach((error) => {
      const message = mutationError(error);
      emitToast({ title: "Данные не загрузились", message, tone: "error", key: `query-${message}` });
    });
  }, [queryErrors.map((error) => mutationError(error)).join("|")]);

  useEffect(() => {
    if (run.data?.status === "failed") {
      emitToast({
        title: "Задача завершилась ошибкой",
        message: String(run.data.error || "Подробности показаны в карточке задачи."),
        tone: "error",
        key: `run-failed-${run.data.run_id}-${run.data.error ?? ""}`,
      });
    }
  }, [run.data?.status, run.data?.run_id, run.data?.error]);

  return (
    <motion.main className="app-shell" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.22, ease: "easeOut" }}>
      <ToastViewport toasts={toasts} onClose={(id) => setToasts((items) => items.filter((item) => item.id !== id))} />
      <header className="top-bar" aria-label="Основные разделы">
        <div className="brand">
          <span>OA</span>
          <div>
            <b>OpenAlex DSS</b>
            <small>Срезы · индексы · отчеты</small>
          </div>
        </div>
        <div role="tablist" aria-orientation="horizontal" className="nav-list" onKeyDown={onNavKeyDown}>
          {workflowNav.map((item, index) => (
            <button
              key={item.id}
              ref={(node) => { navRefs.current[index] = node; }}
              id={`tab-${item.id}`}
              role="tab"
              aria-selected={view === item.id}
              aria-disabled={!item.unlocked}
              aria-controls={`panel-${item.id}`}
              className={[view === item.id ? "active" : "", item.complete ? "complete" : "", !item.unlocked ? "locked" : ""].filter(Boolean).join(" ")}
              tabIndex={item.unlocked ? undefined : -1}
              title={item.unlocked ? undefined : item.reason}
              onClick={() => guardedNavigate(item.id)}
            >
              <b className="nav-step-number">{item.complete ? <CheckCircle2 size={13} /> : item.unlocked ? item.index : <Lock size={12} />}</b>
              {item.icon}
              <span>
                {item.label}
                {!item.unlocked && <small>{item.reason}</small>}
              </span>
            </button>
          ))}
        </div>
        <StatusRail state={workbench.data} run={run.data} running={running} />
      </header>

      <AnimatePresence mode="wait">
        <motion.section
          key={view}
          className="workbench"
          id={`panel-${view}`}
          role="tabpanel"
          aria-labelledby={`tab-${view}`}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.16, ease: "easeOut" }}
        >
        <header className="page-header">
          <div>
            <span className="eyebrow">Рабочий процесс</span>
            <h1>{pageTitle(view)}</h1>
            <p>{pageLead(view)}</p>
          </div>
        </header>
        {errors.length > 0 && <div className="notice error">{errors[0]}</div>}
        {run.data && view !== "slices" && view !== "data" && ["queued", "running", "cancelling", "failed"].includes(String(run.data.status ?? "")) && (
          <section className="panel task-status-panel">
            <RunCard run={run.data} />
          </section>
        )}

        {view === "slices" && (
          <SlicesPage
            filters={filters}
            setFilters={setFilters}
            domainPresets={domainPresets}
            organizationPresets={organizationPresets}
            countryOptions={countryOptions}
            workTypeOptions={workTypeOptions}
            onOpenResolver={() => setResolverOpen(true)}
            onEstimate={(refresh = false) => estimateSlice.mutate({ refresh })}
            estimate={estimate ?? sliceDoc?.current_estimate}
            materialization={materialization ?? sliceDoc?.current_materialization_plan}
            downloadDir={downloadDir}
            setDownloadDir={setDownloadDir}
            maxDownloadMb={maxDownloadMb}
            setMaxDownloadMb={setMaxDownloadMb}
            onPickDownloadDir={() => pickDownloadDir.mutate()}
            pickingDownloadDir={pickDownloadDir.isPending}
            dataRoot={String(catalog.data?.data_root ?? "")}
            apiKey={apiKey}
            setApiKey={setApiKey}
            backendCliApiKeyConfigured={backendCliApiKeyConfigured}
            openAlexDownloadKeyRequired={openAlexDownloadKeyRequired}
            effectiveRunId={effectiveRunId}
            effectiveDumpId={effectiveDumpId}
            onSelect={setSelected}
            onApplyToSlice={(tab, item) => applyEntityToCurrentSlice(tab, item, setFilters, navigate)}
            rateLimit={rateLimit.data}
            onRun={() => {
              const plan = materialization ?? sliceDoc?.current_materialization_plan;
              if (plan?.materialization_id) runMaterialization.mutate();
              else downloadSlice.mutate();
            }}
            onCancelRun={() => runId && cancelRun.mutate(runId)}
            estimating={estimateSlice.isPending}
            materializing={downloadSlice.isPending || runMaterialization.isPending || running || cancelRun.isPending}
            downloadConfigReady={downloadConfigReady}
            run={run.data}
            sliceDoc={sliceDoc}
            downloadedDumps={dumps.data?.dumps ?? []}
            onSelectDownloadedDump={selectDownloadedDump}
            onShowDumpInfo={setDumpInfo}
            onRepairDownloadedDump={(nextDumpId) => repairDownloadedDump.mutate(nextDumpId)}
            onDeleteDownloadedDump={(nextDumpId) => deleteDownloadedDump.mutate(nextDumpId)}
            deletingDumpId={String(deleteDownloadedDump.variables ?? "")}
            repairingDumpId={activeRepairDumpId(run.data, repairDownloadedDump.variables)}
            selectedDumpId={effectiveDumpId}
          />
        )}

        {view === "data" && (
          <DataView
            localDataSummary={localDataSummary.data}
            localDataKind={localDataKind}
            setLocalDataKind={setLocalDataKind}
            localDataKindOptions={localDataKindOptions}
            dataColumnFilters={dataColumnFilters}
            setDataColumnFilters={setDataColumnFilters}
            dataSearch={dataSearch}
            setDataSearch={setDataSearch}
            dataSort={dataSort}
            setDataSort={setDataSort}
            dataDirection={dataDirection}
            setDataDirection={setDataDirection}
            selectedAuthorIds={selectedAuthorIds}
            setSelectedAuthorIds={setSelectedAuthorIds}
            dataOffset={effectiveDataOffset}
            setDataOffset={setDataOffset}
            pageSize={DATA_PREVIEW_PAGE_SIZE}
            table={table.data}
            tableSchema={tableSchema.data}
            tableLoading={table.isFetching || tableSchema.isFetching}
            csvUrl={`${API_BASE}${localDataPreviewCsvUrl(localDataKind, { q: dataSearch, runId: effectiveRunId, dumpId: effectiveDumpId, limit: 100_000, offset: 0, sort: dataSort, direction: dataDirection, fractionMode, dataFilters: dataColumnFilters })}`}
            run={run.data}
            running={running}
            activeContext={workbench.data?.active_context}
            usingActiveContextScope={usingActiveContextScope}
            effectiveRunId={effectiveRunId}
            effectiveDumpId={effectiveDumpId}
            onRefresh={() => qc.invalidateQueries()}
            onSelect={(next) => setSelected(next)}
          />
        )}

        {view === "rankings" && (
          <IndicesView
            metric={metric}
            setMetric={setMetric}
            rankingDirection={rankingDirection}
            setRankingDirection={setRankingDirection}
            fractionMode={fractionMode}
            setFractionMode={setFractionMode}
            ranking={ranking.data}
            authorIndexTable={authorIndexTable.data}
            selectedMetrics={scientometricMetrics}
            setSelectedMetrics={setScientometricMetrics}
            customMetrics={customMetrics}
            setCustomMetrics={setCustomMetrics}
            onSaveCustomMetric={(model) => saveCustomMetric.mutateAsync(model)}
            onDeleteCustomMetric={(id) => deleteCustomMetric.mutateAsync(id)}
            customMetricPersistenceReady={Boolean(effectiveRunId)}
            selectedAuthorIds={selectedAuthorIds}
            metricOptions={allMetricOptions}
            metricLabels={metricLabelMap}
            fractionModeOptions={displayFractionModeOptions}
            onRecalculate={() => recalculate.mutate()}
            canRecalculate={Boolean(effectiveDumpId)}
            recalculating={recalculate.isPending || running}
            usingActiveContextScope={usingActiveContextScope}
            effectiveDumpId={effectiveDumpId}
            onSelect={setSelected}
          />
        )}

        {view === "statistics" && (
          <AnalyticsView
            filters={analysisFilters}
            scientometrics={scientometrics.data}
            authorIndexTable={authorIndexTable.data}
            loadingScientometrics={scientometrics.isFetching}
            scientometricsError={scientometrics.error}
            hasAuthorIndices={hasAuthorIndices}
            onRecalculate={() => recalculate.mutate()}
            canRecalculate={Boolean(effectiveDumpId)}
            recalculating={recalculate.isPending || running}
            metric={metric}
            fractionMode={fractionMode}
            runId={effectiveRunId}
            dumpId={effectiveDumpId}
            metricLabels={metricLabelMap}
            customMetrics={customMetrics}
            scientometricMetrics={scientometricMetrics}
            baselineMetric={baselineMetric}
            rankTopN={analysisRankTopN}
            dataFilters={dataColumnFilters}
            dataKind={localDataKind}
            dataSearch={dataSearch}
            selectedAuthorIds={selectedAuthorIds}
            setSelectedAuthorIds={setSelectedAuthorIds}
            selectedAuthorRows={selectedAuthorRows}
            setSelectedAuthorRows={setSelectedAuthorRows}
          />
        )}

        {view === "reports" && (
          <ReportsPage filters={analysisFilters} metric={metric} fractionMode={fractionMode} runId={effectiveRunId} dumpId={effectiveDumpId} scientometricMetrics={scientometricMetrics} baselineMetric={baselineMetric} rankTopN={analysisRankTopN} dataFilters={dataColumnFilters} dataSort={dataSort} dataDirection={dataDirection} customMetrics={customMetrics} metricLabels={metricLabelMap} onBuild={() => buildReport.mutate()} building={buildReport.isPending} state={workbench.data} sliceDoc={sliceDoc} estimate={estimate} materialization={materialization} />
        )}
        </motion.section>
      </AnimatePresence>

      {resolverOpen && (
        <ResolverDialog
          filters={filters}
          setFilters={setFilters}
          onClose={() => setResolverOpen(false)}
        />
      )}

      {selected && <DetailDrawer selected={selected} onClose={() => setSelected(null)} detail={detail.data} />}
      {dumpInfo && <DumpInfoModal dump={dumpInfo} onClose={() => setDumpInfo(null)} />}
    </motion.main>
  );
}

function SlicesPage({
  filters,
  setFilters,
  domainPresets,
  organizationPresets,
  countryOptions,
  workTypeOptions,
  onOpenResolver,
  onEstimate,
  estimate,
  materialization,
  downloadDir,
  setDownloadDir,
  maxDownloadMb,
  setMaxDownloadMb,
  onPickDownloadDir,
  pickingDownloadDir,
  dataRoot,
  apiKey,
  setApiKey,
  backendCliApiKeyConfigured,
  openAlexDownloadKeyRequired,
  effectiveRunId,
  effectiveDumpId,
  onSelect,
  onApplyToSlice,
  rateLimit,
  onRun,
  onCancelRun,
  estimating,
  materializing,
  downloadConfigReady,
  run,
  sliceDoc,
  downloadedDumps,
  onSelectDownloadedDump,
  onShowDumpInfo,
  onRepairDownloadedDump,
  onDeleteDownloadedDump,
  deletingDumpId,
  repairingDumpId,
  selectedDumpId,
}: {
  filters: ActiveFilters;
  setFilters: (value: ActiveFilters) => void;
  domainPresets: ResearchAreaPreset[];
  organizationPresets: OrganizationPreset[];
  countryOptions: SelectOption[];
  workTypeOptions: SelectOption[];
  onOpenResolver: () => void;
  onEstimate: (refresh?: boolean) => void;
  estimate: EstimatePayload | null | undefined;
  materialization: MaterializationPlanPayload | null | undefined;
  downloadDir: string;
  setDownloadDir: (value: string) => void;
  maxDownloadMb: string;
  setMaxDownloadMb: (value: string) => void;
  onPickDownloadDir: () => void;
  pickingDownloadDir: boolean;
  dataRoot: string;
  apiKey: string;
  setApiKey: (value: string) => void;
  backendCliApiKeyConfigured: boolean;
  openAlexDownloadKeyRequired: boolean;
  effectiveRunId: string;
  effectiveDumpId: string;
  onSelect: (value: { kind: "author" | "work"; id: string }) => void;
  onApplyToSlice: (tab: PointLookupTab, item: EntitySuggestion) => void;
  rateLimit: RateLimitPayload | null | undefined;
  onRun: () => void;
  onCancelRun: () => void;
  estimating: boolean;
  materializing: boolean;
  downloadConfigReady: boolean;
  run: WorkbenchRun | undefined;
  sliceDoc: WorkbenchSlice | null;
  downloadedDumps: WorkbenchDump[];
  onSelectDownloadedDump: (dump: WorkbenchDump) => void;
  onShowDumpInfo: (dump: WorkbenchDump) => void;
  onRepairDownloadedDump: (dumpId: string) => void;
  onDeleteDownloadedDump: (dumpId: string) => void;
  deletingDumpId: string;
  repairingDumpId: string;
  selectedDumpId: string;
}) {
  const dateInvalid = Boolean(filters.from_publication_date && filters.to_publication_date && filters.from_publication_date > filters.to_publication_date);
  const subjectMissing = false;
  const selectedWorkTypes = splitValues(filters.work_type);
  const visibleWorkTypeOptions = ensureWorkTypeOptions(workTypeOptions.length ? workTypeOptions : [], selectedWorkTypes);
  const decision = estimate?.decision ?? {};
  const rawEstimate = estimate?.estimate ?? null;
  const estimateCache = estimate?.estimate_cache ?? {};
  const hasEstimate = Boolean(estimate);
  const canRun = hasEstimate && decision.can_execute !== false;
  const noDataEstimate = hasEstimate && (decision.status === "no_data" || Number(rawEstimate?.estimate_count ?? 0) === 0);
  const emptyEstimateValue = hasEstimate ? "0" : "—";
  const apiKeyReady = Boolean(apiKey.trim()) || backendCliApiKeyConfigured;
  const downloadKeyMissing = openAlexDownloadKeyRequired && !apiKeyReady;

  return (
    <div className="stack">
      <DownloadedSlicesPanel
        downloadedDumps={downloadedDumps}
        selectedDumpId={selectedDumpId}
        repairingDumpId={repairingDumpId}
        deletingDumpId={deletingDumpId}
        onSelectDownloadedDump={onSelectDownloadedDump}
        onShowDumpInfo={onShowDumpInfo}
        onRepairDownloadedDump={onRepairDownloadedDump}
        onDeleteDownloadedDump={onDeleteDownloadedDump}
        onBlocked={(row) => emitToast({
          title: "Срез пока недоступен",
          message: row.status.reason || "Сначала восстановите локальные файлы среза.",
          tone: row.status.tone === "error" ? "error" : "info",
        })}
      />

      <div className="slice-layout">
        <section className="panel">
          <div className="panel-head">
            <span className="step-badge">Описание среза</span>
            <h2>Логическое описание среза</h2>
            <p>Эти параметры используются для оценки и новой загрузки. В списке выше появляются только реально скачанные срезы.</p>
          </div>
          <div className="form-grid">
            <Field label="Направление">
              <SubjectInput
                value={filters.subject_name}
                presets={domainPresets}
                onSelect={(item) => setFilters({
                  ...filters,
                  subject_level: item.level,
                  subject_id: item.id,
                  subject_name: item.name,
                  filter_mode: item.filterMode,
                })}
                onClear={() => setFilters({ ...filters, subject_level: "", subject_id: "", subject_name: "", filter_mode: "all" })}
              />
            </Field>
            <Field label="Страна">
              <CountryInput value={filters.country_code} options={countryOptions} onChange={(countryCode) => setFilters({ ...filters, country_code: countryCode })} />
            </Field>
            <Field label="Организация">
              <OrganizationInput
                value={filters.institution_name}
                presets={organizationPresets}
                onSelect={(item) => setFilters({
                  ...filters,
                  institution_id: item.id,
                  institution_name: item.name,
                  institution_ror: item.ror ?? "",
                  country_code: item.countryCode || filters.country_code,
                })}
                onClear={() => setFilters({ ...filters, institution_id: "", institution_name: "", institution_ror: "" })}
              />
            </Field>
            <Field label="С даты">
              <input type="date" value={filters.from_publication_date} onChange={(event) => setFilters({ ...filters, from_publication_date: event.target.value })} />
            </Field>
            <Field label="По дату">
              <input type="date" value={filters.to_publication_date} onChange={(event) => setFilters({ ...filters, to_publication_date: event.target.value })} />
            </Field>
            <Field label="Типы публикаций">
              <WorkTypePicker
                options={visibleWorkTypeOptions}
                selected={selectedWorkTypes}
                onChange={(selectedTypes) => setFilters({ ...filters, work_type: selectedTypes.join("|") })}
              />
            </Field>
          </div>
          <div className="quality-row">
            <CheckPill active label="Исключать отозванные" />
            <CheckPill active label="Исключать служебные тексты" />
            <CheckPill active label="XPAC выключен" />
          </div>
          {!filters.subject_id && !filters.keyword_id && !filters.text_search_query && <div className="notice"><b>Все направления</b><span>Тематический фильтр не применяется. Перед скачиванием система покажет прогноз объема, а решение о загрузке остается за пользователем.</span></div>}
          {dateInvalid && <div className="notice error"><b>Проверьте период</b><span>Дата начала не должна быть позже даты окончания.</span></div>}
        <div className="action-row">
          <button onClick={onOpenResolver}><Settings2 size={16} /> Тонкая настройка</button>
          <button className="primary" onClick={() => onEstimate(false)} disabled={estimating || dateInvalid || subjectMissing}>{estimating ? <Loader2 size={16} className="spin" /> : <Gauge size={16} />} {estimating ? "Оцениваем..." : "Оценить объем"}</button>
        </div>
        </section>

        <aside className="panel context-panel">
          <span className="step-badge">Текущий срез</span>
          <h2>{humanSliceTitle(filters)}</h2>
          <KeyValue label="Направление" value={sliceSubjectTitle(filters)} />
          <KeyValue label="Территория" value={filters.country_code ? countryDisplay(filters.country_code, countryOptions) : "Все страны"} />
          <KeyValue label="Организация" value={filters.institution_name || "Любая организация"} />
          <KeyValue label="Период" value={`${filters.from_publication_date} — ${filters.to_publication_date}`} />
          <KeyValue label="Публикации" value={formatWorkTypes(filters.work_type, workTypeOptions)} />
          <KeyValue label="Состояние" value={sliceDoc?.state ?? "draft"} />
        </aside>
      </div>

      <section className="panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">Оценка и получение данных</span>
            <h2>План локального среза</h2>
            <p>Система оценивает объем через OpenAlex API, а уже скачанные срезы выбираются без API. Для новой загрузки установленный загрузчик OpenAlex требует ключ.</p>
          </div>
          <button onClick={() => onEstimate(true)} disabled={estimating || dateInvalid || subjectMissing}>{estimating ? <Loader2 size={16} className="spin" /> : <Gauge size={16} />} {estimating ? "Оцениваем..." : "Обновить оценку"}</button>
        </div>
        <div className="metric-grid">
          <MetricCard label="Работ найдено" value={hasEstimate ? fmt(rawEstimate?.estimate_count ?? 0) : "—"} />
          <MetricCard label="Полный срез / к загрузке" value={hasEstimate ? `${fmt(rawEstimate?.estimate_count ?? 0)} / ${fmt(decision.records_to_fetch ?? rawEstimate?.planned_records ?? 0)}` : "—"} />
          <MetricCard label="API-запросов" value={hasEstimate ? fmt(decision.api_requests_planned ?? rawEstimate?.api_requests_planned ?? 0) : "—"} />
          <MetricCard label="Прогноз загрузки" value={hasEstimate ? `${fmt(rawEstimate?.estimated_cli_metadata_mb ?? decision.estimated_raw_mb ?? rawEstimate?.estimated_raw_mb ?? 0)} МБ` : emptyEstimateValue} />
          <MetricCard label="Прогноз предпросмотра" value={hasEstimate ? `${fmt(rawEstimate?.estimated_selected_api_mb ?? rawEstimate?.estimated_raw_mb ?? 0)}–${fmt(rawEstimate?.estimated_raw_mb_p90 ?? decision.estimated_raw_mb ?? 0)} МБ` : emptyEstimateValue} />
          <MetricCard label="Parquet прогноз" value={hasEstimate ? `${fmt(rawEstimate?.estimated_parquet_mb ?? 0)} МБ` : emptyEstimateValue} />
          <MetricCard label="Кэш оценки" value={hasEstimate ? estimateCacheLabel(String(estimateCache.status ?? "")) : "—"} />
        </div>
        <EstimateBudget estimate={rawEstimate} decision={decision} />
        <EstimateFacets facets={rawEstimate?.facets} />
        <div className={canRun ? "notice success" : noDataEstimate ? "notice warn" : hasEstimate ? "notice error" : "notice"}>
          <b>{canRun ? "План можно использовать" : noDataEstimate ? "По текущим фильтрам работ не найдено" : hasEstimate ? "План нужно уточнить" : "Сначала оцените объем"}</b>
          <span>
            {noDataEstimate
              ? "OpenAlex вернул 0 работ. Расширьте период, снимите часть ограничений, выберите «Все направления» или более широкий предметный уровень."
              : `${decisionStrategyLabel(String(decision.strategy ?? ""))} · ${decisionStatusLabel(String(decision.status ?? ""))}`}
          </span>
        </div>
        <div className="notice">
          <b>Где используется OpenAlex API</b>
          <span>OpenAlex API используется для справочников, оценки объема и точечного добавления автора, организации, источника или работы к срезу. Выбор, просмотр, пересчет и удаление уже скачанного среза API не используют.</span>
        </div>
        <section className={downloadKeyMissing ? "notice warn" : "notice success"}>
          <b>Доступ к OpenAlex</b>
          <span>
            {downloadKeyMissing
              ? "Для скачивания нового среза нужен ключ OpenAlex. Введите его ниже или задайте OPENALEX_API_KEY на сервере. Уже скачанные срезы можно выбирать и анализировать без ключа."
              : backendCliApiKeyConfigured && !apiKey.trim()
                ? "Ключ задан на сервере. Новую загрузку можно запускать."
                : "Ключ введен для текущей загрузки. После запуска поле будет очищено в интерфейсе."}
          </span>
          <Field label="Ключ OpenAlex для новой загрузки">
            <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Введите ключ OpenAlex" />
            <small className="field-hint">Ключ нужен только для новой загрузки через OpenAlex CLI. Он не требуется для выбора, просмотра, восстановления и пересчета уже скачанных локальных срезов.</small>
          </Field>
        </section>
        {[...(decision.reasons ?? []), ...(decision.warnings ?? [])].length > 0 && (
          <ul className="plain-list">
            {[...(decision.reasons ?? []), ...(decision.warnings ?? [])].map((item: string) => <li key={item}>{decisionMessageLabel(item)}</li>)}
          </ul>
        )}
        <details className="technical-details">
          <summary>Папка и ограничения загрузки</summary>
          <div className="form-grid tight">
            <Field label="Папка загрузки">
              <div className="lookup-row">
                <input value={downloadDir} onChange={(event) => setDownloadDir(event.target.value)} placeholder="стандартная папка" />
                <button type="button" onClick={onPickDownloadDir} disabled={pickingDownloadDir}>
                  {pickingDownloadDir ? <Loader2 size={16} className="spin" /> : <Database size={16} />} {pickingDownloadDir ? "Открываем..." : "Выбрать папку"}
                </button>
              </div>
              <small className="field-hint">
                Пусто = стандартная папка внутри хранилища данных{dataRoot ? `: ${dataRoot}/raw/openalex_cli/<slice_id>` : ""}. Кнопка открывает системный выбор папки на этом компьютере.
              </small>
            </Field>
            <Field label="Лимит загрузки, МБ">
              <input
                type="number"
                min={1}
                max={500000}
                value={maxDownloadMb}
                onChange={(event) => setMaxDownloadMb(event.target.value)}
                placeholder="Без лимита"
              />
              <small className="field-hint">Если лимит достигнут, загрузка остановится, а уже скачанные записи будут упакованы как частичный срез для предварительного анализа.</small>
            </Field>
          </div>
        </details>
        <RateLimitPanel rateLimit={rateLimit} apiKeySet={apiKeyReady} estimate={rawEstimate} />
        {materialization && (
          <div className="materialization-card">
            <b>{materialization.profile?.label}</b>
            <span>{materialization.materialization_id}</span>
            <small>{materialization.profile?.description}</small>
          </div>
        )}
        <div className="action-row">
          <button className="primary" onClick={onRun} disabled={materializing || dateInvalid || subjectMissing || !hasEstimate || !downloadConfigReady || downloadKeyMissing || decision.can_execute === false}>{materializing ? <Loader2 size={16} className="spin" /> : <UploadCloud size={16} />} {materializing ? "Выполняется..." : "Скачать срез"}</button>
          {run && ["queued", "running", "cancelling"].includes(String(run.status ?? "")) && (
            <button type="button" className="danger-button" onClick={onCancelRun} disabled={String(run.status ?? "") === "cancelling"}>
              {String(run.status ?? "") === "cancelling" ? "Останавливаем..." : "Остановить и сохранить частичный срез"}
            </button>
          )}
        </div>
      </section>

      <SliceEntityLookup
        effectiveRunId={effectiveRunId}
        effectiveDumpId={effectiveDumpId}
        onSelect={onSelect}
        onApplyToSlice={onApplyToSlice}
      />

      <ProgressPanel filters={filters} estimate={estimate} materialization={materialization} run={run} />
    </div>
  );
}

function materializationRunPayload(apiKey: string, downloadDir: string, maxDownloadMb: string) {
  const payload: Record<string, unknown> = {};
  const key = apiKey.trim();
  const dir = downloadDir.trim();
  const limit = Number(maxDownloadMb);
  if (key) payload.api_key = key;
  if (dir) payload.download_dir = dir;
  if (Number.isFinite(limit) && limit > 0) payload.max_download_mb = limit;
  return payload;
}

function activeRepairDumpId(run: WorkbenchRun | undefined, pendingDumpId: unknown) {
  const pending = String(pendingDumpId ?? "");
  const status = String(run?.status ?? "");
  const action = String(run?.action ?? "");
  if (action !== "repair_dump" || !["queued", "running", "cancelling"].includes(status)) return pending;
  const payload = (run as { payload?: Record<string, unknown> } | undefined)?.payload ?? {};
  return String(payload.dump_id ?? pending);
}

function authorCountText(count: number) {
  const value = Math.abs(Number(count) || 0);
  const mod10 = value % 10;
  const mod100 = value % 100;
  if (mod10 === 1 && mod100 !== 11) return `${fmt(count)} автор`;
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return `${fmt(count)} автора`;
  return `${fmt(count)} авторов`;
}

type PointLookupTab = "author" | "institution" | "work" | "source";

function SliceEntityLookup({
  effectiveRunId,
  effectiveDumpId,
  onSelect,
  onApplyToSlice,
}: {
  effectiveRunId: string;
  effectiveDumpId: string;
  onSelect: (value: { kind: "author" | "work"; id: string }) => void;
  onApplyToSlice: (tab: PointLookupTab, item: EntitySuggestion) => void;
}) {
  const [tab, setTab] = useState<PointLookupTab>("author");
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<EntitySuggestion | null>(null);
  const endpoint = {
    author: "/openalex/authors",
    institution: "/openalex/institutions",
    work: "/openalex/works",
    source: "/openalex/sources",
  }[tab];
  const lookup = useQuery({
    queryKey: ["slice-entity-lookup", tab, query.trim()],
    queryFn: () => getJson<ListPayload<EntitySuggestion>>(`${endpoint}?q=${encodeURIComponent(query.trim())}&limit=10`),
    enabled: query.trim().length >= 2,
  });
  const results = (lookup.data?.results ?? []) as EntitySuggestion[];
  const selectPoint = (item: EntitySuggestion) => {
    const id = String(item.openalex_id || item.id || "").trim();
    setPicked(item);
    if (!id) return;
    onApplyToSlice(tab, item);
    if (tab === "author") onSelect({ kind: "author", id });
    if (tab === "work") onSelect({ kind: "work", id });
  };

  return (
    <section className="panel">
        <div className="panel-head">
          <div>
            <span className="step-badge">Добавить к срезу</span>
            <h2>Автор, работа, организация или источник</h2>
            <p>Это часть настройки среза: найдите сущность в OpenAlex и добавьте ее как ограничение. API используется только по этому явному поисковому запросу.</p>
          </div>
        </div>
        <div className="choice-grid compact lookup-tabs">
          {[
            ["author", "Автор / ORCID"],
            ["institution", "Организация / ROR"],
            ["work", "Работа / DOI"],
            ["source", "Источник"],
          ].map(([id, label]) => (
            <button key={id} type="button" className={tab === id ? "choice-pill active" : "choice-pill"} onClick={() => setTab(id as PointLookupTab)}>
              {label}
            </button>
          ))}
        </div>
        <div className="resolver-search flat-search">
          <Search size={17} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Введите имя, DOI, ORCID, ROR или OpenAlex ID"
          />
          <button type="button" onClick={() => lookup.refetch()} disabled={query.trim().length < 2 || lookup.isFetching}>
            {lookup.isFetching ? <Loader2 size={16} className="spin" /> : <Search size={16} />} Найти
          </button>
        </div>
        <div className="resolver-results embedded">
          {query.trim().length < 2 && <EmptyState title="Введите запрос" detail="Поиск запускается только после явного ввода. Он не скачивает срез и не пересчитывает индексы." />}
          {query.trim().length >= 2 && results.length === 0 && !lookup.isFetching && <EmptyState title="Ничего не найдено" detail="Попробуйте полный OpenAlex ID, DOI, ORCID или ROR." />}
          {results.map((item) => (
            <button key={`${tab}-${item.openalex_id}-${item.id}-${item.name}`} type="button" onClick={() => selectPoint(item)}>
              <b>{item.name}</b>
              <span>{item.level_label ?? item.level ?? ""} {item.works_count ? `· ${fmt(item.works_count)} работ` : ""} {item.cited_by_count ? `· ${fmt(item.cited_by_count)} цитирований` : ""}</span>
              <small>{item.openalex_id ?? item.id} {item.ror ? `· ROR: ${item.ror}` : ""} {item.orcid ? `· ORCID: ${item.orcid}` : ""} {item.doi ? `· DOI: ${item.doi}` : ""}</small>
            </button>
          ))}
        </div>
        <div className="notice">
          <b>{effectiveRunId || effectiveDumpId ? "Ограничение добавится к текущему срезу" : "Можно добавить ограничение до скачивания"}</b>
          <span>{effectiveRunId || effectiveDumpId ? "Карточка автора или работы открывается в контексте выбранного локального среза. Глобальные значения OpenAlex не заменяют локальные индексы." : "После выбора сущности она попадет в описание среза; для локальных карточек и расчета затем нужен скачанный срез."}</span>
        </div>
        {picked && (
          <div className="materialization-card">
            <b>{picked.name}</b>
            <span>{picked.level_label ?? picked.level ?? "OpenAlex entity"}</span>
            <small>{picked.openalex_id ?? picked.id} {picked.ror ? `· ROR: ${picked.ror}` : ""} {picked.orcid ? `· ORCID: ${picked.orcid}` : ""} {picked.doi ? `· DOI: ${picked.doi}` : ""}</small>
          </div>
        )}
      </section>
  );
}

function applyEntityToCurrentSlice(
  tab: PointLookupTab,
  item: EntitySuggestion,
  setFilters: (updater: (previous: ActiveFilters) => ActiveFilters) => void,
  navigate: (view: View) => void,
) {
  const id = String(item.openalex_id || item.id || "").trim();
  const doi = String(item.doi || "").trim();
  const patch: Partial<ActiveFilters> = {};
  if (tab === "author" && id) {
    patch.author_id = id;
    patch.author_name = item.name ?? "";
    patch.author_orcid = item.orcid ?? "";
  }
  if (tab === "institution" && id) {
    patch.institution_id = id;
    patch.institution_name = item.name ?? "";
    patch.institution_ror = item.ror ?? "";
  }
  if (tab === "source" && id) {
    patch.source_id = id;
    patch.source_name = item.name ?? "";
    patch.source_type = item.level ?? "";
  }
  if (tab === "work" && doi) {
    patch.doi = doi;
  }
  if (Object.keys(patch).length > 0) {
    setFilters((previous) => ({ ...previous, ...patch }));
    emitToast({ title: "Данные добавлены к срезу", message: "Параметры текущего среза обновлены. Проверьте их во вкладке “Срез”.", tone: "success" });
    navigate("slices");
  } else {
    emitToast({ title: "Карточка открыта", message: "Данных достаточно для просмотра, но нет поля, которое можно добавить в фильтры среза.", tone: "info" });
  }
}

function ResolverDialog({ filters, setFilters, onClose }: { filters: ActiveFilters; setFilters: (value: ActiveFilters) => void; onClose: () => void }) {
  const [tab, setTab] = useState<ResolverTab>("subject");
  const [query, setQuery] = useState("");
  const endpoint = {
    subject: "/openalex/subjects",
    organization: "/openalex/institutions",
    author: "/openalex/authors",
    source: "/openalex/sources",
  }[tab];
  const suggestions = useQuery({
    queryKey: ["resolver", tab, query],
    queryFn: () => getJson<ListPayload<EntitySuggestion>>(`${endpoint}?q=${encodeURIComponent(query)}&limit=10`),
    enabled: query.trim().length >= 2 || tab === "subject",
  });
  const results = (suggestions.data?.results ?? []) as EntitySuggestion[];

  const select = (item: EntitySuggestion) => {
    if (tab === "subject") {
      setFilters({
        ...filters,
        subject_level: item.level ?? "topic",
        subject_id: item.id,
        subject_name: item.name,
        filter_mode: "primary_topic",
      });
    }
    if (tab === "organization") {
      setFilters({
        ...filters,
        institution_id: item.openalex_id ?? item.id,
        institution_name: item.name,
        institution_ror: item.ror ?? "",
        country_code: item.country_code || filters.country_code,
      });
    }
    if (tab === "author") {
      setFilters({
        ...filters,
        author_id: item.openalex_id ?? item.id,
        author_name: item.name,
        author_orcid: item.orcid ?? "",
      });
    }
    if (tab === "source") {
      setFilters({
        ...filters,
        source_id: item.openalex_id ?? item.id,
        source_name: item.name,
      });
    }
    onClose();
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Тонкая настройка и сопоставление">
      <section className="modal">
        <div className="modal-head">
          <div>
            <span className="step-badge">Поиск в OpenAlex</span>
            <h2>Тонкая настройка и сопоставление</h2>
            <p>Здесь можно выбрать только реально найденные темы, организации, авторов и источники. ROR и ORCID вводятся в то же поле поиска.</p>
          </div>
          <button onClick={onClose} aria-label="Закрыть"><X size={18} /></button>
        </div>
        <div className="resolver-tabs">
          {[
            ["subject", "Тематика"],
            ["organization", "Организация / ROR"],
            ["author", "Автор / ORCID"],
            ["source", "Источник"],
          ].map(([id, label]) => <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id as ResolverTab)}>{label}</button>)}
        </div>
        <div className="resolver-search">
          <Search size={17} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Введите название, ID, ROR или ORCID" autoFocus />
        </div>
        <div className="resolver-results">
          {results.length === 0 && <EmptyState title="Нет выбранного значения" detail="Введите минимум два символа. Если OpenAlex не вернет сущность, ее нельзя использовать в срезе." />}
          {results.map((item) => (
            <button key={`${item.openalex_id}-${item.id}-${item.name}`} onClick={() => select(item)}>
              <b>{item.name}</b>
              <span>{item.level_label ?? item.level ?? item.country_code ?? ""} {item.works_count ? `· ${fmt(item.works_count)} работ` : ""}</span>
              <small>{item.openalex_id ?? item.id} {item.ror ? `· ROR: ${item.ror}` : ""} {item.orcid ? `· ORCID: ${item.orcid}` : ""}</small>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

function WorkTypePicker({ options, selected, onChange }: { options: SelectOption[]; selected: string[]; onChange: (value: string[]) => void }) {
  const selectedSet = new Set(selected);
  const toggle = (value: string) => {
    if (!value) {
      onChange([]);
      return;
    }
    const next = selectedSet.has(value) ? selected.filter((item) => item !== value) : [...selected, value];
    onChange(next);
  };
  return (
    <div className="choice-stack">
      <div className="choice-grid" role="group" aria-label="Типы публикаций OpenAlex">
        <button type="button" className={selected.length === 0 ? "choice-pill active" : "choice-pill"} onClick={() => toggle("")}>
          Все
        </button>
        {options.map((item) => (
          <button
            key={item.value}
            type="button"
            className={selectedSet.has(item.value) ? "choice-pill active" : "choice-pill"}
            onClick={() => toggle(item.value)}
          >
            {item.label}
          </button>
        ))}
        {options.length === 0 && <span className="muted">Справочник типов пока не загружен.</span>}
      </div>
      <small className="field-hint">Выберите один или несколько типов. «Все» снимает ограничение по типу.</small>
    </div>
  );
}

type SubjectSelection = {
  id: string;
  name: string;
  level: string;
  levelLabel?: string;
  filterMode: string;
  worksCount?: number;
};

type OrganizationSelection = {
  id: string;
  name: string;
  ror?: string;
  countryCode?: string;
  worksCount?: number;
};

function SubjectInput({
  value,
  presets,
  onSelect,
  onClear,
}: {
  value: string;
  presets: ResearchAreaPreset[];
  onSelect: (value: SubjectSelection) => void;
  onClear: () => void;
}) {
  const [draft, setDraft] = useState(value);
  const [error, setError] = useState("");
  const queryText = draft.trim();
  const suggestions = useQuery({
    queryKey: ["subject-input", queryText],
    queryFn: () => getJson<ListPayload<EntitySuggestion>>(`/openalex/subjects?q=${encodeURIComponent(queryText)}&limit=12`),
    enabled: queryText.length >= 2,
  });
  const localOptions = useMemo(() => subjectPresetOptions(presets), [presets]);
  const remoteOptions = useMemo(() => subjectSuggestionOptions(suggestions.data?.results ?? []), [suggestions.data]);
  const visibleOptions = mergeSubjects([
    ...localOptions.filter((item) => optionMatches(item, queryText)),
    ...remoteOptions,
  ]).slice(0, 18);

  useEffect(() => {
    setDraft(value);
    setError("");
  }, [value]);

  const commit = async () => {
    const text = draft.trim();
    if (!text) {
      setError("");
      onClear();
      return;
    }
    if (isAllInput(text)) {
      setError("");
      setDraft("Все направления");
      onClear();
      return;
    }
    let options = mergeSubjects([...localOptions, ...remoteOptions]);
    let selected = findSubjectOption(options, text);
    if (!selected && text.length >= 2) {
      const result = await suggestions.refetch();
      options = mergeSubjects([...localOptions, ...subjectSuggestionOptions(result.data?.results ?? [])]);
      selected = findSubjectOption(options, text) ?? options.find((item) => optionMatches(item, text));
    }
    if (!selected) {
      setError("Такое направление не найдено в локальных пресетах и OpenAlex.");
      return;
    }
    setError("");
    setDraft(subjectInputValue(selected));
    onSelect(selected);
  };

  return (
    <div className="validated-input">
      <div className="lookup-row">
        <input
          value={draft}
          list="subject-options"
          aria-invalid={Boolean(error)}
          aria-describedby={error ? "subject-error" : undefined}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commit();
            }
          }}
          placeholder="Начните ввод"
        />
        <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => { setDraft("Все направления"); onClear(); }}>Все</button>
      </div>
      <datalist id="subject-options">
        <option value="Все направления" />
        {visibleOptions.map((item) => (
          <option key={`${item.level}:${item.id}`} value={subjectInputValue(item)} />
        ))}
      </datalist>
      {error && <small id="subject-error" className="field-error">{error}</small>}
      {!error && <small className="field-hint">Поиск идет по OpenAlex Fields, Subfields и Topics; локальные подсказки только ускоряют ввод.</small>}
    </div>
  );
}

function OrganizationInput({
  value,
  presets,
  onSelect,
  onClear,
}: {
  value: string;
  presets: OrganizationPreset[];
  onSelect: (value: OrganizationSelection) => void;
  onClear: () => void;
}) {
  const [draft, setDraft] = useState(value);
  const [error, setError] = useState("");
  const queryText = draft.trim();
  const suggestions = useQuery({
    queryKey: ["organization-input", queryText],
    queryFn: () => getJson<ListPayload<EntitySuggestion>>(`/openalex/institutions?q=${encodeURIComponent(queryText)}&limit=12`),
    enabled: queryText.length >= 2,
  });
  const localOptions = useMemo(() => organizationPresetOptions(presets), [presets]);
  const remoteOptions = useMemo(() => organizationSuggestionOptions(suggestions.data?.results ?? []), [suggestions.data]);
  const visibleOptions = mergeOrganizations([
    ...localOptions.filter((item) => optionMatches(item, queryText)),
    ...remoteOptions,
  ]).slice(0, 18);

  useEffect(() => {
    setDraft(value);
    setError("");
  }, [value]);

  const commit = async () => {
    const text = draft.trim();
    if (!text) {
      setError("");
      onClear();
      return;
    }
    if (isAllInput(text)) {
      setError("");
      setDraft("Все организации");
      onClear();
      return;
    }
    let options = mergeOrganizations([...localOptions, ...remoteOptions]);
    let selected = findOrganizationOption(options, text);
    if (!selected && text.length >= 2) {
      const result = await suggestions.refetch();
      options = mergeOrganizations([...localOptions, ...organizationSuggestionOptions(result.data?.results ?? [])]);
      selected = findOrganizationOption(options, text) ?? options.find((item) => optionMatches(item, text));
    }
    if (!selected) {
      setError("Такая организация не найдена в локальном справочнике и OpenAlex.");
      return;
    }
    setError("");
    setDraft(organizationInputValue(selected));
    onSelect(selected);
  };

  return (
    <div className="validated-input">
      <div className="lookup-row">
        <input
          value={draft}
          list="organization-options"
          aria-invalid={Boolean(error)}
          aria-describedby={error ? "organization-error" : undefined}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commit();
            }
          }}
          placeholder="Начните ввод"
        />
        <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => { setDraft("Все организации"); onClear(); }}>Все</button>
      </div>
      <datalist id="organization-options">
        <option value="Все организации" />
        {visibleOptions.map((item) => (
          <option key={item.id} value={organizationInputValue(item)} />
        ))}
      </datalist>
      {error && <small id="organization-error" className="field-error">{error}</small>}
      {!error && <small className="field-hint">Поиск идет по OpenAlex Institutions и ROR. Пустое поле означает: без ограничения по организации.</small>}
    </div>
  );
}

function CountryInput({ value, options, onChange }: { value: string; options: SelectOption[]; onChange: (value: string) => void }) {
  const [draft, setDraft] = useState(value ? countryDisplay(value, options) : "");
  const [error, setError] = useState("");

  useEffect(() => {
    setDraft(value ? countryDisplay(value, options) : "");
    setError("");
  }, [value, options]);

  const commit = () => {
    const next = resolveCountryDraft(draft, options);
    if (!draft.trim()) {
      setError("");
      onChange("");
      return;
    }
    if (isAllInput(draft)) {
      setError("");
      onChange("");
      setDraft("Все страны");
      return;
    }
    if (!next) {
      setError("Выберите страну из подсказок или введите ISO-код.");
      return;
    }
    setError("");
    onChange(next);
    setDraft(countryDisplay(next, options));
  };

  return (
    <div className="validated-input">
      <div className="lookup-row">
        <input
          value={draft}
          list="country-options"
          aria-invalid={Boolean(error)}
          aria-describedby={error ? "country-error" : undefined}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commit();
            }
          }}
          placeholder="Начните ввод"
        />
        <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => { setDraft("Все страны"); onChange(""); }}>Все</button>
      </div>
      <datalist id="country-options">
        <option value="Все страны" />
        {options.filter((item) => item.value).map((item) => (
          <option key={item.value} value={countryOptionLabel(item)} />
        ))}
      </datalist>
      {error && <small id="country-error" className="field-error">{error}</small>}
      {!error && <small className="field-hint">Выберите страну из подсказок. «Все страны» снимает ограничение.</small>}
    </div>
  );
}

function countryDisplay(value: string, options: SelectOption[]) {
  const option = options.find((item) => item.value.toUpperCase() === value.toUpperCase());
  return option ? countryOptionLabel(option) : countryLabel(value);
}

function countryOptionLabel(option: SelectOption) {
  const code = option.value.trim().toUpperCase();
  const label = option.label.trim();
  return label.includes(`(${code})`) ? label : `${label} (${code})`;
}

function resolveCountryDraft(value: string, options: SelectOption[]) {
  const direct = resolveCountryInput(value);
  if (direct) return direct;
  const text = normalizeInput(value);
  const matched = options.find((item) => {
    const code = item.value.trim().toUpperCase();
    return text === normalizeInput(item.label) || text === normalizeInput(countryOptionLabel(item)) || text === normalizeInput(code);
  });
  return matched?.value.trim().toUpperCase() ?? "";
}

function catalogOptions(rows: Array<Record<string, unknown>>): SelectOption[] {
  const out: SelectOption[] = [];
  rows.forEach((row) => {
    const value = String(row.id ?? row.value ?? row.openalex_id ?? "").trim();
    const label = String(row.name ?? row.display_name ?? row.label ?? value).trim();
    const description = String(row.description ?? "").trim();
    if (value && label) out.push({ value, label, ...(description ? { description } : {}) });
  });
  return out;
}

function formatWorkTypes(value: string, options: SelectOption[]) {
  const selected = splitValues(value);
  if (!selected.length) return "Все поддерживаемые типы";
  const labels = new Map(options.map((item) => [item.value, item.label]));
  return selected.map((item) => labels.get(item) ?? workTypeLabel(item)).join(", ");
}

function configuredOptions(rows: Array<Record<string, unknown>>): SelectOption[] {
  return rows
    .map((row) => {
      const value = String(row.value ?? row.id ?? row.profile_id ?? "").trim();
      const label = String(row.label ?? row.name ?? value).trim();
      const description = String(row.description ?? "").trim();
      const option: SelectOption & { default?: boolean } = { value, label };
      if (description) option.description = description;
      if (Boolean(row.default)) option.default = true;
      return option;
    })
    .filter((item) => item.value && item.label);
}

function defaultOption(options: Array<SelectOption & { default?: boolean }>) {
  return options.find((item) => item.default) ?? options[0];
}

function ensureCurrentOption(options: SelectOption[], value: string) {
  if (!value || options.some((item) => item.value === value)) return options;
  return [{ value, label: value }, ...options];
}

function subjectPresetOptions(presets: ResearchAreaPreset[]): SubjectSelection[] {
  return presets
    .filter((item) => item.subject_id && item.subject_name)
    .map((item) => ({
      id: item.subject_id,
      name: item.subject_name || item.label,
      level: item.subject_level || "topic",
      levelLabel: item.description,
      filterMode: item.filter_mode || "primary_topic",
    }));
}

function subjectSuggestionOptions(rows: Array<Record<string, unknown>>): SubjectSelection[] {
  return rows
    .map((item) => ({
      id: String(item.id ?? item.openalex_id ?? "").trim(),
      name: String(item.name ?? item.display_name ?? item.label ?? "").trim(),
      level: String(item.level ?? "topic").trim() || "topic",
      levelLabel: String(item.level_label ?? item.level ?? "").trim(),
      filterMode: "primary_topic",
      worksCount: Number(item.works_count ?? 0),
    }))
    .filter((item) => item.id && item.name);
}

function organizationPresetOptions(presets: OrganizationPreset[]): OrganizationSelection[] {
  return presets
    .filter((item) => item.institution_id && item.institution_name)
    .map((item) => ({
      id: item.institution_id,
      name: item.institution_name || item.label,
      ror: item.ror,
      countryCode: item.country_code,
    }));
}

function organizationSuggestionOptions(rows: Array<Record<string, unknown>>): OrganizationSelection[] {
  return rows
    .map((item) => ({
      id: String(item.openalex_id ?? item.id ?? "").trim(),
      name: String(item.name ?? item.display_name ?? item.label ?? "").trim(),
      ror: String(item.ror ?? "").trim() || undefined,
      countryCode: String(item.country_code ?? "").trim() || undefined,
      worksCount: Number(item.works_count ?? 0),
    }))
    .filter((item) => item.id && item.name);
}

function subjectInputValue(item: SubjectSelection) {
  return [item.name, item.levelLabel || item.level].filter(Boolean).join(" · ");
}

function organizationInputValue(item: OrganizationSelection) {
  return [item.name, item.countryCode].filter(Boolean).join(" · ");
}

function findSubjectOption(options: SubjectSelection[], text: string) {
  const normalized = normalizeInput(text);
  return options.find((item) => (
    normalizeInput(subjectInputValue(item)) === normalized
    || normalizeInput(item.name) === normalized
    || normalizeInput(item.id) === normalized
  ));
}

function findOrganizationOption(options: OrganizationSelection[], text: string) {
  const normalized = normalizeInput(text);
  return options.find((item) => (
    normalizeInput(organizationInputValue(item)) === normalized
    || normalizeInput(item.name) === normalized
    || normalizeInput(item.id) === normalized
    || (item.ror && normalizeInput(item.ror) === normalized)
  ));
}

function mergeSubjects(items: SubjectSelection[]) {
  const seen = new Set<string>();
  const out: SubjectSelection[] = [];
  items.forEach((item) => {
    const key = `${item.level}:${item.id}`;
    if (seen.has(key)) return;
    seen.add(key);
    out.push(item);
  });
  return out;
}

function mergeOrganizations(items: OrganizationSelection[]) {
  const seen = new Set<string>();
  const out: OrganizationSelection[] = [];
  items.forEach((item) => {
    if (seen.has(item.id)) return;
    seen.add(item.id);
    out.push(item);
  });
  return out;
}

function optionMatches(item: { name: string; id: string }, text: string) {
  const query = normalizeInput(text);
  if (!query) return true;
  return normalizeInput(item.name).includes(query) || normalizeInput(item.id).includes(query);
}

function isAllInput(value: string) {
  return ["all", "все", "все направления", "все страны", "все организации"].includes(normalizeInput(value));
}

function normalizeInput(value: string) {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function ensureWorkTypeOptions(options: SelectOption[], selected: string[]) {
  const out = [...options];
  selected.forEach((value) => {
    if (value && !out.some((item) => item.value === value)) out.unshift({ value, label: value });
  });
  return out;
}

function splitValues(value: string) {
  return value.split("|").map((item) => item.trim()).filter(Boolean);
}

function extractDumpId(run?: WorkbenchRun) {
  const result = run?.result ?? {};
  const build = (result.build ?? {}) as Record<string, unknown>;
  const fetch = (result.fetch ?? {}) as Record<string, unknown>;
  const archive = (result.archive ?? {}) as Record<string, unknown>;
  const analysisEligibility = (result.analysis_eligibility ?? {}) as Record<string, unknown>;
  const buildArchive = (build.archive ?? {}) as Record<string, unknown>;
  const fetchDump = (fetch.dump ?? {}) as Record<string, unknown>;
  return String(
    analysisEligibility.dump_id
    ?? buildArchive.dump_id
    ?? fetchDump.dump_id
    ?? archive.dump_id
    ?? "",
  ).trim();
}

function decisionStatusLabel(value: string) {
  const labels: Record<string, string> = {
    can_fetch: "можно получить данные",
    medium_slice: "средний срез",
    large_slice: "крупный срез",
    very_large_slice: "очень крупный срез",
    no_data: "нет работ",
    unsupported_cli_filter: "фильтр нельзя скачать установленным загрузчиком",
  };
  return labels[value] ?? (value || "нет статуса");
}

function decisionStrategyLabel(value: string) {
  const labels: Record<string, string> = {
    openalex_cli_slice: "скачивание среза OpenAlex",
    openalex_cli_large_slice: "скачивание крупного среза",
    refine_slice: "уточните фильтры",
    do_not_fetch: "не запускать загрузку",
  };
  return labels[value] ?? (value || "оценка еще не выполнена");
}

function estimateCacheLabel(value: string) {
  const labels: Record<string, string> = {
    hit: "использована сохраненная оценка",
    miss: "оценка рассчитана заново",
    refresh: "оценка обновлена вручную",
  };
  return labels[value] ?? "не используется";
}

function decisionMessageLabel(value: string) {
  const labels: Record<string, string> = {
    "OpenAlex returned zero works for this filter.": "OpenAlex вернул 0 работ для этих фильтров.",
    "OpenAlex вернул 0 работ для выбранных фильтров.": "OpenAlex вернул 0 работ для выбранных фильтров.",
    "Estimated corpus is medium-sized. Download is allowed; review the forecast before proceeding.": "Срез среднего размера: перед скачиванием проверьте объем, время и ключ OpenAlex.",
  };
  return labels[value] ?? value;
}
