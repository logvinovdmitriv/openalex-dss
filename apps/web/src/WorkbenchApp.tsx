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
  Sigma,
  UploadCloud,
  X,
} from "lucide-react";
import { Area, Brush, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { API_BASE, deleteJson, getJson, postJson, type CustomMetricDefinition, type TableColumnFilters, type TableResponse } from "./api";
import {
  DEFAULT_FILTERS,
  CORE_METRIC_OPTIONS,
  FRACTION_MODE_OPTIONS,
  countryLabel,
  filterParams,
  fmt,
  modeLabel,
  resolveCountryInput,
  metricLabel,
  workTypeLabel,
  type ActiveFilters,
  type OrganizationPreset,
  type ResearchAreaPreset,
  type SelectOption,
} from "./domain";
import { CheckPill, DataGrid, DetailDrawer, DownloadLink, EmptyState, Field, KeyValue, MetricCard } from "./components/ui";
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
  type ScientometricFinding,
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
import { DataRestrictionChips } from "./features/data/DataRestrictionChips";
import { DataView } from "./features/data/DataView";
import { DownloadedSlicesPanel, DumpInfoModal } from "./features/slices/DownloadedSlices";
import { EstimateBudget, EstimateFacets, RateLimitPanel } from "./features/slices/EstimatePanels";
import { DEFAULT_CUSTOM_METRICS } from "./features/formulas/defaultCustomMetrics";
import { FormulaBuilderDialog, MetricInfoPopover, metricLabelFor } from "./features/formulas/FormulaBuilder";
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

function Workbench() {
  const qc = useQueryClient();
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [view, setView] = useState<View>(() => viewFromHash(window.location.hash));
  const [filters, setFilters] = useState<ActiveFilters>(DEFAULT_FILTERS);
  const [metric, setMetric] = useState("h");
  const [fractionMode, setFractionMode] = useState("strict_authors_count");
  const [topN, setTopN] = useState(0);
  const [dataOffset, setDataOffset] = useState(0);
  const [customMetrics, setCustomMetrics] = useState<CustomMetricDefinition[]>(DEFAULT_CUSTOM_METRICS);
  const [scientometricMetrics, setScientometricMetrics] = useState<string[]>(["p", "c", "c_frac", "h", "g", "iupv", "islv", "custom_added_rating"]);
  const [baselineMetric, setBaselineMetric] = useState("h");
  const [storageProfileId, setStorageProfileId] = useState("");
  const [downloadDir, setDownloadDir] = useState("");
  const [maxDownloadMb, setMaxDownloadMb] = useState("");
  const [dataSort, setDataSort] = useState("");
  const [dataDirection, setDataDirection] = useState<"asc" | "desc">("desc");
  const [dataSearch, setDataSearch] = useState("");
  const [selectedAuthorIds, setSelectedAuthorIds] = useState<string[]>([]);
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
  const dumps = useQuery({ queryKey: ["dumps"], queryFn: () => getJson<{ dumps?: WorkbenchDump[] }>("/dumps?limit=50") });
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
  const customMetricKey = useMemo(() => JSON.stringify(customMetrics), [customMetrics]);
  const analysisFilters = useMemo(() => DATA_ONLY_ANALYSIS_FILTERS, []);
  const dataSelection = useDataSelection({
    filters: dataColumnFilters,
    search: dataSearch,
    sort: dataSort,
    direction: dataDirection,
    limit: topN,
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
  }, [localDataKind, dataSearch, dataFilterKey, dataSort, dataDirection, topN, fractionMode, effectiveRunId, effectiveDumpId]);
  const selectedRowLimit = Math.max(0, Number(topN) || 0);
  const effectiveDataOffset = selectedRowLimit > 0 ? Math.min(dataOffset, Math.max(0, selectedRowLimit - 1)) : dataOffset;
  const dataPreviewLimit = selectedRowLimit > 0
    ? Math.max(1, Math.min(DATA_PREVIEW_PAGE_SIZE, selectedRowLimit - effectiveDataOffset))
    : DATA_PREVIEW_PAGE_SIZE;
  const previewPageKey = `${effectiveDataOffset}:${dataPreviewLimit}`;
  const rankingPreviewLimit = selectedRowLimit > 0 ? Math.min(selectedRowLimit, DATA_PREVIEW_PAGE_SIZE) : DATA_PREVIEW_PAGE_SIZE;
  const analysisRankTopN = selectedRowLimit > 0 ? Math.min(selectedRowLimit, 1000) : 0;
  const table = useQuery({
    queryKey: ["local-data-preview", localDataKind, dataSearch, dataFilterKey, topN, dataSort, dataDirection, fractionMode, effectiveRunId, effectiveDumpId, previewPageKey],
    queryFn: () => getJson<TableResponse>(localDataPreviewUrl(localDataKind, { q: dataSearch, runId: effectiveRunId, dumpId: effectiveDumpId, limit: dataPreviewLimit, offset: effectiveDataOffset, sort: dataSort, direction: dataDirection, fractionMode, dataFilters: dataColumnFilters })),
    enabled: scopeReady && localDataKindAvailable,
    placeholderData: (previous) => previous,
    staleTime: 60_000,
  });
  const ranking = useQuery({
    queryKey: ["analytics-ranking", metric, fractionMode, effectiveRunId, effectiveDumpId, topN, dataSearch, dataFilterKey, dataSort, dataDirection, customMetricKey],
    queryFn: () => getJson<TableResponse>(analyticsRankingUrl(
      analysisFilters,
      fractionMode,
      metric,
      effectiveRunId,
      effectiveDumpId,
      rankingPreviewLimit,
      "",
      dataSelection,
      customMetrics,
    )),
    enabled: hasLocalAnalyticsData,
    placeholderData: (previous) => previous,
    staleTime: 60_000,
  });
  const authorIndexTable = useQuery({
    queryKey: ["author-index-table", fractionMode, effectiveRunId, effectiveDumpId, topN, dataSearch, dataFilterKey, dataSort, dataDirection, previewPageKey],
    queryFn: () => getJson<TableResponse>(localDataPreviewUrl("indices", {
      q: dataSearch,
      runId: effectiveRunId,
      dumpId: effectiveDumpId,
      limit: dataPreviewLimit,
      offset: effectiveDataOffset,
      sort: dataSort,
      direction: dataDirection,
      fractionMode,
      dataFilters: dataColumnFilters,
    })),
    enabled: scopeReady && Boolean(localDataSummary.data?.tables?.indices?.exists),
    placeholderData: (previous) => previous,
    staleTime: 60_000,
  });
  const scientometrics = useQuery({
    queryKey: ["scientometrics", scientometricMetricKey, baselineMetric, topN, fractionMode, effectiveRunId, effectiveDumpId, dataSearch, dataFilterKey, dataSort, dataDirection, customMetricKey],
    queryFn: () => getJson<ScientometricAnalysisPayload>(scientometricsUrl({
      filters: analysisFilters,
      fractionMode,
      metrics: scientometricMetrics,
      baselineMetric,
      rankTopN: analysisRankTopN,
      runId: effectiveRunId,
      dumpId: effectiveDumpId,
      dataSelection,
      customMetrics,
    })),
    enabled: hasLocalAnalyticsData && scientometricMetrics.length > 0,
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
  const uiOptions = catalog.data?.ui_options ?? {};
  const topNOptions = configuredOptions((uiOptions.top_n ?? []) as Array<Record<string, unknown>>);
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
  const defaultStorageProfileId = String(defaultOption(storageProfileOptions)?.value ?? "minimal_analytics");
  const defaultSourceStrategy = String(defaultOption(sourceStrategyOptions)?.value ?? "openalex_cli");
  const activeStorageProfileId = storageProfileId || defaultStorageProfileId;
  const activeSourceStrategy = sourceStrategy || defaultSourceStrategy;
  const activeTopN = topN;
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
      limit: activeTopN > 0 ? Math.min(activeTopN, 500) : 50,
      scientometric_metrics: scientometricMetrics.join(","),
      baseline_metric: baselineMetric,
      rank_top_n: analysisRankTopN,
      custom_metric_defs: customMetricDefsQuery(customMetrics),
      ...dataSelectionQuery({
        filters: dataColumnFilters,
        search: dataSearch,
        sort: dataSort,
        direction: dataDirection,
        limit: activeTopN,
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
            downloadedDumps={dumps.data?.dumps ?? workbench.data?.dumps ?? []}
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
            topN={activeTopN}
            setTopN={setTopN}
            topNOptions={topNOptions}
            dataOffset={effectiveDataOffset}
            setDataOffset={setDataOffset}
            pageSize={DATA_PREVIEW_PAGE_SIZE}
            table={table.data}
            csvUrl={`${API_BASE}${localDataPreviewCsvUrl(localDataKind, { q: dataSearch, runId: effectiveRunId, dumpId: effectiveDumpId, limit: activeTopN > 0 ? activeTopN : 100_000, offset: 0, sort: dataSort, direction: dataDirection, fractionMode, dataFilters: dataColumnFilters })}`}
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
          <RankingsPage
            metric={metric}
            setMetric={setMetric}
            fractionMode={fractionMode}
            setFractionMode={setFractionMode}
            topN={activeTopN}
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
          <StatisticsPage
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
            topN={activeTopN}
            setTopN={setTopN}
            dataFilters={dataColumnFilters}
            setDataFilters={setDataColumnFilters}
            dataSearch={dataSearch}
            setDataSearch={setDataSearch}
            selectedAuthorIds={selectedAuthorIds}
            setSelectedAuthorIds={setSelectedAuthorIds}
            dataSort={dataSort}
            setDataSort={setDataSort}
            dataDirection={dataDirection}
            setDataDirection={setDataDirection}
            onSelect={setSelected}
          />
        )}

        {view === "reports" && (
          <ReportsPage filters={analysisFilters} metric={metric} fractionMode={fractionMode} runId={effectiveRunId} dumpId={effectiveDumpId} topN={activeTopN} scientometricMetrics={scientometricMetrics} baselineMetric={baselineMetric} rankTopN={analysisRankTopN} dataFilters={dataColumnFilters} dataSort={dataSort} dataDirection={dataDirection} customMetrics={customMetrics} metricLabels={metricLabelMap} onBuild={() => buildReport.mutate()} building={buildReport.isPending} state={workbench.data} sliceDoc={sliceDoc} estimate={estimate} materialization={materialization} />
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
            <p>Система оценивает объем через OpenAlex API, а уже скачанные срезы выбираются без API. Новый срез скачивается отдельным действием через установленный загрузчик; если ему нужен ключ, система покажет это до запуска.</p>
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
        {[...(decision.reasons ?? []), ...(decision.warnings ?? [])].length > 0 && (
          <ul className="plain-list">
            {[...(decision.reasons ?? []), ...(decision.warnings ?? [])].map((item: string) => <li key={item}>{decisionMessageLabel(item)}</li>)}
          </ul>
        )}
        <details className="technical-details">
          <summary>Папка и ключ для новой загрузки</summary>
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
            <Field label="Ключ OpenAlex">
              <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Необязательно" />
              <small className="field-hint">Оставьте пустым, если не хотите передавать ключ загрузчику. Если установленный загрузчик потребует ключ, ошибка появится уведомлением.</small>
              {backendCliApiKeyConfigured && !apiKey.trim() && <small className="field-hint">Ключ уже задан в настройках сервера.</small>}
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
          <button className="primary" onClick={onRun} disabled={materializing || dateInvalid || subjectMissing || !hasEstimate || !downloadConfigReady || decision.can_execute === false}>{materializing ? <Loader2 size={16} className="spin" /> : <UploadCloud size={16} />} {materializing ? "Выполняется..." : "Скачать срез"}</button>
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

function RankingsPage({
  metric,
  setMetric,
  fractionMode,
  setFractionMode,
  topN,
  ranking,
  authorIndexTable,
  selectedMetrics,
  setSelectedMetrics,
  customMetrics,
  setCustomMetrics,
  onSaveCustomMetric,
  onDeleteCustomMetric,
  customMetricPersistenceReady,
  selectedAuthorIds,
  metricOptions,
  metricLabels,
  fractionModeOptions,
  onRecalculate,
  canRecalculate,
  recalculating,
  usingActiveContextScope,
  effectiveDumpId,
  onSelect,
}: {
  metric: string;
  setMetric: (value: string) => void;
  fractionMode: string;
  setFractionMode: (value: string) => void;
  topN: number;
  ranking?: TableResponse;
  authorIndexTable?: TableResponse;
  selectedMetrics: string[];
  setSelectedMetrics: (value: string[]) => void;
  customMetrics: CustomMetricDefinition[];
  setCustomMetrics: (value: CustomMetricDefinition[]) => void;
  onSaveCustomMetric: (value: CustomMetricDefinition) => Promise<unknown>;
  onDeleteCustomMetric: (id: string) => Promise<unknown>;
  customMetricPersistenceReady: boolean;
  selectedAuthorIds: string[];
  metricOptions: SelectOption[];
  metricLabels: Record<string, string>;
  fractionModeOptions: SelectOption[];
  onRecalculate: () => void;
  canRecalculate: boolean;
  recalculating: boolean;
  usingActiveContextScope: boolean;
  effectiveDumpId: string;
  onSelect: (value: { kind: "author" | "work"; id: string }) => void;
}) {
  const displayMetricOptions = ensureCurrentOptions(metricOptions, [metric, ...selectedMetrics]);
  const visibleMetrics = [...new Set([metric, ...selectedMetrics])].filter(Boolean);
  const [formulaBuilderOpen, setFormulaBuilderOpen] = useState(false);
  const rankingTable = useMemo(() => selectedAuthorIndexTable(authorIndexTable ?? ranking, visibleMetrics, selectedAuthorIds), [authorIndexTable, ranking, visibleMetrics.join(","), selectedAuthorIds.join("|")]);
  const toggleMetric = (value: string) => {
    if (value === metric) return;
    if (selectedMetrics.includes(value)) {
      setSelectedMetrics(selectedMetrics.filter((item) => item !== value));
      return;
    }
    setSelectedMetrics([...selectedMetrics, value]);
  };
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">Расчет индексов</span>
            <h2>Индексы и рейтинги</h2>
          <p>Здесь показывается авторская таблица индексов. Ограничения, сортировка и число строк берутся из вкладки “Данные”, а ниже выбирается, какие индексы вывести.</p>
          </div>
          <button
            className="primary"
            onClick={onRecalculate}
            disabled={recalculating || !canRecalculate}
            title={canRecalculate ? undefined : "Сначала выберите локальный срез"}
          >
            {recalculating ? <Loader2 size={16} className="spin" /> : <Sigma size={16} />} Рассчитать
          </button>
        </div>
        <div className="form-grid tight">
          <Field label="Основной индекс рейтинга">
            <select value={metric} onChange={(event) => setMetric(event.target.value)}>
              {ensureCurrentOption(displayMetricOptions, metric).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
            <small className="field-hint">По этому индексу сортируется рейтинг и строится основной анализ.</small>
          </Field>
          <Field label="Учет вклада соавторов">
            <select value={fractionMode} onChange={(event) => setFractionMode(event.target.value)}>
              {ensureCurrentOption(fractionModeOptions, fractionMode).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
            <small className="field-hint">Настройка влияет на расчет авторских показателей.</small>
          </Field>
        </div>
        <div className="metric-grid">
          <MetricCard label="Показатель" value={metricLabelFor(metric, metricLabels)} />
          <MetricCard label="Учет вклада" value={modeLabel(fractionMode)} />
          <MetricCard label="Лимит из “Данных”" value={topN > 0 ? fmt(topN) : "все"} />
          <MetricCard label="Авторов в таблице" value={fmt(authorIndexTable?.total ?? ranking?.total ?? 0)} />
          <MetricCard label="Точек на графиках" value={selectedAuthorIds.length ? fmt(selectedAuthorIds.length) : "нет"} />
        </div>
        {usingActiveContextScope && effectiveDumpId && (
          <div className="notice">
            <b>Пересчет по активному контексту</b>
            <span>Если запустить расчет сейчас, будет использован активный локальный срез: {effectiveDumpId}.</span>
          </div>
        )}
        {!authorIndexTable && (
          <div className="notice warn action-notice">
            <div>
              <b>Авторские индексы еще не рассчитаны</b>
              <span>Выбранный срез можно смотреть во вкладке “Данные”, но таблица авторов, рейтинги и графики появятся только после локального расчета индексов.</span>
            </div>
            <button
              type="button"
              className="primary"
              onClick={onRecalculate}
              disabled={recalculating || !canRecalculate}
              title={canRecalculate ? undefined : "Сначала выберите локальный срез"}
            >
              {recalculating ? <Loader2 size={16} className="spin" /> : <Sigma size={16} />} Рассчитать индексы
            </button>
          </div>
        )}
        <div className="notice">
          <div>
            <b>Какие индексы показывать</b>
            <span>Нажимайте на показатель, чтобы включить или скрыть его в таблице и аналитике. Значок i рядом с названием показывает смысл показателя и формулу расчета.</span>
          </div>
        </div>
        <div className="metric-option-grid" role="group" aria-label="Показатели в таблице индексов">
          {displayMetricOptions.map((item) => {
            const active = visibleMetrics.includes(item.value);
            const pinned = item.value === metric;
            return (
              <div
                key={item.value}
                className={active ? "metric-option-card active" : "metric-option-card"}
              >
                <button
                  type="button"
                  className="metric-option-toggle"
                  aria-pressed={active}
                  disabled={pinned}
                  onClick={() => toggleMetric(item.value)}
                >
                  <span>
                    <b>{item.label}</b>
                    <small>{pinned ? "основной индекс" : active ? "показан" : "скрыт"}</small>
                  </span>
                </button>
                <MetricInfoPopover metric={item} />
              </div>
            );
          })}
        </div>
        <section className="formula-summary">
          <div>
            <b>Собственные показатели</b>
            <span>Можно добавить расчетный показатель по данным выбранного среза и использовать его в рейтинге, таблице и графиках.</span>
          </div>
          <button type="button" className="primary" onClick={() => setFormulaBuilderOpen(true)}>
            <Sigma size={16} /> Открыть конструктор
          </button>
        </section>
        {formulaBuilderOpen && (
          <FormulaBuilderDialog
            metrics={customMetrics}
            setMetrics={setCustomMetrics}
            onSaveMetric={onSaveCustomMetric}
            onDeleteMetric={onDeleteCustomMetric}
            persistenceReady={customMetricPersistenceReady}
            selectedMetrics={selectedMetrics}
            setSelectedMetrics={setSelectedMetrics}
            activeMetric={metric}
            setActiveMetric={setMetric}
            onClose={() => setFormulaBuilderOpen(false)}
          />
        )}
      </section>
      <section className="panel table-panel">
        <div className="panel-head">
          <span className="step-badge">Таблица индексов</span>
          <h2>Авторский уровень данных</h2>
          <p>Это таблица авторов с выбранными индексами. Она использует те же ограничения, сортировку и число строк, которые заданы на вкладке “Данные”.</p>
        </div>
        <DataGrid data={rankingTable} onSelect={onSelect} hiddenFields={["author_id"]} fieldLabels={metricLabels} />
      </section>
    </div>
  );
}

function selectedAuthorIndexTable(ranking: TableResponse | undefined, metrics: string[], selectedAuthorIds: string[] = []): TableResponse | undefined {
  const projected = projectAuthorIndexTable(ranking, metrics);
  if (!projected) return undefined;
  const selected = new Set(selectedAuthorIds.map(String));
  const rows = selected.size
    ? (projected.rows ?? []).filter((row) => selected.has(String(row.author_id ?? "")))
    : projected.rows;
  return { ...projected, rows, total: selected.size ? rows.length : projected.total };
}

function projectAuthorIndexTable(ranking: TableResponse | undefined, metrics: string[]): TableResponse | undefined {
  if (!ranking) return undefined;
  const fields = ranking.fields ?? [];
  const identityFields = ["author_display_name", "author_id"].filter((field) => fields.includes(field));
  const metricFields = metrics.filter((field) => fields.includes(field));
  const contextFields = ["country_code", "subject_name", "n_flagged_works", "n_truncated_works"].filter((field) => fields.includes(field));
  const selectedFields = [...new Set([...identityFields, ...metricFields, ...contextFields])];
  return { ...ranking, fields: selectedFields.length ? selectedFields : fields };
}

function StatisticsPage({
  filters,
  scientometrics,
  authorIndexTable,
  loadingScientometrics,
  scientometricsError,
  hasAuthorIndices,
  onRecalculate,
  canRecalculate,
  recalculating,
  metric,
  fractionMode,
  runId,
  dumpId,
  metricLabels,
  customMetrics,
  scientometricMetrics,
  baselineMetric,
  rankTopN,
  topN,
  setTopN,
  dataFilters,
  setDataFilters,
  dataSearch,
  setDataSearch,
  selectedAuthorIds,
  setSelectedAuthorIds,
  dataSort,
  setDataSort,
  dataDirection,
  setDataDirection,
  onSelect,
}: {
  filters: ActiveFilters;
  scientometrics?: ScientometricAnalysisPayload;
  authorIndexTable?: TableResponse;
  loadingScientometrics: boolean;
  scientometricsError: unknown;
  hasAuthorIndices: boolean;
  onRecalculate: () => void;
  canRecalculate: boolean;
  recalculating: boolean;
  metric: string;
  fractionMode: string;
  runId: string;
  dumpId: string;
  metricLabels: Record<string, string>;
  customMetrics: CustomMetricDefinition[];
  scientometricMetrics: string[];
  baselineMetric: string;
  rankTopN: number;
  topN: number;
  setTopN: (value: number) => void;
  dataFilters: TableColumnFilters;
  setDataFilters: (value: TableColumnFilters) => void;
  dataSearch: string;
  setDataSearch: (value: string) => void;
  selectedAuthorIds: string[];
  setSelectedAuthorIds: (value: string[]) => void;
  dataSort: string;
  setDataSort: (value: string) => void;
  dataDirection: "asc" | "desc";
  setDataDirection: (value: "asc" | "desc") => void;
  onSelect: (value: { kind: "author" | "work"; id: string }) => void;
}) {
  const metrics = (scientometrics?.metrics ?? scientometricMetrics).filter(Boolean);
  const analyticsMetrics = metrics.length ? metrics : [metric].filter(Boolean);
  const warnings = (scientometrics?.warnings ?? []).filter((warning) => !/Кендалл|Kendall/i.test(String(warning)));
  const [showBoxplot, setShowBoxplot] = useState(true);
  const analyticsAuthorTable = useMemo(() => projectAuthorIndexTable(authorIndexTable, analyticsMetrics), [authorIndexTable, analyticsMetrics.join("|")]);
  const selectedAuthorRows = selectedAuthorIndexTable(authorIndexTable, analyticsMetrics, selectedAuthorIds)?.rows ?? [];
  const scientometricMetricParam = scientometricMetrics.join(",");
  const selectionQuery = dataSelectionQuery({ filters: dataFilters, search: dataSearch, sort: dataSort, direction: dataDirection, limit: topN });
  const scientometricParams = filterParams(filters, {
    fraction_mode: fractionMode,
    metrics: scientometricMetricParam,
    baseline_metric: baselineMetric,
    top_n: rankTopN,
    run_id: runId,
    dump_id: dumpId,
    custom_metric_defs: customMetricDefsQuery(customMetrics),
    ...selectionQuery,
  });
  const hasAnalyticsExportScope = Boolean(runId || dumpId);
  const analyticsDownloads = {
    descriptive: `${API_BASE}/analytics/scientometrics/descriptive.csv?${scientometricParams.toString()}`,
    correlations: `${API_BASE}/analytics/scientometrics/correlations.csv?${scientometricParams.toString()}`,
    findings: `${API_BASE}/analytics/scientometrics/findings.csv?${scientometricParams.toString()}`,
    conclusion: `${API_BASE}/analytics/scientometrics/conclusion.md?${scientometricParams.toString()}`,
  };

  return (
    <div className="stack">
      <section className="notice">
        <b>Аналитика построена по выборке из “Данных”</b>
        <span>Поиск, фильтры, сортировка и число строк задаются во вкладке “Данные”. Отмеченные авторы подсвечиваются точками на графиках.</span>
      </section>
      {!hasAuthorIndices && (
        <section className="notice warn action-notice">
          <div>
            <b>Для графиков нужен расчет индексов</b>
            <span>Скачанный срез содержит работы и авторства. Аналитика строится по авторской таблице “Авторы и индексы”. Запустите расчет для выбранного среза, после завершения графики обновятся автоматически.</span>
          </div>
          <button
            type="button"
            className="primary"
            onClick={onRecalculate}
            disabled={recalculating || !canRecalculate}
            title={canRecalculate ? undefined : "Сначала выберите локальный срез"}
          >
            {recalculating ? <Loader2 size={16} className="spin" /> : <Sigma size={16} />} Рассчитать индексы
          </button>
        </section>
      )}
      <section className="panel analytics-hero-panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">Аналитика</span>
            <h2>Аналитика выбранной выборки</h2>
            <p>На этой странице нет отдельных фильтров. Все графики ниже автоматически используют поиск, ограничения, сортировку и число строк из вкладки “Данные”. Отмеченные авторы показываются отдельными точками.</p>
          </div>
          {loadingScientometrics && <span className="status-chip"><Loader2 size={14} className="spin" /> Обновление</span>}
        </div>
        <div className="analytics-context-line">
          <span><b>Строк из “Данных”:</b> {topN > 0 ? fmt(topN) : "все"}</span>
          <span><b>Основной показатель:</b> {metricLabelFor(baselineMetric, metricLabels)}</span>
          <span><b>Показатели:</b> {analyticsMetrics.map((item) => metricLabelFor(item, metricLabels)).join(", ")}</span>
        </div>
      </section>
      {Boolean(scientometricsError) && (
        <section className="notice error">
          <b>Не удалось построить аналитический пакет</b>
          <span>{mutationError(scientometricsError)}</span>
        </section>
      )}
      {warnings.length > 0 && (
        <section className="notice warn">
          <b>Ограничения интерпретации</b>
          <ul className="plain-list">
            {warnings.map((warning: string) => <li key={warning}>{analysisWarningLabel(warning, metricLabels)}</li>)}
          </ul>
        </section>
      )}
      {selectedAuthorIds.length > 0 && (
        <section className="notice success">
          <b>На графиках отмечены выбранные авторы</b>
          <span>Красные точки показывают {authorCountText(selectedAuthorIds.length)}, отмеченных в таблице “Данные”. Распределения и матрицы продолжают считаться по всей отфильтрованной выборке.</span>
        </section>
      )}
      {dataSearch.trim() && selectedAuthorIds.length === 0 && (
        <section className="notice">
          <b>Учитывается поиск из таблицы “Данные”</b>
          <span>Текущий поиск: “{dataSearch.trim()}”. Он применяется вместе с фильтрами столбцов, сортировкой и числом строк.</span>
        </section>
      )}
      {!scientometrics && (
        <EmptyState
          title={hasAuthorIndices ? "Нет аналитического пакета" : "Графики появятся после расчета индексов"}
          detail={hasAuthorIndices ? "Выберите расчет или локальный срез, затем дождитесь загрузки данных наукометрического анализа." : "Сейчас выбран только скачанный срез. Он пригоден для просмотра работ, но для статистики нужен авторский расчет."}
        />
      )}
      {scientometrics && Number(scientometrics.n_authors ?? 0) <= 0 && (
        <section className="notice warn action-notice">
          <div>
            <b>Графики пока не построены</b>
            <span>В выбранной области нет авторской таблицы индексов или текущие ограничения из “Данных” отфильтровали всех авторов. Откройте “Данные” → “Авторы и индексы”, проверьте строки, сбросьте ограничения или запустите расчет индексов для выбранного среза.</span>
          </div>
          {!hasAuthorIndices && (
            <button type="button" className="primary" onClick={onRecalculate} disabled={recalculating || !canRecalculate}>
              {recalculating ? <Loader2 size={16} className="spin" /> : <Sigma size={16} />} Рассчитать индексы
            </button>
          )}
        </section>
      )}
      {scientometrics && Number(scientometrics.n_authors ?? 0) > 0 && (
        <>
          <AnalyticsAuthorTablePanel
            table={analyticsAuthorTable}
            metrics={analyticsMetrics}
            metricLabels={metricLabels}
            dataFilters={dataFilters}
            setDataFilters={setDataFilters}
            dataSearch={dataSearch}
            setDataSearch={setDataSearch}
            dataSort={dataSort}
            setDataSort={setDataSort}
            dataDirection={dataDirection}
            setDataDirection={setDataDirection}
            selectedAuthorIds={selectedAuthorIds}
            setSelectedAuthorIds={setSelectedAuthorIds}
            topN={topN}
            setTopN={setTopN}
            onSelect={onSelect}
          />
          <DescriptiveStatsPanel
            payload={scientometrics}
            metrics={analyticsMetrics}
            metricLabels={metricLabels}
            downloads={analyticsDownloads}
            hasExportScope={hasAnalyticsExportScope}
          />
          <DistributionComparisonPanel
            payload={scientometrics}
            metrics={analyticsMetrics}
            metricLabels={metricLabels}
            highlightedAuthors={selectedAuthorRows}
            loading={loadingScientometrics}
          />
          <section className="panel">
            <div className="panel-head split">
              <div>
                <span className="step-badge">Диапазоны</span>
                <h2>Разброс значений</h2>
                <p>Ящик с усами показывает середину распределения, типичный диапазон и резко выделяющиеся значения по каждому индексу.</p>
              </div>
              <button type="button" className={showBoxplot ? "choice-pill active" : "choice-pill"} onClick={() => setShowBoxplot(!showBoxplot)}>
                {showBoxplot ? "Скрыть ящик с усами" : "Показать ящик с усами"}
              </button>
            </div>
            {showBoxplot && <MetricBoxplotPanel payload={scientometrics} metrics={analyticsMetrics} metricLabels={metricLabels} />}
          </section>
          <CorrelationMatrixPanel payload={scientometrics} method="spearman" metrics={analyticsMetrics} metricLabels={metricLabels} />
          <FindingsPanel payload={scientometrics} metricLabels={metricLabels} />
          <ConclusionDraftPanel payload={scientometrics} metricLabels={metricLabels} />
        </>
      )}
    </div>
  );
}

function DescriptiveStatsPanel({
  payload,
  metrics,
  metricLabels,
  downloads,
  hasExportScope,
}: {
  payload: ScientometricAnalysisPayload;
  metrics: string[];
  metricLabels?: Record<string, string>;
  downloads: Record<string, string>;
  hasExportScope: boolean;
}) {
  const rows = metrics
    .map((metricName) => {
      const descriptive = (payload.descriptive ?? {})[metricName] ?? {};
      const boxplot = (payload.boxplots ?? {})[metricName] ?? {};
      const hasData = Number(descriptive.n ?? 0) > 0 || [descriptive.median, descriptive.mean, boxplot.outlier_count].some((value) => Number.isFinite(Number(value)));
      return {
        metricName,
        n: Number(descriptive.n ?? 0),
        mean: numberOrNull(descriptive.mean),
        median: numberOrNull(descriptive.median ?? boxplot.median),
        q1: numberOrNull(descriptive.q1 ?? boxplot.q1),
        q3: numberOrNull(descriptive.q3 ?? boxplot.q3),
        min: numberOrNull(descriptive.min ?? boxplot.min_whisker),
        max: numberOrNull(descriptive.max ?? boxplot.max_whisker),
        stddev: numberOrNull(descriptive.stddev),
        outliers: Number(boxplot.outlier_count ?? 0),
        hasData,
      };
    })
    .filter((row) => row.hasData);
  const baselineMetric = String(payload.scope?.baseline_metric ?? "");
  return (
    <section className="panel">
      <div className="panel-head split">
        <div>
          <span className="step-badge">Сводная статистика</span>
          <h2>Статистические ориентиры по показателям</h2>
          <p>Эта таблица дает минимум, который нужен для чтения графиков: размер выборки, центр распределения, типичный диапазон, общий размах и число резко выделяющихся значений.</p>
        </div>
        <div className="download-inline">
          {hasExportScope && <DownloadLink href={downloads.descriptive} label="Сводная таблица" compact />}
          {hasExportScope && <DownloadLink href={downloads.correlations} label="Связь показателей" compact />}
          {hasExportScope && <DownloadLink href={downloads.findings} label="Выводы" compact />}
          {hasExportScope && <DownloadLink href={downloads.conclusion} label="Заключение" compact />}
        </div>
      </div>
      <div className="table-wrap stats-summary-table">
        <table>
          <thead>
            <tr>
              <th>Показатель</th>
              <th>Авторов</th>
              <th>Среднее</th>
              <th>Медиана</th>
              <th>Квартильный диапазон</th>
              <th>Мин–макс</th>
              <th>Стандартное отклонение</th>
              <th>Выделяющиеся</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.metricName} className={row.metricName === baselineMetric ? "summary-baseline-row" : undefined}>
                <td><b>{metricLabelFor(row.metricName, metricLabels)}</b>{row.metricName === baselineMetric ? <span className="muted-inline"> основной</span> : null}</td>
                <td>{fmt(row.n)}</td>
                <td>{formatNullableAnalysisValue(row.mean)}</td>
                <td>{formatNullableAnalysisValue(row.median)}</td>
                <td>{formatNullableRange(row.q1, row.q3)}</td>
                <td>{formatNullableRange(row.min, row.max)}</td>
                <td>{formatNullableAnalysisValue(row.stddev)}</td>
                <td>{fmt(row.outliers)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function formatNullableAnalysisValue(value: number | null) {
  return value === null ? "—" : formatAnalysisValue(value);
}

function formatNullableRange(left: number | null, right: number | null) {
  if (left === null && right === null) return "—";
  return `${formatNullableAnalysisValue(left)} – ${formatNullableAnalysisValue(right)}`;
}

function analysisWarningLabel(warning: string, metricLabels?: Record<string, string>) {
  const text = String(warning || "");
  const iqrMatch = text.match(/IQR is zero for metrics? ([^;.]+)[.;]/i);
  if (iqrMatch) {
    const metrics = iqrMatch[1]
      .split(/,\s*/)
      .map((item) => metricLabelFor(item.trim(), metricLabels))
      .join(", ");
    return `Для показателей ${metrics} межквартильный размах равен нулю; правило выделяющихся значений по ящику с усами здесь неинформативно.`;
  }
  if (/IQR outlier fences are not informative/i.test(text)) {
    return "Межквартильный размах равен нулю; границы выделяющихся значений по ящику с усами здесь неинформативны.";
  }
  return text;
}

function AnalyticsAuthorTablePanel({
  table,
  metrics,
  metricLabels,
  dataFilters,
  setDataFilters,
  dataSearch,
  setDataSearch,
  dataSort,
  setDataSort,
  dataDirection,
  setDataDirection,
  selectedAuthorIds,
  setSelectedAuthorIds,
  topN,
  setTopN,
  onSelect,
}: {
  table?: TableResponse;
  metrics: string[];
  metricLabels?: Record<string, string>;
  dataFilters: TableColumnFilters;
  setDataFilters: (value: TableColumnFilters) => void;
  dataSearch: string;
  setDataSearch: (value: string) => void;
  dataSort: string;
  setDataSort: (value: string) => void;
  dataDirection: "asc" | "desc";
  setDataDirection: (value: "asc" | "desc") => void;
  selectedAuthorIds: string[];
  setSelectedAuthorIds: (value: string[]) => void;
  topN: number;
  setTopN: (value: number) => void;
  onSelect: (value: { kind: "author" | "work"; id: string }) => void;
}) {
  const visibleAuthorIds = useMemo(() => [...new Set((table?.rows ?? []).map((row) => String(row.author_id ?? "").trim()).filter(Boolean))], [table?.rows]);
  const selectedSet = new Set(selectedAuthorIds);
  const allVisibleSelected = visibleAuthorIds.length > 0 && visibleAuthorIds.every((id) => selectedSet.has(id));
  const reset = () => {
    setDataFilters({});
    setDataSearch("");
    setDataSort("");
    setDataDirection("desc");
    setSelectedAuthorIds([]);
  };
  return (
    <section className="panel table-panel analytics-author-table">
      <div className="panel-head split">
        <div>
          <span className="step-badge">Авторы</span>
          <h2>Таблица авторов и рейтингов</h2>
          <p>Фильтры, сортировка и число строк в этой таблице сразу меняют графики и выводы ниже. Выбранные авторы показываются отдельными точками.</p>
        </div>
        <div className="download-inline">
          <button type="button" className="ghost-button" onClick={reset}>Сбросить</button>
        </div>
      </div>
      <div className="form-grid tight">
        <Field label="Поиск по авторам">
          <input value={dataSearch} onChange={(event) => setDataSearch(event.target.value)} placeholder="ФИО, организация, страна или ID" />
          <small className="field-hint">Поиск выполняется на backend по авторской таблице выбранного среза.</small>
        </Field>
        <Field label="Сколько авторов взять">
          <div className="limit-input-row">
            <input
              type="number"
              min={1}
              max={500000}
              value={topN > 0 ? String(topN) : ""}
              onChange={(event) => {
                const next = Number(event.target.value);
                setTopN(Number.isFinite(next) && next > 0 ? Math.floor(next) : 0);
              }}
              placeholder="Все"
            />
            <button type="button" className={topN <= 0 ? "choice-pill active" : "choice-pill"} onClick={() => setTopN(0)}>
              Все
            </button>
          </div>
          <small className="field-hint">Ограничение применяется после фильтров и сортировки.</small>
        </Field>
      </div>
      <div className="action-row">
        {visibleAuthorIds.length > 0 && (
          <button
            type="button"
            className={allVisibleSelected ? "choice-pill active" : "choice-pill"}
            onClick={() => setSelectedAuthorIds(allVisibleSelected ? [] : visibleAuthorIds)}
          >
            {allVisibleSelected ? "Убрать точки с графиков" : "Показать видимых авторов точками"}
          </button>
        )}
        {selectedAuthorIds.length > 0 && <span className="selection-chip passive">Выбрано авторов: {fmt(selectedAuthorIds.length)}</span>}
      </div>
      <DataRestrictionChips
        filters={dataFilters}
        sortField={dataSort}
        sortDirection={dataDirection}
        search={dataSearch}
        selectedAuthorIds={selectedAuthorIds}
        limit={topN}
        onResetSearch={() => setDataSearch("")}
        onRemoveFilter={(field) => {
          const next = { ...dataFilters };
          delete next[field];
          setDataFilters(next);
        }}
        onResetSort={() => {
          setDataSort("");
          setDataDirection("desc");
        }}
      />
      <DataGrid
        data={table}
        onSelect={onSelect}
        hiddenFields={["author_id"]}
        fieldLabels={metricLabels}
        sortField={dataSort}
        sortDirection={dataDirection}
        onSortChange={(field, direction) => {
          setDataSort(field);
          setDataDirection(direction);
        }}
        enableColumnFilters
        columnFilters={dataFilters}
        onColumnFiltersChange={setDataFilters}
        selectableRows
        selectedIds={selectedAuthorIds}
        selectionField="author_id"
        onSelectedIdsChange={setSelectedAuthorIds}
      />
      <p className="muted">Показатели в таблице: {metrics.map((item) => metricLabelFor(item, metricLabels)).join(", ")}.</p>
    </section>
  );
}

const CHART_COLORS = ["#155e75", "#167343", "#5b5fc7", "#0f766e", "#7c3aed", "#8a5a00", "#2563eb", "#64748b"];

function DistributionComparisonPanel({
  payload,
  metrics,
  metricLabels,
  highlightedAuthors,
  loading = false,
}: {
  payload: ScientometricAnalysisPayload;
  metrics: string[];
  metricLabels?: Record<string, string>;
  highlightedAuthors?: Record<string, unknown>[];
  loading?: boolean;
}) {
  const visibleMetrics = metrics.filter(Boolean);
  const rows = visibleMetrics
    .map((metricName) => ({ metricName, rows: rawDistributionRows(payload, metricName) }))
    .filter((item) => item.rows.length > 0);
  const highlightRows = selectedAuthorDistributionMarkers(payload, visibleMetrics, highlightedAuthors ?? []);
  const hasHighlights = highlightRows.length > 0;
  return (
    <section className="panel analytics-main-chart">
      <div className="panel-head split">
        <div>
          <span className="step-badge">Распределение</span>
          <h2>Распределение авторов по показателям</h2>
          <p>Каждый показатель показан отдельно в собственной шкале. По горизонтали — значение показателя, по вертикали — число авторов. Нижняя полоса позволяет приблизить нужный диапазон.</p>
        </div>
        {loading && <span className="status-chip"><Loader2 size={14} className="spin" /> Обновление</span>}
      </div>
      {hasHighlights && (
        <div className="selection-summary active">
          <span>Красные точки показывают авторов, выбранных в таблице выше.</span>
        </div>
      )}
      {visibleMetrics.length === 0 || rows.length === 0 ? (
        <EmptyState title="Выберите хотя бы один показатель" detail="Включите показатель во вкладке “Индексы” или в конструкторе собственной формулы." />
      ) : (
        <div className="distribution-small-multiples">
          {rows.map((item, index) => (
            <div key={item.metricName} className="distribution-multiple-card">
              <div className="distribution-multiple-head">
                <b>{metricLabelFor(item.metricName, metricLabels)}</b>
                <span>{fmt(item.rows.reduce((sum, row) => sum + row.count, 0))} авторов</span>
              </div>
              <div className="chart-box index-distribution-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={item.rows} margin={{ left: 8, right: 14, top: 8, bottom: 30 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e7edf4" />
                    <XAxis dataKey="center" type="number" tickFormatter={(value) => fmt(value)} domain={["dataMin", "dataMax"]} />
                    <YAxis allowDecimals={false} label={{ value: "Авторов", angle: -90, position: "insideLeft" }} />
                    <Tooltip
                      labelFormatter={(_, payloadRows) => {
                        const row = payloadRows?.[0]?.payload;
                        if (row?.author) return `${row.author}: ${formatAnalysisValue(row.value)}`;
                        return row ? `${formatAnalysisValue(row.lo)} – ${formatAnalysisValue(row.hi)}` : "";
                      }}
                      formatter={(value, _name, item: any) => {
                        if (item?.payload?.author) return [`${metricLabelFor(String(item.payload.metricName), metricLabels)}: ${formatAnalysisValue(item.payload.value)}`, "выбранный автор"];
                        return [fmt(value), "авторов"];
                      }}
                    />
                    <Area type="monotone" dataKey="count" fill={CHART_COLORS[index % CHART_COLORS.length]} fillOpacity={0.14} stroke="none" isAnimationActive={false} />
                    <Line type="monotone" dataKey="count" stroke={CHART_COLORS[index % CHART_COLORS.length]} strokeWidth={3} dot={false} activeDot={{ r: 4 }} name="Авторов" />
                    <Scatter
                      name="Выбранные авторы"
                      data={highlightRows.filter((row) => row.metricName === item.metricName)}
                      dataKey="count"
                      fill="#be123c"
                      shape="circle"
                    />
                    <Brush dataKey="center" height={18} travellerWidth={8} tickFormatter={(value) => fmt(value)} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

type DistributionMarker = {
  center?: number;
  count: number;
  value: number;
  metricName: string;
  author: string;
};

function selectedAuthorDistributionMarkers(
  payload: ScientometricAnalysisPayload,
  metrics: string[],
  authors: Record<string, unknown>[],
): DistributionMarker[] {
  if (!authors.length) return [];
  return metrics.flatMap((metricName) => {
    const bins = rawDistributionRows(payload, metricName);
    if (!bins.length) return [];
    const out: DistributionMarker[] = [];
    authors.forEach((author) => {
        const value = Number(author[metricName]);
        if (!Number.isFinite(value)) return;
        const authorName = String(author.author_display_name || author.author_id || "Выбранный автор");
        const nearest = nearestRawDistributionBin(bins, value);
        out.push({
          center: value,
          count: Math.max(1, Number(nearest?.count ?? 1)),
          value,
          metricName,
          author: authorName,
        });
      });
    return out;
  });
}

function nearestRawDistributionBin(rows: ReturnType<typeof rawDistributionRows>, value: number) {
  return rows.reduce<(typeof rows)[number] | null>((best, row) => {
    if (value >= row.lo && value <= row.hi) return row;
    if (!best) return row;
    return Math.abs(row.center - value) < Math.abs(best.center - value) ? row : best;
  }, null);
}

function rawDistributionRows(payload: ScientometricAnalysisPayload, metricName: string) {
  const histogram = ((payload.histograms ?? {})[metricName]?.raw ?? []) as Array<Record<string, unknown>>;
  return histogram
    .map((row, index) => ({
      lo: Number(row.lo),
      hi: Number(row.hi),
      center: (Number(row.lo) + Number(row.hi)) / 2,
      count: Number(row.count ?? 0),
      bin: index + 1,
    }))
    .filter((row) => Number.isFinite(row.center) && Number.isFinite(row.count) && row.count >= 0);
}

function MetricBoxplotPanel({ payload, metrics, metricLabels }: { payload: ScientometricAnalysisPayload; metrics: string[]; metricLabels?: Record<string, string> }) {
  const rows = metrics
    .map((metricName) => {
      const boxplot = (payload.boxplots ?? {})[metricName] ?? {};
      const min = numberOrNull(boxplot.min_whisker ?? boxplot.min);
      const q1 = numberOrNull(boxplot.q1);
      const median = numberOrNull(boxplot.median);
      const q3 = numberOrNull(boxplot.q3);
      const max = numberOrNull(boxplot.max_whisker ?? boxplot.max);
      if (![min, q1, median, q3, max].every((value) => value !== null)) return null;
      const outlierRows = ((payload.outliers ?? {})[metricName] ?? []) as Array<Record<string, unknown>>;
      const outlierValues = outlierRows.map((item) => Number(item.value)).filter(Number.isFinite).slice(0, 24);
      const left = Math.min(min as number, q1 as number, median as number, q3 as number, max as number, ...outlierValues);
      const right = Math.max(min as number, q1 as number, median as number, q3 as number, max as number, ...outlierValues);
      return {
        metricName,
        min: min as number,
        q1: q1 as number,
        median: median as number,
        q3: q3 as number,
        max: max as number,
        outliers: Number(boxplot.outlier_count ?? 0),
        outlierValues,
        domainMin: left,
        domainMax: right,
      };
    })
    .filter(Boolean) as Array<{
      metricName: string;
      min: number;
      q1: number;
      median: number;
      q3: number;
      max: number;
      outliers: number;
      outlierValues: number[];
      domainMin: number;
      domainMax: number;
    }>;
  if (!rows.length) {
    return <EmptyState title="Нет диапазонов" detail="Для выбранных индексов нет достаточного числа числовых значений." />;
  }
  return (
    <div className="boxplot-svg-list">
      {rows.map((row) => {
        const x = (value: number) => {
          const leftPad = 64;
          const rightPad = 38;
          const width = 1000 - leftPad - rightPad;
          if (row.domainMax <= row.domainMin) return leftPad + width / 2;
          return leftPad + ((value - row.domainMin) / (row.domainMax - row.domainMin)) * width;
        };
        const minX = x(row.min);
        const q1X = x(row.q1);
        const medianX = x(row.median);
        const q3X = x(row.q3);
        const maxX = x(row.max);
        const boxX = Math.min(q1X, q3X);
        const boxWidth = Math.max(4, Math.abs(q3X - q1X));
        return (
          <div key={row.metricName} className="boxplot-svg-row">
            <div className="boxplot-svg-title">
              <b>{metricLabelFor(row.metricName, metricLabels)}</b>
              <span>Q1 {formatAnalysisValue(row.q1)} · медиана {formatAnalysisValue(row.median)} · Q3 {formatAnalysisValue(row.q3)}{row.outliers ? ` · выделяющихся ${fmt(row.outliers)}` : ""}</span>
            </div>
            <svg viewBox="0 0 1000 88" role="img" aria-label={`Ящик с усами для ${metricLabelFor(row.metricName, metricLabels)}`} className="boxplot-svg">
              <line x1="64" y1="62" x2="962" y2="62" className="boxplot-axis" />
              {[row.domainMin, row.q1, row.median, row.q3, row.domainMax].map((value, index) => (
                <g key={`${row.metricName}-${index}-${value}`}>
                  <line x1={x(value)} y1="57" x2={x(value)} y2="67" className="boxplot-axis-tick" />
                  <text x={x(value)} y="82" textAnchor="middle">{formatAnalysisValue(value)}</text>
                </g>
              ))}
              <line x1={minX} y1="34" x2={maxX} y2="34" className="boxplot-whisker" />
              <line x1={minX} y1="22" x2={minX} y2="46" className="boxplot-cap" />
              <line x1={maxX} y1="22" x2={maxX} y2="46" className="boxplot-cap" />
              <rect x={boxX} y="18" width={boxWidth} height="32" rx="2" className="boxplot-box" />
              <line x1={medianX} y1="14" x2={medianX} y2="54" className="boxplot-median" />
              {row.outlierValues.map((value, index) => (
                <circle key={`${row.metricName}-outlier-${index}`} cx={x(value)} cy="34" r="4" className="boxplot-outlier">
                  <title>{`Выделяющееся значение: ${formatAnalysisValue(value)}`}</title>
                </circle>
              ))}
            </svg>
          </div>
        );
      })}
    </div>
  );
}

function numberOrNull(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function CorrelationMatrixPanel({ payload, method, metrics, metricLabels }: { payload: any; method: "spearman" | "pearson_log1p" | "kendall_tau_b"; metrics: string[]; metricLabels?: Record<string, string> }) {
  const matrix = method === "kendall_tau_b" ? payload?.correlations?.kendall_tau_b?.matrix ?? {} : payload?.correlations?.[method] ?? {};
  const skipped = payload?.correlations?.kendall_tau_b?.skipped ?? [];
  const visibleMetrics = metrics.filter((metricName) => matrix?.[metricName]);
  return (
    <section className="panel correlation-panel-wide">
      <div className="panel-head">
        <span className="step-badge">Связь показателей</span>
        <h2>{correlationLabel(method)} между рейтингами</h2>
        <p>Большая матрица показывает, насколько похоже упорядочиваются авторы по выбранным показателям. Значение ближе к 1 означает более похожий рейтинг.</p>
      </div>
      {method === "kendall_tau_b" && skipped.length > 0 && <div className="notice warn"><b>Часть пар не рассчитана</b><span>Слишком много наблюдений для выбранного способа сравнения. Уменьшите число строк или уточните фильтр во вкладке “Данные”.</span></div>}
      {visibleMetrics.length < 2 ? (
        <EmptyState title="Недостаточно показателей" detail="Для матрицы нужно выбрать минимум два показателя одной смысловой группы." />
      ) : (
        <div className="correlation-matrix-card wide">
          <div className="heatmap-grid compact-heatmap" style={{ gridTemplateColumns: `minmax(120px, 1fr) repeat(${visibleMetrics.length}, minmax(72px, 1fr))` }}>
            <span />
            {visibleMetrics.map((metricName) => <b key={metricName}>{metricShortLabel(metricName, metricLabels)}</b>)}
            {visibleMetrics.map((left) => (
              <div className="heatmap-row-fragment" key={left}>
                <b>{metricShortLabel(left, metricLabels)}</b>
                {visibleMetrics.map((right) => {
                  const value = matrix?.[left]?.[right];
                  return <span key={`${left}-${right}`} style={{ background: correlationColor(value) }}>{value === null || value === undefined ? "—" : fmt(value)}</span>;
                })}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function FindingsPanel({ payload, metricLabels }: { payload: ScientometricAnalysisPayload; metricLabels?: Record<string, string> }) {
  const findings = payload?.findings ?? [];
  const summary = payload?.finding_summary ?? {};
  if (!findings.length) return null;
  const priority: Record<string, number> = { high: 0, medium: 1, low: 2, informational: 3 };
  const visibleFindings = [...findings]
    .sort((left, right) => (priority[left.severity ?? ""] ?? 9) - (priority[right.severity ?? ""] ?? 9))
    .slice(0, 6);
  const groups: Array<[string, string]> = [
    ["high", "Важные замечания"],
    ["medium", "Требуют внимания"],
    ["low", "Дополнительные замечания"],
    ["informational", "Справочная информация"],
  ];
  return (
    <section className="panel">
      <div className="panel-head">
        <span className="step-badge">Выводы</span>
        <h2>Короткие выводы по показателям</h2>
        <p>Каждый вывод строится по текущей выборке из вкладки “Данные”. Это подсказка для отчета, не экспертное заключение.</p>
      </div>
      <div className="metric-grid">
        <MetricCard label="Выводов" value={fmt(Number(summary.n_findings ?? findings.length))} />
        <MetricCard label="Важных" value={fmt(Number(summary.high_count ?? 0))} />
        <MetricCard label="Требуют внимания" value={fmt(Number(summary.medium_count ?? 0))} />
        <MetricCard label="Рекомендуемый показатель" value={summary.candidate_metric ? metricLabelFor(String(summary.candidate_metric), metricLabels) : "—"} />
      </div>
      {groups.map(([severity, title]) => {
        const items = visibleFindings.filter((item) => item.severity === severity);
        if (!items.length) return null;
        return (
          <div key={severity} className="stack compact-stack">
            <h3>{title}</h3>
            {items.map((item) => (
              <div key={String(item.id)} className={findingNoticeClass(severity)}>
                <b>{findingTitle(item)}</b>
                <span>{String(item.text ?? "")}</span>
                {item.recommendation ? <small>{String(item.recommendation)}</small> : null}
                <div className="method-grid">
                  {findingEvidenceEntries(item.evidence).map(([key, value]) => (
                    <span key={key} className="check-pill">{evidenceLabel(key)}: {formatEvidenceValue(value)}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        );
      })}
      {findings.length > visibleFindings.length && (
        <div className="notice">
          <b>Показаны только ключевые выводы</b>
          <span>Полный список доступен через выгрузку “Таблица выводов”.</span>
        </div>
      )}
    </section>
  );
}

function ConclusionDraftPanel({ payload, metricLabels }: { payload: ScientometricAnalysisPayload; metricLabels?: Record<string, string> }) {
  const draft = payload?.conclusion_draft;
  const paragraphs = draft?.paragraphs ?? [];
  if (!draft || !paragraphs.length) return null;
  return (
    <section className="panel">
      <div className="panel-head">
        <span className="step-badge">Черновик заключения</span>
        <h2>{draft.title ?? "Черновик вывода"}</h2>
        <p>Текст собран из выводов текущей области анализа. Его можно использовать как основу раздела отчета после проверки таблиц и аналитических визуализаций.</p>
      </div>
      <div className="stack compact-stack">
        {paragraphs.map((paragraph, index) => (
          <div key={`${paragraph.role ?? "paragraph"}:${index}`} className="notice">
            <b>{conclusionRoleLabel(String(paragraph.role ?? ""))}</b>
            <span>{paragraph.text ?? ""}</span>
            {(paragraph.evidence_finding_ids ?? []).length > 0 && (
              <small>Основания: {(paragraph.evidence_finding_ids ?? []).join(", ")}</small>
            )}
            {(paragraph.evidence_metrics ?? []).length > 0 && (
              <small>Показатели: {(paragraph.evidence_metrics ?? []).map((item) => metricLabelFor(item, metricLabels)).join(", ")}</small>
            )}
          </div>
        ))}
      </div>
      {(draft.limitations ?? []).length > 0 && (
        <div className="notice warn">
          <b>Ограничения вывода</b>
          <ul className="plain-list">
            {(draft.limitations ?? []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      )}
    </section>
  );
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

function ensureCurrentOptions(options: SelectOption[], values: string[]) {
  const missing = values
    .filter((value) => value && !options.some((item) => item.value === value))
    .map((value) => ({ value, label: metricLabel(value) }));
  return [...missing, ...options];
}

function formatAnalysisValue(value: unknown, rate = false) {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return rate ? `${fmt(numeric * 100)}%` : fmt(numeric);
}

function findingNoticeClass(severity: string) {
  if (severity === "high") return "notice error";
  if (severity === "medium") return "notice warn";
  return "notice";
}

function findingTitle(finding: ScientometricFinding) {
  const metric = finding.metric ? metricLabel(String(finding.metric)) : "область анализа";
  const baseline = finding.baseline_metric ? `${metricLabel(String(finding.baseline_metric))} → ` : "";
  return `${findingSeverityLabel(String(finding.severity ?? ""))} · ${baseline}${metric} · ${findingTypeLabel(String(finding.type ?? ""))}`;
}

function findingSeverityLabel(value: string) {
  const labels: Record<string, string> = {
    high: "Важно",
    medium: "Внимание",
    low: "Дополнительно",
    informational: "Справочно",
  };
  return labels[value] ?? value;
}

function findingTypeLabel(value: string) {
  const labels: Record<string, string> = {
    heavy_tail_distribution: "есть резко высокие значения",
    zero_inflation: "много нулевых значений",
    high_tie_rate: "много одинаковых мест",
    publication_volume_dependence: "зависимость от числа публикаций",
    citation_volume_dependence: "зависимость от числа цитирований",
    top1_dominance_dependence: "зависимость от самой цитируемой работы",
    rank_instability: "места сильно меняются",
    rank_agreement: "места совпадают",
    balanced_candidate_metric: "рекомендуемый показатель",
    productivity_metric: "продуктивность",
    citation_volume_metric: "объем цитирования",
  };
  return labels[value] ?? value;
}

function conclusionRoleLabel(value: string) {
  const labels: Record<string, string> = {
    scope: "Область анализа",
    distribution_limits: "Распределения",
    index_limitations: "Различающая способность",
    dependence_limits: "Зависимости показателей",
    correction_effects: "Поправки к показателям",
    rank_comparison: "Сравнение мест",
    candidate_metric: "Рекомендуемый показатель",
    no_data: "Нет данных",
    final_caution: "Ограничение интерпретации",
  };
  return labels[value] ?? value;
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

function findingEvidenceEntries(value: unknown) {
  if (!value || typeof value !== "object") return [] as Array<[string, unknown]>;
  return Object.entries(value as Record<string, unknown>)
    .filter(([, item]) => item === null || ["string", "number", "boolean"].includes(typeof item))
    .slice(0, 5);
}

function evidenceLabel(value: string) {
  const labels: Record<string, string> = {
    skewness: "перекос распределения",
    excess_kurtosis: "резкие крайние значения",
    jarque_bera_p_approx: "отклонение от обычной формы",
    zero_rate: "нулевых",
    tie_rate: "одинаковых мест",
    abs_spearman_rho: "сила связи",
    spearman_rho: "связь показателей",
    direction: "направление",
    p90_abs_delta: "90% изменений",
    median_abs_delta: "медиана изменений",
    jaccard_top_n_exact: "совпадение первых строк",
    rank_top_n: "первые строки",
  };
  return labels[value] ?? value;
}

function formatEvidenceValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "да" : "нет";
  return formatAnalysisValue(value);
}

function metricShortLabel(value: string, metricLabels?: Record<string, string>) {
  if (metricLabels?.[value]) return metricLabels[value];
  const labels: Record<string, string> = {
    p: "Публикации",
    c: "Цитирования",
    c_frac: "Долевые цит.",
    cpp: "Средняя цит.",
    h: "Хирш",
    i10: "10+ цит.",
    g: "Индекс g",
    m_local: "Индекс m",
    top1_share: "Топ-1",
    f5: "Полянин f5",
    fm5: "Полянин fm5",
    iupv: "Собственный интегр.",
    islv: "Собственный сбал.",
    lrdi: "Устойчивость",
  };
  return labels[value] ?? value;
}

function correlationLabel(method: "spearman" | "pearson_log1p" | "kendall_tau_b") {
  if (method === "pearson_log1p") return "Связь численных значений";
  if (method === "kendall_tau_b") return "Совпадение порядка авторов";
  return "Связь мест в рейтинге";
}

function correlationColor(value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "#f3f6f9";
  const alpha = Math.min(0.42, Math.max(0.08, Math.abs(numeric) * 0.32 + 0.1));
  return numeric >= 0 ? `rgba(22, 115, 67, ${alpha})` : `rgba(21, 94, 117, ${alpha})`;
}
