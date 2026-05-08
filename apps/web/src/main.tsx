import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { createRoot } from "react-dom/client";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  BarChart3,
  CheckCircle2,
  Database,
  Download,
  Gauge,
  Info,
  Layers3,
  Lock,
  Loader2,
  Search,
  Settings2,
  Sigma,
  UploadCloud,
  Wrench,
  X,
} from "lucide-react";
import { Area, Brush, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { API_BASE, deleteJson, getJson, postJson, type CustomMetricDefinition, type TableColumnFilters, type TableResponse } from "./api";
import {
  DEFAULT_FILTERS,
  CORE_METRIC_OPTIONS,
  FRACTION_MODE_OPTIONS,
  columnLabel,
  countryLabel,
  filterParams,
  fmt,
  metricDescription,
  metricFormula,
  modeLabel,
  resolveCountryInput,
  metricLabel,
  workTypeLabel,
  type ActiveFilters,
  type OrganizationPreset,
  type ResearchAreaPreset,
  type SelectOption,
} from "./domain";
import { DataGrid, DetailDrawer, EmptyState } from "./components/ui";
import {
  analyticsRankingUrl,
  buildAnalysisRunPayload,
  buildDownloadPolicy,
  buildSliceDefinitionPayload,
  bytesToMb,
  effectiveUiScope,
  filtersFromSlicePayload,
  humanSliceTitle,
  localDataPreviewCsvUrl,
  localDataPreviewUrl,
  localDataMissingScopeState,
  localDataSummaryUrl,
  mutationError,
  pageLead,
  pageTitle,
  progressForRun,
  scientometricsUrl,
  dataSelectionQuery,
  customMetricDefsQuery,
  sliceSubjectTitle,
  viewFromHash,
  type EntitySuggestion,
  type LocalDataKind,
  type LocalDataSummary,
  type ResolverTab,
  type ScientometricAnalysisPayload,
  type ScientometricFinding,
  type View,
  type WorkbenchActiveContext,
  type WorkbenchRun,
  type WorkbenchState,
} from "./workbench";
import "./styles.css";

type ToastTone = "error" | "success" | "info";
type ToastPayload = { title: string; message: string; tone?: ToastTone; key?: string };
type ToastItem = ToastPayload & { id: string; tone: ToastTone };

const TOAST_EVENT = "openalex-dss-toast";
const toastDedupe = new Map<string, number>();

function emitToast(payload: ToastPayload) {
  if (typeof window === "undefined") return;
  const message = String(payload.message || "").trim();
  if (!message) return;
  const key = payload.key ?? `${payload.title}:${message}`;
  const now = Date.now();
  if (now - (toastDedupe.get(key) ?? 0) < 5_000) return;
  toastDedupe.set(key, now);
  window.dispatchEvent(new CustomEvent<ToastPayload>(TOAST_EVENT, { detail: { ...payload, message, key } }));
}

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

const NAV: Array<{ id: View; label: string; icon: ReactNode }> = [
  { id: "slices", label: "Срез", icon: <Layers3 size={17} /> },
  { id: "data", label: "Данные", icon: <Database size={17} /> },
  { id: "rankings", label: "Индексы", icon: <Sigma size={17} /> },
  { id: "statistics", label: "Аналитика", icon: <BarChart3 size={17} /> },
  { id: "reports", label: "Отчеты", icon: <Download size={17} /> },
];

type WorkflowNavItem = {
  id: View;
  label: string;
  icon: ReactNode;
  index: number;
  unlocked: boolean;
  complete: boolean;
  active: boolean;
  reason: string;
  fallback: View;
};

const COMMON_RANKING_METRICS = new Set(["p", "c", "c_frac", "cpp", "h", "i10", "g", "m_local", "f5", "fm5", "iupv", "islv", "lrdi"]);
const DATA_PREVIEW_PAGE_SIZE = 100;
const DATA_ONLY_ANALYSIS_FILTERS: ActiveFilters = {
  ...DEFAULT_FILTERS,
  filter_mode: "",
  from_publication_date: "",
  to_publication_date: "",
  affiliation_mode: "",
};
const DEFAULT_CUSTOM_METRICS: CustomMetricDefinition[] = [
  {
    id: "custom_added_rating",
    label: "Пример собственного рейтинга",
    description: "Пример собственной формулы: сводный рейтинг по процентилям публикаций, индекса Хирша и долевых цитирований.",
    expression: "100 * (pr_p * pr_h * pr_c_frac) ** (1 / 3)",
  },
];

function buildWorkflowNav({
  view,
  scopeReady,
  hasAvailableLocalTables,
  hasAuthorIndices,
  running,
}: {
  view: View;
  scopeReady: boolean;
  hasAvailableLocalTables: boolean;
  hasAuthorIndices: boolean;
  running: boolean;
}): WorkflowNavItem[] {
  const reasons: Partial<Record<View, string>> = {
    data: "Сначала выберите или скачайте срез",
    rankings: "Сначала выберите или скачайте срез",
    statistics: running ? "Дождитесь завершения текущей задачи" : "Сначала рассчитайте индексы",
    reports: running ? "Дождитесь завершения текущей задачи" : "Сначала рассчитайте индексы",
  };
  const unlocked: Record<View, boolean> = {
    slices: true,
    data: scopeReady,
    rankings: scopeReady,
    statistics: scopeReady && hasAuthorIndices && !running,
    reports: scopeReady && hasAuthorIndices && !running,
  };
  const complete: Record<View, boolean> = {
    slices: scopeReady,
    data: scopeReady && hasAvailableLocalTables,
    rankings: scopeReady && hasAuthorIndices,
    statistics: scopeReady && hasAuthorIndices,
    reports: scopeReady && hasAuthorIndices,
  };
  return NAV.map((item, index) => {
    const fallback: View = !scopeReady ? "slices" : !hasAuthorIndices && (item.id === "statistics" || item.id === "reports") ? "rankings" : "slices";
    return {
      ...item,
      index: index + 1,
      unlocked: unlocked[item.id],
      complete: complete[item.id] && item.id !== view && !running,
      active: item.id === view,
      reason: reasons[item.id] ?? "",
      fallback,
    };
  });
}

function nextUnlockedNavIndex(items: WorkflowNavItem[], current: number, key: string) {
  const direction = key === "ArrowDown" || key === "ArrowRight" ? 1 : key === "ArrowUp" || key === "ArrowLeft" ? -1 : 0;
  if (key === "Home") return items.findIndex((item) => item.unlocked);
  if (key === "End") {
    const reversedIndex = [...items].reverse().findIndex((item) => item.unlocked);
    return reversedIndex < 0 ? undefined : items.length - 1 - reversedIndex;
  }
  if (!direction) return undefined;
  for (let index = current + direction; index >= 0 && index < items.length; index += direction) {
    if (items[index].unlocked) return index;
  }
  return current;
}

function App() {
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
  const [sliceDoc, setSliceDoc] = useState<any>(null);
  const [estimate, setEstimate] = useState<any>(null);
  const [materialization, setMaterialization] = useState<any>(null);
  const [runId, setRunId] = useState("");
  const [dumpId, setDumpId] = useState("");
  const [resolverOpen, setResolverOpen] = useState(false);
  const [selected, setSelected] = useState<{ kind: "author" | "work"; id: string } | null>(null);
  const [localDataKind, setLocalDataKind] = useState<LocalDataKind>("indices");
  const [dataColumnFilters, setDataColumnFilters] = useState<TableColumnFilters>({});
  const [dumpInfo, setDumpInfo] = useState<any | null>(null);
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

  const registry = useQuery({ queryKey: ["registry"], queryFn: () => getJson<any>("/registry") });
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => getJson<any>("/catalog") });
  const workbench = useQuery({ queryKey: ["workbench"], queryFn: () => getJson<WorkbenchState>("/workbench") });
  const dumps = useQuery({ queryKey: ["dumps"], queryFn: () => getJson<any>("/dumps?limit=50") });
  const countries = useQuery({ queryKey: ["countries"], queryFn: () => getJson<any>("/openalex/countries?limit=50") });
  const workTypes = useQuery({ queryKey: ["work-types"], queryFn: () => getJson<any>("/openalex/work-types?limit=50") });
  const rateLimit = useQuery({
    queryKey: ["openalex-rate-limit", apiKey],
    queryFn: () => getJson<any>(`/openalex/rate-limit?api_key=${encodeURIComponent(apiKey.trim())}`),
    enabled: Boolean(apiKey.trim()),
  });
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getJson<any>(`/runs/${runId}`),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = (query.state.data as any)?.status;
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
  const uiScope = effectiveUiScope({
    runId,
    dumpId: activeDumpId,
    activeContext: workbench.data?.active_context,
  });
  const effectiveRunId = uiScope.runId;
  const effectiveDumpId = uiScope.dumpId;
  const usingActiveContextScope = uiScope.source === "active_context";
  const scopeReady = Boolean(effectiveRunId || effectiveDumpId);
  const dataFilterKey = useMemo(() => JSON.stringify(dataColumnFilters), [dataColumnFilters]);
  const customMetricKey = useMemo(() => JSON.stringify(customMetrics), [customMetrics]);
  const analysisFilters = useMemo(() => DATA_ONLY_ANALYSIS_FILTERS, []);
  const dataSelection = useMemo(() => ({
    filters: dataColumnFilters,
    search: dataSearch,
    sort: dataSort,
    direction: dataDirection,
    limit: topN,
    authorIds: [],
  }), [dataColumnFilters, dataSearch, dataSort, dataDirection, topN]);
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
  const hasAuthorIndices = Boolean((localDataSummary.data?.tables as any)?.indices?.exists);
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
    enabled: scopeReady && Boolean((localDataSummary.data?.tables as any)?.indices?.exists),
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
    queryFn: () => getJson<any>(
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
  const topNOptions = configuredOptions(uiOptions.top_n ?? []);
  const metricCatalogOptions = configuredOptions(catalog.data?.metrics ?? []);
  const configuredPrimaryMetricOptions = metricCatalogOptions
    .filter((item) => COMMON_RANKING_METRICS.has(item.value))
    .map((item) => ({ ...item, label: metricLabel(item.value), description: item.description || metricDescription(item.value) }));
  const primaryMetricOptions = configuredPrimaryMetricOptions.length ? configuredPrimaryMetricOptions : CORE_METRIC_OPTIONS;
  const customMetricOptions: SelectOption[] = customMetrics.map((item) => ({
    value: item.id,
    label: item.label,
    description: item.description || "Собственная формула по данным выбранного среза.",
    formula: item.expression,
    custom: true,
  }));
  const allMetricOptions = [...primaryMetricOptions, ...customMetricOptions];
  const metricLabelMap = Object.fromEntries(allMetricOptions.map((item) => [item.value, item.label]));
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
    mutationFn: (body: any) => postJson<any>("/slices", body),
    onSuccess: (doc) => {
      setSliceDoc(doc);
      qc.invalidateQueries({ queryKey: ["workbench"] });
    },
  });
  const estimateSlice = useMutation({
    mutationFn: async () => {
      const doc = await postJson<any>("/slices", { ...slicePayload, title: humanSliceTitle(filters) });
      setSliceDoc(doc);
      const result = await postJson<any>(`/slices/${encodeURIComponent(doc.slice_id)}/estimate`, { download_policy: downloadPolicy });
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
      const doc = sliceDoc ?? (await postJson<any>("/slices", { ...slicePayload, title: humanSliceTitle(filters) }));
      setSliceDoc(doc);
      return postJson<any>(`/slices/${encodeURIComponent(doc.slice_id)}/materialization-plans`, { storage_profile_id: activeStorageProfileId, source_strategy: activeSourceStrategy, download_policy: downloadPolicy, download_dir: downloadDir.trim() || undefined });
    },
    onSuccess: (plan) => {
      setMaterialization(plan);
      qc.invalidateQueries({ queryKey: ["workbench"] });
    },
  });
  const runMaterialization = useMutation({
    mutationFn: async () => {
      const plan = materialization ?? (await createMaterialization.mutateAsync());
      return postJson<any>(`/materializations/${encodeURIComponent(plan.materialization_id)}/run`, materializationRunPayload(apiKey, downloadDir, maxDownloadMb));
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
      const doc = await postJson<any>("/slices", { ...slicePayload, title: humanSliceTitle(filters) });
      setSliceDoc(doc);
      const estimateResult = await postJson<any>(`/slices/${encodeURIComponent(doc.slice_id)}/estimate`, { download_policy: downloadPolicy });
      setEstimate(estimateResult);
      setSliceDoc({ ...doc, current_estimate: estimateResult, state: "estimated" });
      const decision = estimateResult?.decision ?? {};
      if (decision.can_execute === false) {
        const reason = [...(decision.reasons ?? []), ...(decision.warnings ?? [])].filter(Boolean).join(" ");
        throw new Error(reason || "OpenAlex не вернул работ для выбранных фильтров.");
      }
      const plan = await postJson<any>(`/slices/${encodeURIComponent(doc.slice_id)}/materialization-plans`, { storage_profile_id: activeStorageProfileId, source_strategy: activeSourceStrategy, download_policy: downloadPolicy, download_dir: downloadDir.trim() || undefined });
      setMaterialization(plan);
      return postJson<any>(`/materializations/${encodeURIComponent(plan.materialization_id)}/run`, materializationRunPayload(apiKey, downloadDir, maxDownloadMb));
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
    mutationFn: (nextDumpId: string) => deleteJson<any>(`/dumps/${encodeURIComponent(nextDumpId)}`),
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
    mutationFn: (nextDumpId: string) => postJson<any>(`/dumps/${encodeURIComponent(nextDumpId)}/select`, {}),
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
    mutationFn: (nextDumpId: string) => postJson<any>(`/dumps/${encodeURIComponent(nextDumpId)}/repair`, {}),
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
      return postJson<any>("/runs", {
        action: "recalculate",
        payload: {
          dump_id: effectiveDumpId,
          ...analysisRunPayload,
        },
      });
    },
    onSuccess: (result) => {
      setRunId(result.run_id);
      setDumpId("");
      navigate("rankings");
    },
  });
  const cancelRun = useMutation({
    mutationFn: (nextRunId: string) => postJson<any>(`/runs/${encodeURIComponent(nextRunId)}/cancel`, {}),
    onSuccess: (result) => {
      setRunId(String(result?.run_id ?? runId));
      qc.invalidateQueries({ queryKey: ["run", result?.run_id ?? runId] });
    },
  });
  const buildReport = useMutation({
    mutationFn: () => postJson<any>(`/reports/build?${filterParams(analysisFilters, {
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
  const selectDownloadedDump = (dump: any) => {
    const nextDumpId = String(dump?.dump_id ?? "");
    const slice = (workbench.data?.slices ?? []).find((item: any) => String(item.slice_id ?? "") === String(dump?.slice_id ?? ""));
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
            onEstimate={() => estimateSlice.mutate()}
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
          <LocalDataPage
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
  onEstimate: () => void;
  estimate: any;
  materialization: any;
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
  rateLimit: any;
  onRun: () => void;
  onCancelRun: () => void;
  estimating: boolean;
  materializing: boolean;
  downloadConfigReady: boolean;
  run: any;
  sliceDoc: any;
  downloadedDumps: any[];
  onSelectDownloadedDump: (dump: any) => void;
  onShowDumpInfo: (dump: any) => void;
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
  const rawEstimate = estimate?.estimate ?? {};
  const hasEstimate = Boolean(estimate);
  const canRun = hasEstimate && decision.can_execute !== false;
  const noDataEstimate = hasEstimate && (decision.status === "no_data" || Number(rawEstimate.estimate_count ?? 0) === 0);
  const emptyEstimateValue = hasEstimate ? "0" : "—";
  const apiKeyReady = Boolean(apiKey.trim()) || backendCliApiKeyConfigured;
  const sliceRows = buildDownloadedSliceRows(downloadedDumps).slice(0, 20);
  const selectSliceRow = (row: UnifiedSliceRow) => {
    if (row.selectDisabled) {
      emitToast({ title: "Срез пока недоступен", message: row.status.reason || "Сначала восстановите локальные файлы среза.", tone: row.status.tone === "error" ? "error" : "info" });
      return;
    }
    if (row.dump) {
      onSelectDownloadedDump(row.dump);
      return;
    }
  };
  const deleteSliceRow = (row: UnifiedSliceRow) => {
    if (!window.confirm(`Удалить локальный срез “${row.title}”? Будут удалены скачанные файлы и таблицы этого среза.`)) return;
    row.dumpIds.forEach(onDeleteDownloadedDump);
  };
  const repairSliceRow = (row: UnifiedSliceRow) => {
    const dumpId = row.dumpIds[0];
    if (dumpId) onRepairDownloadedDump(dumpId);
  };

  return (
    <div className="stack">
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
          <button className="primary" onClick={onEstimate} disabled={estimating || dateInvalid || subjectMissing}>{estimating ? <Loader2 size={16} className="spin" /> : <Gauge size={16} />} {estimating ? "Оцениваем..." : "Оценить объем"}</button>
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
          <button onClick={onEstimate} disabled={estimating || dateInvalid || subjectMissing}>{estimating ? <Loader2 size={16} className="spin" /> : <Gauge size={16} />} {estimating ? "Оцениваем..." : "Обновить оценку"}</button>
        </div>
        <div className="metric-grid">
          <MetricCard label="Работ найдено" value={hasEstimate ? fmt(rawEstimate.estimate_count ?? 0) : "—"} />
          <MetricCard label="Полный срез / к загрузке" value={hasEstimate ? `${fmt(rawEstimate.estimate_count ?? 0)} / ${fmt(decision.records_to_fetch ?? rawEstimate.planned_records ?? 0)}` : "—"} />
          <MetricCard label="API-запросов" value={hasEstimate ? fmt(decision.api_requests_planned ?? rawEstimate.api_requests_planned ?? 0) : "—"} />
          <MetricCard label="Прогноз загрузки" value={hasEstimate ? `${fmt(rawEstimate.estimated_cli_metadata_mb ?? decision.estimated_raw_mb ?? rawEstimate.estimated_raw_mb ?? 0)} МБ` : emptyEstimateValue} />
          <MetricCard label="Прогноз предпросмотра" value={hasEstimate ? `${fmt(rawEstimate.estimated_selected_api_mb ?? rawEstimate.estimated_raw_mb ?? 0)}–${fmt(rawEstimate.estimated_raw_mb_p90 ?? decision.estimated_raw_mb ?? 0)} МБ` : emptyEstimateValue} />
          <MetricCard label="Parquet прогноз" value={hasEstimate ? `${fmt(rawEstimate.estimated_parquet_mb ?? 0)} МБ` : emptyEstimateValue} />
        </div>
        <EstimateBudget estimate={rawEstimate} decision={decision} />
        <EstimateFacets facets={rawEstimate.facets} />
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

type UnifiedSliceRow = {
  key: string;
  title: string;
  meta: string;
  detail: string;
  action: string;
  status: { status: string; label: string; tone: "ok" | "warn" | "error" | "info"; reason?: string };
  selectDisabled?: boolean;
  repairAction?: string;
  sliceId: string;
  dumpIds: string[];
  slice?: any;
  materialization?: any;
  dump?: any;
};

function buildDownloadedSliceRows(downloadedDumps: any[]): UnifiedSliceRow[] {
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

function dumpHealth(dump: any): { status: string; label: string; tone: "ok" | "warn" | "error" | "info"; reason?: string; repairAction?: string } {
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

function downloadedSliceTitle(dump: any) {
  const title = String(dump?.title ?? dump?.slice_title ?? "").trim();
  if (title) return title;
  const subject = String(dump?.subject_name ?? dump?.filters?.subject_name ?? "").trim();
  const period = [dump?.from_publication_date, dump?.to_publication_date].map((item) => String(item ?? "").trim()).filter(Boolean).join("–");
  const dumpId = String(dump?.dump_id ?? "").trim();
  return [subject || "Локальный срез", period, dumpId ? dumpId.replace(/^dump_/, "") : ""].filter(Boolean).join(" · ");
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

function activeRepairDumpId(run: any, pendingDumpId: unknown) {
  const pending = String(pendingDumpId ?? "");
  const status = String(run?.status ?? "");
  const action = String(run?.action ?? "");
  if (action !== "repair_dump" || !["queued", "running", "cancelling"].includes(status)) return pending;
  return String(run?.payload?.dump_id ?? pending);
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

function DumpInfoModal({ dump, onClose }: { dump: any; onClose: () => void }) {
  const health = dumpHealth(dump);
  const request = dump?.openalex_request ?? {};
  const storage = dump?.storage_plan ?? {};
  const signatures = dump?.signatures ?? {};
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
          <KeyValue label="Размер файла" value={`${fmt(bytesToMb(Number(dump?.bytes_written ?? 0)))} МБ`} />
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
          <KeyValue label="Папка загрузки" value={String(storage?.download_base_dir ?? "—")} />
          <KeyValue label="Файл среза" value={rawPath || "—"} />
          <KeyValue label="Папка файлов OpenAlex" value={String(dump?.cli_files_dir ?? storage?.cli_output_dir ?? "—")} />
          <KeyValue label="Паспорт загрузки" value={manifestPath || "—"} />
          <KeyValue label="Список файлов" value={String(dump?.files_manifest ?? "—")} />
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

function LocalDataPage({
  localDataSummary,
  localDataKind,
  setLocalDataKind,
  localDataKindOptions,
  dataColumnFilters,
  setDataColumnFilters,
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
  topNOptions,
  dataOffset,
  setDataOffset,
  pageSize,
  table,
  csvUrl,
  run,
  running,
  activeContext,
  usingActiveContextScope,
  effectiveRunId,
  effectiveDumpId,
  onRefresh,
  onSelect,
}: {
  localDataSummary?: LocalDataSummary;
  localDataKind: LocalDataKind;
  setLocalDataKind: (value: LocalDataKind) => void;
  localDataKindOptions: SelectOption[];
  dataColumnFilters: TableColumnFilters;
  setDataColumnFilters: (value: TableColumnFilters) => void;
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
  topNOptions: SelectOption[];
  dataOffset: number;
  setDataOffset: (value: number) => void;
  pageSize: number;
  table?: TableResponse;
  csvUrl: string;
  run: any;
  running: boolean;
  activeContext?: WorkbenchActiveContext;
  usingActiveContextScope: boolean;
  effectiveRunId: string;
  effectiveDumpId: string;
  onRefresh: () => void;
  onSelect: (value: { kind: "author" | "work"; id: string }) => void;
}) {
  const missingScope = localDataMissingScopeState({ runId: effectiveRunId, dumpId: effectiveDumpId, activeContext });
  const availableTables = Object.values(localDataSummary?.tables ?? {}).filter((entry: any) => Boolean(entry?.exists));
  const hasAvailableTables = localDataKindOptions.length > 0;
  const hasTableRestrictions = Boolean(Object.keys(dataColumnFilters).length || dataSearch.trim() || dataSort || dataDirection !== "desc");
  const hasDataRestrictions = hasTableRestrictions || selectedAuthorIds.length > 0;
  const rowsOnPage = table?.rows?.length ?? 0;
  const totalExact = table?.total_exact !== false && table?.total !== null && table?.total !== undefined;
  const rawTotal = Number(table?.total ?? 0);
  const selectedTotal = totalExact ? (topN > 0 ? Math.min(rawTotal, topN) : rawTotal) : null;
  const pageStart = rowsOnPage ? dataOffset + 1 : 0;
  const pageEndRaw = rowsOnPage ? dataOffset + rowsOnPage : 0;
  const pageEnd = selectedTotal !== null && selectedTotal > 0 ? Math.min(pageEndRaw, selectedTotal) : pageEndRaw;
  const canPrevPage = dataOffset > 0;
  const canNextPage = totalExact
    ? selectedTotal !== null && selectedTotal > 0 && pageEnd < selectedTotal
    : Boolean(table?.has_more) && (topN <= 0 || pageEndRaw < topN);
  const paginationText = rowsOnPage
    ? totalExact && selectedTotal !== null
      ? `Показаны строки ${fmt(pageStart)}-${fmt(pageEnd)} из ${fmt(selectedTotal)}`
      : `Показаны строки ${fmt(pageStart)}-${fmt(pageEnd)}${table?.has_more ? " · есть следующие строки" : " · конец выборки"}`
    : "Строк нет";
  const limitText = totalExact && topN > 0 && rawTotal > topN ? ` (ограничено до ${fmt(topN)})` : "";
  const visibleAuthorIds = useMemo(() => {
    if (localDataKind !== "indices") return [];
    return [...new Set((table?.rows ?? []).map((row) => String(row.author_id ?? "").trim()).filter(Boolean))];
  }, [localDataKind, table?.rows]);
  const allVisibleAuthorsSelected = visibleAuthorIds.length > 0 && visibleAuthorIds.every((id) => selectedAuthorIds.includes(id));
  const resetDataRestrictions = () => {
    setDataColumnFilters({});
    setDataSearch("");
    setDataSort("");
    setDataDirection("desc");
    setSelectedAuthorIds([]);
  };
  return (
    <div className="stack">
      {availableTables.length > 0 && (
        <section className="metric-grid">
          {availableTables.map((entry: any) => (
            <MetricCard key={String(entry.kind)} label={String(entry.label || entry.kind)} value={fmt(entry.rows ?? 0)} />
          ))}
        </section>
      )}
      <ActiveContextPanel
        activeContext={activeContext}
        usingAsDefault={usingActiveContextScope}
        effectiveRunId={effectiveRunId}
        effectiveDumpId={effectiveDumpId}
      />
      {missingScope.missing && (
        <section className="notice warn">
          <b>Локальный срез не выбран</b>
          <span>{missingScope.detail}</span>
        </section>
      )}
      {!missingScope.missing && !hasAvailableTables && (
        <section className="notice warn">
          <b>В выбранном срезе нет доступных локальных таблиц</b>
          <span>Вкладка “Данные” показывает только файлы, которые реально существуют в скачанном срезе или созданном расчете. Выберите другой срез или запустите расчет индексов.</span>
        </section>
      )}
      <section className="panel table-panel">
        <div className="panel-head">
          <span className="step-badge">Просмотр таблицы</span>
          <h2>Данные текущей выборки</h2>
          <p>Здесь задаются таблица, ограничения по столбцам, сортировка и число строк. Индексы, аналитика и отчеты используют эту же выборку.</p>
          <button onClick={onRefresh}><Loader2 size={16} className={running ? "spin" : ""} /> Обновить</button>
        </div>
        {run && <RunCard run={run} />}
        {hasAvailableTables && (
          <div className="choice-grid compact table-kind-tabs" role="tablist" aria-label="Таблицы выбранного среза">
          {localDataKindOptions.map((item) => (
            <button
              key={item.value}
              type="button"
              role="tab"
              aria-selected={localDataKind === item.value}
              className={localDataKind === item.value ? "choice-pill active" : "choice-pill"}
              onClick={() => {
                setLocalDataKind(item.value as LocalDataKind);
                setDataColumnFilters({});
              }}
            >
              {item.label}
            </button>
          ))}
          </div>
        )}
        <div className="form-grid tight">
          <Field label="Поиск по таблице">
            <input value={dataSearch} onChange={(event) => setDataSearch(event.target.value)} placeholder="Автор, работа, организация, DOI..." />
            <small className="field-hint">Поиск применяется к текущей таблице вместе с ограничениями по столбцам.</small>
          </Field>
          <Field label={localDataKind === "indices" ? "Сколько авторов взять" : "Сколько строк взять"}>
            <div className="limit-input-row">
              <input
                type="number"
                min={1}
                max={500000}
                list="top-n-options"
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
            <datalist id="top-n-options">
              {topNOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </datalist>
            <small className="field-hint">Пустое поле означает “все”. Ограничение применяется после фильтров и сортировки; фильтры задаются нажатием на заголовок столбца.</small>
          </Field>
        </div>
        <div className="action-row">
          {!missingScope.missing && hasAvailableTables && <a className="button-link" href={csvUrl}>Скачать текущую выборку</a>}
          {localDataKind === "indices" && visibleAuthorIds.length > 0 && (
            <button
              type="button"
              className={allVisibleAuthorsSelected ? "choice-pill active" : "choice-pill"}
              onClick={() => setSelectedAuthorIds(allVisibleAuthorsSelected ? [] : visibleAuthorIds)}
            >
              {allVisibleAuthorsSelected ? "Снять точки с графиков" : "Показать всех авторов точками"}
            </button>
          )}
          {hasDataRestrictions && <button type="button" className="ghost-button" onClick={resetDataRestrictions}>{hasTableRestrictions ? "Сбросить ограничения" : "Снять точки"}</button>}
        </div>
        <DataRestrictionChips
          filters={dataColumnFilters}
          sortField={dataSort}
          sortDirection={dataDirection}
          search={dataSearch}
          selectedAuthorIds={selectedAuthorIds}
          limit={topN}
          onResetSearch={() => setDataSearch("")}
          onRemoveFilter={(field) => {
            const next = { ...dataColumnFilters };
            delete next[field];
            setDataColumnFilters(next);
          }}
          onResetSort={() => {
            setDataSort("");
            setDataDirection("desc");
          }}
        />
        {missingScope.missing ? (
          <EmptyState title="Нет выбранного локального среза" detail="Предпросмотр появится после выбора расчета, локального среза или после загрузки нового среза." />
        ) : !hasAvailableTables ? (
          <EmptyState title="Нет локальных таблиц" detail="В выбранном срезе пока нет скачанных таблиц или результатов расчета, которые можно показать." />
        ) : (
          <>
            <DataGrid
              data={table}
              onSelect={onSelect}
              hiddenFields={["slice_id"]}
              sortField={dataSort}
              sortDirection={dataDirection}
              onSortChange={(field, direction) => {
                setDataSort(field);
                setDataDirection(direction);
              }}
              enableColumnFilters
              columnFilters={dataColumnFilters}
              onColumnFiltersChange={setDataColumnFilters}
              selectableRows={localDataKind === "indices"}
              selectedIds={selectedAuthorIds}
              selectionField="author_id"
              onSelectedIdsChange={setSelectedAuthorIds}
            />
            <div className="table-pagination">
              <span>
                {paginationText}
                {limitText}
              </span>
              <div className="action-row compact">
                <button type="button" className="ghost-button" disabled={!canPrevPage} onClick={() => setDataOffset(Math.max(0, dataOffset - pageSize))}>
                  Назад
                </button>
                <button type="button" className="ghost-button" disabled={!canNextPage} onClick={() => setDataOffset(dataOffset + pageSize)}>
                  Вперед
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function DataRestrictionChips({
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
      {hasSelectedAuthors && (
        <span className="selection-chip passive">Точки на графиках: {fmt(selectedAuthorIds.length)}</span>
      )}
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

function authorCountText(count: number) {
  const value = Math.abs(Number(count) || 0);
  const mod10 = value % 10;
  const mod100 = value % 100;
  if (mod10 === 1 && mod100 !== 11) return `${fmt(count)} автор`;
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return `${fmt(count)} автора`;
  return `${fmt(count)} авторов`;
}

function ActiveContextPanel({
  activeContext,
  usingAsDefault,
  effectiveRunId,
  effectiveDumpId,
}: {
  activeContext?: WorkbenchActiveContext;
  usingAsDefault: boolean;
  effectiveRunId: string;
  effectiveDumpId: string;
}) {
  const hasScope = Boolean(effectiveRunId || effectiveDumpId || activeContext?.active_run_id || activeContext?.active_dump_id);
  if (!hasScope) return null;
  const eligibility = activeContextEligibility(activeContext?.allowed_for_final_analysis);
  return (
    <section className="panel">
      <div className="panel-head split">
        <div>
          <span className="step-badge">Выбранный срез</span>
          <h2>Активный локальный срез</h2>
          <p>Просмотр данных, индексов, графиков и отчетов использует этот срез, если расчет или локальный срез не выбран явно.</p>
        </div>
        <span className={eligibility.className}>{eligibility.label}</span>
      </div>
      <div className="metric-grid">
        <MetricCard label="Расчет" value={effectiveRunId || "не задан"} />
        <MetricCard label="Локальный срез" value={effectiveDumpId || "не задан"} />
        <MetricCard label="Источник" value={activeContextSourceLabel(activeContext?.source)} />
        <MetricCard label="Как выбран" value={usingAsDefault ? "автоматически" : "вручную"} />
      </div>
    </section>
  );
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
    queryFn: () => getJson<any>(`${endpoint}?q=${encodeURIComponent(query.trim())}&limit=10`),
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
              <small>{item.openalex_id ?? item.id} {item.ror ? `· ROR: ${item.ror}` : ""} {item.orcid ? `· ORCID: ${item.orcid}` : ""} {(item as any).doi ? `· DOI: ${(item as any).doi}` : ""}</small>
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
            <small>{picked.openalex_id ?? picked.id} {picked.ror ? `· ROR: ${picked.ror}` : ""} {picked.orcid ? `· ORCID: ${picked.orcid}` : ""} {(picked as any).doi ? `· DOI: ${(picked as any).doi}` : ""}</small>
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
  const doi = String((item as any).doi || "").trim();
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

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function MetricInfoPopover({ metric }: { metric: SelectOption }) {
  const iconRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const closeTimer = useRef<number | null>(null);
  const pinnedOpen = useRef(false);
  const [position, setPosition] = useState<{ left: number; top: number; width: number; maxHeight: number; placement: "top" | "bottom" } | null>(null);
  const metricName = metric.value;
  const description = metric.description || metricDescription(metricName);
  const formula = metric.formula || metricFormula(metricName);
  const label = metric.label || metricLabel(metricName);
  const clearCloseTimer = () => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  };
  const close = () => {
    clearCloseTimer();
    pinnedOpen.current = false;
    setPosition(null);
  };
  const scheduleClose = () => {
    if (pinnedOpen.current) return;
    clearCloseTimer();
    closeTimer.current = window.setTimeout(() => setPosition(null), 120);
  };
  const open = () => {
    clearCloseTimer();
    const rect = iconRef.current?.getBoundingClientRect();
    if (!rect) return;
    const gutter = 12;
    const width = Math.min(420, window.innerWidth - gutter * 2);
    const left = clamp(rect.right - width, gutter, Math.max(gutter, window.innerWidth - width - gutter));
    const spaceBelow = window.innerHeight - rect.bottom - gutter;
    const spaceAbove = rect.top - gutter;
    const placement: "top" | "bottom" = spaceBelow < 260 && spaceAbove > spaceBelow ? "top" : "bottom";
    const availableHeight = Math.max(180, placement === "bottom" ? spaceBelow - 8 : spaceAbove - 8);
    setPosition({
      left,
      top: placement === "bottom" ? rect.bottom + 8 : rect.top - 8,
      width,
      maxHeight: Math.min(360, availableHeight),
      placement,
    });
  };
  useEffect(() => {
    if (!position) return undefined;
    const reposition = () => open();
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (iconRef.current?.contains(target) || popoverRef.current?.contains(target)) return;
      close();
    };
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      clearCloseTimer();
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [position?.left, position?.top, position?.placement]);
  const togglePinned = () => {
    if (position && pinnedOpen.current) {
      close();
      return;
    }
    pinnedOpen.current = true;
    open();
  };
  const popover = position ? createPortal(
    <div
      ref={popoverRef}
      className={`metric-info-popover ${position.placement}`}
      role="tooltip"
      style={{ left: position.left, top: position.top, width: position.width, maxHeight: position.maxHeight }}
      onPointerEnter={clearCloseTimer}
      onPointerLeave={scheduleClose}
    >
      <b>{label}</b>
      {description && <span>{description}</span>}
      <MetricFormulaMath metricName={metricName} fallback={formula} />
      <small>Формула применяется только к текущему выбранному срезу.</small>
    </div>,
    document.body,
  ) : null;
  return (
    <span className="metric-info-popover-wrap">
      <button
        ref={iconRef}
        type="button"
        className="metric-info-icon"
        aria-label={`Описание показателя ${label}`}
        aria-expanded={Boolean(position)}
        onClick={togglePinned}
        onFocus={open}
        onBlur={scheduleClose}
        onPointerEnter={open}
        onPointerLeave={scheduleClose}
      >
        <Info size={14} />
      </button>
      {popover}
    </span>
  );
}

function MetricFormulaMath({ metricName, fallback }: { metricName: string; fallback: string }) {
  const markup = metricFormulaMarkup(metricName);
  if (markup) return <span className="formula-math" dangerouslySetInnerHTML={{ __html: markup }} />;
  return <code className="formula-fallback">{fallback}</code>;
}

function metricLabelFor(metricName: string, labels?: Record<string, string>) {
  return labels?.[metricName] ?? metricLabel(metricName);
}

const FORMULA_VARIABLES = [
  { token: "p", label: "Публикации" },
  { token: "c", label: "Цитирования" },
  { token: "c_frac", label: "Долевые цитирования" },
  { token: "cpp", label: "Средняя цитируемость" },
  { token: "h", label: "Индекс Хирша" },
  { token: "i10", label: "Работы с 10+ цитированиями" },
  { token: "g", label: "Индекс g" },
  { token: "m_local", label: "Индекс m" },
  { token: "f5", label: "Индекс Полянина f5" },
  { token: "fm5", label: "Долевой f5" },
  { token: "lrdi", label: "Индекс устойчивости" },
  { token: "pr_p", label: "Процентиль публикаций" },
  { token: "pr_h", label: "Процентиль Хирша" },
  { token: "pr_c_frac", label: "Процентиль долевых цитирований" },
  { token: "pr_g", label: "Процентиль g-индекса" },
];

const FORMULA_FUNCTIONS = ["sqrt()", "log1p()", "log()", "exp()", "pow()", "min()", "max()", "abs()", "round()", "floor()", "ceil()"];
const FORMULA_FUNCTION_NAMES = new Set(FORMULA_FUNCTIONS.map((item) => item.replace("()", "")));

function CustomMetricBuilder({
  metrics,
  setMetrics,
  selectedMetrics,
  setSelectedMetrics,
  activeMetric,
  setActiveMetric,
}: {
  metrics: CustomMetricDefinition[];
  setMetrics: (value: CustomMetricDefinition[]) => void;
  selectedMetrics: string[];
  setSelectedMetrics: (value: string[]) => void;
  activeMetric: string;
  setActiveMetric: (value: string) => void;
}) {
  const [draft, setDraft] = useState<CustomMetricDefinition>({
    id: "",
    label: "",
    description: "",
    expression: DEFAULT_CUSTOM_METRICS[0].expression,
  });
  const addToken = (token: string) => {
    const current = draft.expression.trim();
    const suffix = token.endsWith("()") ? `${token.slice(0, -1)}` : token;
    const needsOperator = Boolean(current) && !/[+\-*/%(,\s]$/.test(current);
    const next = `${current}${needsOperator ? " + " : current ? " " : ""}${suffix}`.trim();
    setDraft({ ...draft, expression: next });
  };
  const addMetric = () => {
    const expression = draft.expression.trim();
    if (!expression) {
      emitToast({ title: "Формула не добавлена", message: "Введите математическое выражение по доступным полям.", tone: "error" });
      return;
    }
    const validationError = validateFormulaExpression(expression);
    if (validationError) {
      emitToast({ title: "Формула не добавлена", message: validationError, tone: "error" });
      return;
    }
    const label = draft.label.trim() || `Собственная формула ${metrics.length + 1}`;
    const id = safeCustomMetricId(draft.id || label, metrics.length + 1);
    if (metrics.some((item) => item.id === id)) {
      emitToast({ title: "Формула не добавлена", message: "Формула с таким идентификатором уже есть. Измените короткое имя.", tone: "error" });
      return;
    }
    const nextMetric = { id, label, description: draft.description?.trim() || "Собственная формула по данным выбранного среза.", expression };
    setMetrics([...metrics, nextMetric]);
    setSelectedMetrics([...new Set([...selectedMetrics, id])]);
    setActiveMetric(id);
    setDraft({ id: "", label: "", description: "", expression: "" });
    emitToast({ title: "Формула добавлена", message: `Показатель «${label}» включен в таблицу и графики.`, tone: "success" });
  };
  const removeMetric = (id: string) => {
    setMetrics(metrics.filter((item) => item.id !== id));
    setSelectedMetrics(selectedMetrics.filter((item) => item !== id));
    if (activeMetric === id) setActiveMetric("h");
  };
  const resetMetrics = () => {
    const defaultIds = DEFAULT_CUSTOM_METRICS.map((item) => item.id);
    setMetrics(DEFAULT_CUSTOM_METRICS);
    setSelectedMetrics([...new Set([...selectedMetrics.filter((item) => !item.startsWith("custom_")), ...defaultIds])]);
    if (activeMetric.startsWith("custom_")) setActiveMetric(defaultIds[0] ?? "h");
    setDraft({ id: "", label: "", description: "", expression: DEFAULT_CUSTOM_METRICS[0].expression });
    emitToast({ title: "Формулы сброшены", message: "Возвращен пример собственной формулы по умолчанию.", tone: "info" });
  };
  return (
    <div className="formula-builder">
      <div className="formula-builder-head">
        <div>
          <h3>Калькулятор наукометрического показателя</h3>
          <p>Составьте выражение из показателей авторов. Поля `pr_...` означают процентиль 0–1 внутри текущей выборки, поэтому результат удобно сравнивать на общей шкале.</p>
        </div>
        <button type="button" onClick={resetMetrics}>Сбросить формулы</button>
      </div>
      <div className="formula-example">
        <b>Пример:</b>
        <code>100 * (pr_p * pr_h * pr_c_frac) ** (1 / 3)</code>
        <span>Это интегральный рейтинг по публикациям, индексу Хирша и долевым цитированиям.</span>
      </div>
      <div className="formula-form-grid">
        <Field label="Название">
          <input value={draft.label} onChange={(event) => setDraft({ ...draft, label: event.target.value })} placeholder="Например: Мой рейтинг" />
        </Field>
        <Field label="Короткое имя">
          <input value={draft.id} onChange={(event) => setDraft({ ...draft, id: event.target.value })} placeholder="custom_my_rating" />
        </Field>
      </div>
      <Field label="Описание">
        <input value={draft.description ?? ""} onChange={(event) => setDraft({ ...draft, description: event.target.value })} placeholder="Что показывает формула и когда ее применять" />
      </Field>
      <Field label="Формула">
        <textarea value={draft.expression} onChange={(event) => setDraft({ ...draft, expression: event.target.value })} rows={3} spellCheck={false} />
      </Field>
      <div className="formula-token-section">
        <b>Поля данных</b>
        <div className="formula-token-grid">
          {FORMULA_VARIABLES.map((item) => (
            <button type="button" className="choice-pill" key={item.token} onClick={() => addToken(item.token)} title={item.label}>
              {item.token}
            </button>
          ))}
        </div>
      </div>
      <div className="formula-token-section">
        <b>Функции</b>
        <div className="formula-token-grid compact">
          {FORMULA_FUNCTIONS.map((item) => (
            <button type="button" className="choice-pill" key={item} onClick={() => addToken(item)}>
              {item}
            </button>
          ))}
        </div>
      </div>
      <div className="formula-actions">
        <button type="button" className="primary" onClick={addMetric}><Sigma size={16} /> Добавить формулу</button>
      </div>
      {metrics.length > 0 && (
        <div className="custom-metric-list">
          {metrics.map((item) => {
            const enabled = selectedMetrics.includes(item.id) || activeMetric === item.id;
            return (
              <div key={item.id} className={enabled ? "custom-metric-row active" : "custom-metric-row"}>
                <div>
                  <b>{item.label}</b>
                  <code>{item.expression}</code>
                </div>
                <div className="row-actions">
                  <button
                    type="button"
                    className={enabled ? "choice-pill active" : "choice-pill"}
                    onClick={() => {
                      if (enabled && activeMetric !== item.id) setSelectedMetrics(selectedMetrics.filter((value) => value !== item.id));
                      if (!enabled) setSelectedMetrics([...selectedMetrics, item.id]);
                    }}
                    disabled={activeMetric === item.id}
                  >
                    {enabled ? "Показан" : "Показать"}
                  </button>
                  <button type="button" className="choice-pill" onClick={() => setActiveMetric(item.id)}>Основной</button>
                  <button type="button" className="choice-pill danger" onClick={() => removeMetric(item.id)}>Удалить</button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function validateFormulaExpression(expression: string) {
  if (expression.length > 500) return "Формула слишком длинная. Сократите выражение.";
  if (!/^[0-9A-Za-z_+\-*/%().,\s]+$/.test(expression)) return "Формула содержит неподдерживаемые символы. Используйте поля, числа, скобки и математические операции.";
  const allowedNames = new Set([...FORMULA_VARIABLES.map((item) => item.token), ...FORMULA_FUNCTION_NAMES, "pi", "e"]);
  const identifiers = expression.match(/[A-Za-z_][A-Za-z0-9_]*/g) ?? [];
  const unknown = identifiers.find((item) => !allowedNames.has(item));
  if (unknown) return `Неизвестное поле или функция: ${unknown}. Выберите поле из списка ниже.`;
  let balance = 0;
  for (const char of expression) {
    if (char === "(") balance += 1;
    if (char === ")") balance -= 1;
    if (balance < 0) return "В формуле лишняя закрывающая скобка.";
  }
  if (balance !== 0) return "В формуле не закрыта скобка.";
  const vars = FORMULA_VARIABLES.map((item) => item.token);
  const funcs = [...FORMULA_FUNCTION_NAMES];
  const args = [...vars, ...funcs, "pi", "e"];
  const values = [
    ...vars.map(() => 1),
    ...funcs.map((name) => {
      const map: Record<string, (...args: number[]) => number> = {
        sqrt: Math.sqrt,
        log1p: Math.log1p,
        min: Math.min,
        max: Math.max,
        abs: Math.abs,
        round: Math.round,
        log: Math.log,
        exp: Math.exp,
        pow: Math.pow,
        floor: Math.floor,
        ceil: Math.ceil,
      };
      return map[name];
    }),
    Math.PI,
    Math.E,
  ];
  try {
    const result = Function(...args, `"use strict"; return (${expression});`)(...values);
    if (!Number.isFinite(Number(result))) return "Формула должна возвращать конечное число.";
  } catch {
    return "Формула содержит синтаксическую ошибку. Проверьте операции и скобки.";
  }
  return "";
}

function FormulaBuilderDialog(props: {
  metrics: CustomMetricDefinition[];
  setMetrics: (value: CustomMetricDefinition[]) => void;
  selectedMetrics: string[];
  setSelectedMetrics: (value: string[]) => void;
  activeMetric: string;
  setActiveMetric: (value: string) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") props.onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [props.onClose]);
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) props.onClose();
    }}>
      <section className="formula-modal" role="dialog" aria-modal="true" aria-labelledby="formula-builder-title">
        <div className="modal-head">
          <div>
            <span className="step-badge">Рабочее окно</span>
            <h2 id="formula-builder-title">Конструктор собственного показателя</h2>
            <p>Создайте формулу из доступных полей, проверьте пример и включите показатель в рейтинг.</p>
          </div>
          <button type="button" className="icon-button" onClick={props.onClose} aria-label="Закрыть конструктор формул">
            <X size={18} />
          </button>
        </div>
        <CustomMetricBuilder {...props} />
      </section>
    </div>
  );
}

function safeCustomMetricId(raw: string, fallbackIndex: number) {
  const normalized = raw
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
  const value = normalized || `formula_${fallbackIndex}`;
  return (value.startsWith("custom_") ? value : `custom_${value}`).slice(0, 48);
}

function metricFormulaMarkup(metricName: string) {
  const formulas: Record<string, string> = {
    p: `<math><mrow><mi>P</mi><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><mo>|</mo><msub><mi>W</mi><mi>a</mi></msub><mo>|</mo></mrow></math>`,
    c: `<math><mrow><mi>C</mi><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><munderover><mo>∑</mo><mi>i</mi><msub><mi>W</mi><mi>a</mi></msub></munderover><msub><mi>c</mi><mi>i</mi></msub></mrow></math>`,
    c_frac: `<math><mrow><msub><mi>C</mi><mi>д</mi></msub><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><munderover><mo>∑</mo><mi>i</mi><msub><mi>W</mi><mi>a</mi></msub></munderover><mfrac><msub><mi>c</mi><mi>i</mi></msub><msub><mi>n</mi><mi>i</mi></msub></mfrac></mrow></math>`,
    cpp: `<math><mrow><mi>CPP</mi><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><mfrac><mrow><mi>C</mi><mo>(</mo><mi>a</mi><mo>)</mo></mrow><mrow><mi>P</mi><mo>(</mo><mi>a</mi><mo>)</mo></mrow></mfrac></mrow></math>`,
    h: `<math><mrow><mi>h</mi><mo>=</mo><mi>max</mi><mo>{</mo><mi>k</mi><mo>:</mo><msub><mi>c</mi><mi>k</mi></msub><mo>≥</mo><mi>k</mi><mo>}</mo></mrow></math>`,
    i10: `<math><mrow><mi>i10</mi><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><mo>|</mo><mo>{</mo><mi>i</mi><mo>:</mo><msub><mi>c</mi><mi>i</mi></msub><mo>≥</mo><mn>10</mn><mo>}</mo><mo>|</mo></mrow></math>`,
    g: `<math><mrow><mi>g</mi><mo>=</mo><mi>max</mi><mo>{</mo><mi>k</mi><mo>:</mo><munderover><mo>∑</mo><mrow><mi>i</mi><mo>=</mo><mn>1</mn></mrow><mi>k</mi></munderover><msub><mi>c</mi><mi>i</mi></msub><mo>≥</mo><msup><mi>k</mi><mn>2</mn></msup><mo>}</mo></mrow></math>`,
    m_local: `<math><mrow><mi>m</mi><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><mfrac><mrow><mi>h</mi><mo>(</mo><mi>a</mi><mo>)</mo></mrow><msub><mi>T</mi><mi>a</mi></msub></mfrac></mrow></math>`,
    f5: `<math><mrow><mi>f5</mi><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><mo>|</mo><mo>{</mo><mi>i</mi><mo>:</mo><msub><mi>c</mi><mi>i</mi></msub><mo>≥</mo><mn>5</mn><mo>}</mo><mo>|</mo></mrow></math>`,
    fm5: `<math><mrow><mi>fm5</mi><mo>(</mo><mi>a</mi><mo>)</mo><mo>=</mo><munderover><mo>∑</mo><mrow><msub><mi>c</mi><mi>i</mi></msub><mo>≥</mo><mn>5</mn></mrow><msub><mi>W</mi><mi>a</mi></msub></munderover><msub><mi>w</mi><mi>i</mi></msub></mrow></math>`,
    iupv: `<math><mrow><mi>IUPV</mi><mo>=</mo><mn>100</mn><mo>·</mo><msup><mrow><mo>(</mo><mi>pr</mi><mo>(</mo><mi>P</mi><mo>)</mo><mo>·</mo><mi>pr</mi><mo>(</mo><mi>h</mi><mo>)</mo><mo>·</mo><mi>pr</mi><mo>(</mo><msub><mi>C</mi><mi>д</mi></msub><mo>)</mo><mo>)</mo></mrow><mfrac><mn>1</mn><mn>3</mn></mfrac></msup></mrow></math>`,
    islv: `<math><mrow><mi>ISLV</mi><mo>=</mo><mn>100</mn><mo>·</mo><msub><mi>G</mi><mi>w</mi></msub><mo>(</mo><mi>pr</mi><mo>(</mo><mi>h</mi><mo>)</mo><mo>,</mo><mi>pr</mi><mo>(</mo><msub><mi>C</mi><mi>д</mi></msub><mo>)</mo><mo>,</mo><mi>pr</mi><mo>(</mo><mi>g</mi><mo>)</mo><mo>,</mo><mi>pr</mi><mo>(</mo><mi>i10</mi><mo>)</mo><mo>,</mo><mi>pr</mi><mo>(</mo><mi>P</mi><mo>)</mo><mo>)</mo></mrow></math>`,
    lrdi: `<math><mrow><mi>LRDI</mi><mo>=</mo><mi>shrink</mi><mo>(</mo><mi>P</mi><mo>)</mo><mo>·</mo><munderover><mo>∑</mo><mi>i</mi><msub><mi>W</mi><mi>a</mi></msub></munderover><mfrac><mrow><mi>ln</mi><mo>(</mo><mn>1</mn><mo>+</mo><msub><mi>c</mi><mi>i</mi></msub><mo>)</mo></mrow><msub><mi>n</mi><mi>i</mi></msub></mfrac><mo>·</mo><msup><mi>e</mi><mrow><mo>-</mo><mi>λ</mi><mo>·</mo><msub><mi>age</mi><mi>i</mi></msub></mrow></msup></mrow></math>`,
  };
  return (formulas[metricName] ?? "").replace("<math>", '<math xmlns="http://www.w3.org/1998/Math/MathML">');
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

function ReportsPage({
  filters,
  metric,
  fractionMode,
  runId,
  dumpId,
  topN,
  scientometricMetrics,
  baselineMetric,
  rankTopN,
  dataFilters,
  dataSort,
  dataDirection,
  customMetrics,
  metricLabels,
  onBuild,
  building,
  state,
  sliceDoc,
  estimate,
  materialization,
}: {
  filters: ActiveFilters;
  metric: string;
  fractionMode: string;
  runId: string;
  dumpId: string;
  topN: number;
  scientometricMetrics: string[];
  baselineMetric: string;
  rankTopN: number;
  dataFilters: TableColumnFilters;
  dataSort: string;
  dataDirection: "asc" | "desc";
  customMetrics: CustomMetricDefinition[];
  metricLabels: Record<string, string>;
  onBuild: () => void;
  building: boolean;
  state: any;
  sliceDoc: any;
  estimate: any;
  materialization: any;
}) {
  const [section, setSection] = useState<"exports" | "passports">("exports");
  const selectionQuery = dataSelectionQuery({ filters: dataFilters, sort: dataSort, direction: dataDirection, limit: topN });
  const activeRestrictionCount = Object.keys(dataFilters).length;
  const reportParams = filterParams(filters, {
    fraction_mode: fractionMode,
    metric,
    limit: topN,
    run_id: runId,
    dump_id: dumpId,
    scientometric_metrics: scientometricMetrics.join(","),
    baseline_metric: baselineMetric,
    rank_top_n: rankTopN,
    custom_metric_defs: customMetricDefsQuery(customMetrics),
    ...selectionQuery,
  });
  const rankingUrl = `${API_BASE}/analytics/ranking.csv?${reportParams.toString()}`;
  const bundleUrl = `${API_BASE}/reports/bundle.json?${reportParams.toString()}`;
  const hasReportDataScope = Boolean(runId || dumpId);
  const localIndicesUrl = `${API_BASE}${localDataPreviewCsvUrl("indices", { runId, dumpId, limit: 100_000, sort: dataSort, direction: dataDirection, fractionMode, dataFilters })}`;
  const localWorksUrl = `${API_BASE}${localDataPreviewCsvUrl("works", { runId, dumpId, limit: 100_000, sort: dataSort, direction: dataDirection, dataFilters })}`;
  const localAuthorshipsUrl = `${API_BASE}${localDataPreviewCsvUrl("authorships", { runId, dumpId, limit: 100_000, sort: dataSort, direction: dataDirection, dataFilters })}`;
  const localWorkTopicsUrl = `${API_BASE}${localDataPreviewCsvUrl("work_topics", { runId, dumpId, limit: 100_000, sort: dataSort, direction: dataDirection, dataFilters })}`;
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">Отчет</span>
            <h2>Отчеты и пакет воспроизводимости</h2>
            <p>Отчет фиксирует срез исследования, локальную загрузку, текущую выборку из “Данных”, расчет индексов, ограничения и паспорта.</p>
          </div>
          <button onClick={onBuild} disabled={building}>{building ? <Loader2 size={16} className="spin" /> : <Download size={16} />} Собрать HTML</button>
        </div>
        <div className="choice-grid compact section-tabs" role="tablist" aria-label="Разделы отчетов">
          {[
            ["exports", "Пакет и таблицы"],
            ["passports", "Паспорта"],
          ].map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={section === id} className={section === id ? "choice-pill active" : "choice-pill"} onClick={() => setSection(id as "exports" | "passports")}>
              {label}
            </button>
          ))}
        </div>
        {section === "exports" && (
          <>
          <div className="download-grid">
            {hasReportDataScope && <DownloadLink href={rankingUrl} label="Рейтинг авторов" />}
          <DownloadLink href={bundleUrl} label="Пакет отчета" />
          {hasReportDataScope && (
            <>
              <DownloadLink href={localIndicesUrl} label="Авторы и индексы" />
              <DownloadLink href={localWorksUrl} label="Работы" />
              <DownloadLink href={localAuthorshipsUrl} label="Авторство в работах" />
              <DownloadLink href={localWorkTopicsUrl} label="Темы работ" />
            </>
          )}
          <DownloadLink href={`${API_BASE}/workbench`} label="Состояние системы" />
          <DownloadLink href={`${API_BASE}/catalog`} label="Каталог настроек" />
        </div>
        {!hasReportDataScope && (
          <div className="notice warn">
            <b>Выгрузка требует выбранный срез</b>
            <span>Выберите расчет или локальный срез: ссылки на локальные таблицы не показываются без выбранной области анализа.</span>
          </div>
        )}
          </>
        )}
        {section === "passports" && (
          <ReportPassportsSection state={state} sliceDoc={sliceDoc} estimate={estimate} materialization={materialization} />
        )}
        <div className="notice">
          <b>Параметры пакета</b>
          <span>Показатели: {scientometricMetrics.map((item) => metricLabelFor(item, metricLabels)).join(", ")}. Основной показатель: {metricLabelFor(baselineMetric, metricLabels)}. Строк из “Данных”: {rankTopN > 0 ? fmt(rankTopN) : "все"}. Ограничений по столбцам: {activeRestrictionCount}.</span>
        </div>
      </section>
    </div>
  );
}

function DownloadLink({ href, label, compact = false }: { href: string; label: string; compact?: boolean }) {
  return <a className={compact ? "download-action compact" : "download-action"} href={href}><Download size={15} /> {label}</a>;
}

function ReportPassportsSection({ state, sliceDoc, estimate, materialization }: { state: any; sliceDoc: any; estimate: any; materialization: any }) {
  return (
    <div className="passport-grid">
      <JsonPanel title="Паспорт среза" value={sliceDoc ?? state?.workflow?.current_slice ?? {}} />
      <JsonPanel title="Паспорт оценки" value={estimate ?? sliceDoc?.current_estimate ?? {}} />
      <JsonPanel title="Паспорт загрузки и хранения" value={materialization ?? sliceDoc?.current_materialization_plan ?? {}} />
      <JsonPanel title="Паспорт качества данных" value={state?.quality ?? {}} />
    </div>
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
    queryFn: () => getJson<any>(`${endpoint}?q=${encodeURIComponent(query)}&limit=10`),
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

function ToastViewport({ toasts, onClose }: { toasts: ToastItem[]; onClose: (id: string) => void }) {
  if (toasts.length === 0) return null;
  return (
    <div className="toast-viewport" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <section key={toast.id} className={`toast-card ${toast.tone}`}>
          <div>
            <b>{toast.title}</b>
            <span>{toast.message}</span>
          </div>
          <button type="button" aria-label="Закрыть уведомление" onClick={() => onClose(toast.id)}>
            <X size={15} />
          </button>
        </section>
      ))}
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

function RateLimitPanel({ rateLimit, apiKeySet, estimate }: { rateLimit: any; apiKeySet: boolean; estimate: any }) {
  const headerLimit = estimate?.rate_limit ?? {};
  const dailyRemaining = rateLimit?.daily_remaining_usd;
  const dailyBudget = rateLimit?.daily_budget_usd;
  const estimatedCost = estimate?.estimated_cost_usd;
  return (
    <div className="metric-grid">
      <MetricCard label="Ключ OpenAlex" value={apiKeySet ? "задан" : "не задан"} />
      <MetricCard label="Остаток OpenAlex" value={dailyRemaining !== undefined ? `$${fmt(dailyRemaining)}` : headerLimit.remaining !== undefined ? fmt(headerLimit.remaining) : "нет данных"} />
      <MetricCard label="Дневной лимит" value={dailyBudget !== undefined ? `$${fmt(dailyBudget)}` : headerLimit.limit !== undefined ? fmt(headerLimit.limit) : "нет данных"} />
      <MetricCard label="Стоимость оценки" value={estimatedCost !== undefined ? `$${fmt(estimatedCost)}` : "нет данных"} />
    </div>
  );
}

function EstimateBudget({ estimate, decision }: { estimate: any; decision: any }) {
  const p90 = Number(estimate?.estimated_cli_metadata_bytes ?? estimate?.estimated_raw_bytes_p90 ?? estimate?.estimated_raw_bytes ?? 0);
  const avg = Number(estimate?.estimated_selected_api_bytes ?? estimate?.estimated_raw_bytes ?? 0);
  if (!avg && !p90) return null;
  const baseline = Math.max(avg, p90, 1);
  const avgPct = Math.min(100, Math.round((avg / baseline) * 100));
  const p90Pct = Math.min(100, Math.round((p90 / baseline) * 100));
  return (
    <div className="estimate-budget">
      <div className="progress-meta">
        <span>Прогноз: предпросмотр {fmt(bytesToMb(avg))} МБ, загрузка {fmt(bytesToMb(p90))} МБ</span>
        <b>{decision?.status ?? "estimate"}</b>
      </div>
      <div className="budget-track" aria-label={`Средний прогноз ${avgPct}%, p90 ${p90Pct}%`}>
        <span className="budget-avg" style={{ width: `${avgPct}%` }} />
        <span className="budget-p90" style={{ width: `${p90Pct}%` }} />
      </div>
    </div>
  );
}

function EstimateFacets({ facets }: { facets: any }) {
  const groups = [
    { key: "publication_years", title: "Годы публикаций" },
    { key: "work_types", title: "Типы публикаций" },
    { key: "countries", title: "Страны аффилиаций" },
  ];
  if (!facets || groups.every((group) => !(facets[group.key]?.rows ?? []).length)) return null;
  return (
    <div className="facet-grid">
      {groups.map((group) => (
        <FacetBars key={group.key} title={group.title} rows={facets[group.key]?.rows ?? []} />
      ))}
    </div>
  );
}

function FacetBars({ title, rows }: { title: string; rows: Array<{ key?: string; label?: string; count?: number }> }) {
  const cleanRows = rows.filter((row) => row.label || row.key).slice(0, 8);
  const max = Math.max(1, ...cleanRows.map((row) => Number(row.count ?? 0)));
  return (
    <section className="facet-card">
      <b>{title}</b>
      {cleanRows.length === 0 && <small>Нет данных предпросмотра</small>}
      {cleanRows.map((row) => {
        const count = Number(row.count ?? 0);
        return (
          <div className="facet-row" key={`${row.key ?? row.label}`}>
            <span>{row.label || row.key}</span>
            <i><em style={{ width: `${Math.max(2, Math.round((count / max) * 100))}%` }} /></i>
            <strong>{fmt(count)}</strong>
          </div>
        );
      })}
    </section>
  );
}

function ProgressPanel({ filters, estimate, materialization, run }: { filters: ActiveFilters; estimate: any; materialization: any; run: any }) {
  const steps = [
    { id: "draft", label: "Срез", ready: true },
    { id: "estimated", label: "Оценка", ready: Boolean(estimate) },
    { id: "planned", label: "План", ready: Boolean(materialization) },
    { id: "materializing", label: "Загрузка", ready: run?.status === "completed" || run?.status === "running" },
    { id: "analyzed", label: "Аналитика", ready: run?.result?.build || run?.status === "completed" },
  ];
  return (
    <section className="panel">
      <div className="panel-head">
        <span className="step-badge">Ход работы</span>
        <h2>{humanSliceTitle(filters)}</h2>
      </div>
      <div className="state-line">
        {steps.map((step) => <span key={step.id} className={step.ready ? "ready" : ""}>{step.label}</span>)}
      </div>
      {run && <RunCard run={run} />}
    </section>
  );
}

function StatusRail({ state, run, running }: { state: any; run: any; running: boolean }) {
  const tables = state?.tables ?? {};
  const progress = progressForRun(run);
  return (
    <div className="status-rail">
      <span><Database size={15} /> Работы: {fmt(tables?.works?.rows ?? 0)}</span>
      <span><Sigma size={15} /> Авторы: {fmt(tables?.indices?.rows ?? 0)}</span>
      <span><Gauge size={15} /> {running ? (progress.percent === null ? progress.label : `${progress.label} · ${progress.percent}%`) : run?.status ?? state?.workflow?.active_stage ?? "idle"}</span>
    </div>
  );
}

function RunCard({ run }: { run: WorkbenchRun }) {
  if (!run) return null;
  const progress = progressForRun(run);
  const details = (run as any).progress ?? {};
  const fetchedWorks = Number(details.fetched ?? 0);
  const targetWorks = Number(details.target_records ?? details.total_available ?? 0);
  const hasWorkCounter = fetchedWorks > 0 || targetWorks > 0;
  const hasFilesCounter = details.files_seen || details.bytes_written;
  const live = runLiveState(run);
  const phases = runProgressPhases(run, details);
  return (
    <div className={`run-card ${run.status === "failed" ? "error" : ""} ${live.active ? "live" : ""}`}>
      <div className="run-live-head">
        <span className={`live-dot ${live.active ? "active" : ""}`} aria-hidden="true" />
        <div>
          <b>{live.title}</b>
          <small>{live.detail}</small>
        </div>
      </div>
      <span className="run-id-line">{runActionTitle(run.action)}: {run.run_id}</span>
      <ProgressBar percent={progress.percent} label={progress.label} tone={run.status === "failed" ? "error" : "normal"} />
      {phases.length > 0 && (
        <div className="run-phase-grid" aria-label="Подробный ход выполнения">
          {phases.map((phase) => (
            <PhaseBar key={phase.id} phase={phase} />
          ))}
        </div>
      )}
      {Object.keys(details).length > 0 && (
        <div className="run-progress-details">
          {hasWorkCounter && <span>{fmt(fetchedWorks)} / {fmt(targetWorks)} работ</span>}
          {details.page_count ? <span>{fmt(details.page_count)} страниц</span> : null}
          {details.files_seen ? <span>{fmt(details.files_seen)} файлов OpenAlex</span> : null}
          {hasFilesCounter ? <span>{fmt(bytesToMb(details.bytes_written ?? 0))} МБ на диске</span> : null}
          {details.elapsed_seconds ? <span>{formatElapsed(details.elapsed_seconds)}</span> : null}
        </div>
      )}
      {run.error && <small>{run.error}</small>}
    </div>
  );
}

function runActionTitle(action: unknown) {
  const value = String(action ?? "");
  if (value === "recalculate") return "Расчет индексов";
  if (value === "build_from_openalex") return "Скачивание и расчет среза";
  if (value === "fetch_slice_dump") return "Скачивание среза";
  if (value === "repair_dump") return "Восстановление среза";
  return "Задача";
}

function runCompletedTitle(action: unknown) {
  const value = String(action ?? "");
  if (value === "repair_dump") return "Срез восстановлен";
  if (value === "recalculate") return "Индексы рассчитаны";
  if (value === "fetch_slice_dump") return "Срез скачан";
  if (value === "build_from_openalex") return "Срез скачан и рассчитан";
  return "Задача завершена";
}

function runLiveState(run: WorkbenchRun) {
  const action = String(run.action ?? "");
  const status = String(run.status ?? "");
  const isSliceLoad = action === "build_from_openalex" || action === "fetch_slice_dump";
  if (status === "queued" && action === "repair_dump") return { active: true, title: "Восстановление в очереди", detail: "Операция начнется автоматически." };
  if (status === "queued") return { active: true, title: "Срез в очереди", detail: "Загрузка начнется автоматически." };
  if (status === "running" && action === "repair_dump") return { active: true, title: "Восстановление среза", detail: "Проверка, упаковка, таблицы и расчет отображаются отдельными этапами." };
  if (status === "running" && isSliceLoad) return { active: true, title: "Загрузка среза", detail: "Статус обновляется в реальном времени." };
  if (status === "running") return { active: true, title: "Выполнение", detail: "Статус обновляется в реальном времени." };
  if (status === "cancelling") return {
    active: true,
    title: action === "repair_dump" ? "Остановка восстановления" : "Остановка загрузки",
    detail: action === "repair_dump" ? "Текущий срез останется в списке с текущим состоянием." : "Система сохраняет уже скачанные записи как частичный срез.",
  };
  if (status === "cancelled") return {
    active: false,
    title: action === "repair_dump" ? "Восстановление остановлено" : "Загрузка остановлена",
    detail: action === "repair_dump" ? "Срез можно восстановить повторно из списка срезов." : "Частичный срез будет доступен, если успели скачаться записи.",
  };
  if (status === "completed" && action === "repair_dump") return { active: false, title: "Срез восстановлен", detail: "Локальные таблицы и индексы доступны." };
  if (status === "completed" && isSliceLoad) return { active: false, title: "Срез готов", detail: "Локальные таблицы доступны для анализа." };
  if (status === "completed") return { active: false, title: "Готово", detail: "Задача завершена." };
  if (status === "failed") return {
    active: false,
    title: action === "repair_dump" ? "Восстановление не выполнено" : "Ошибка выполнения",
    detail: "Подробности показаны ниже и в уведомлении.",
  };
  return { active: false, title: action || "Run", detail: status || "нет статуса" };
}

type RunPhase = {
  id: string;
  label: string;
  percent: number | null;
  state: "pending" | "active" | "done" | "error";
};

function runProgressPhases(run: WorkbenchRun, details: Record<string, any>): RunPhase[] {
  const action = String(run.action ?? "");
  const status = String(run.status ?? "");
  const failed = status === "failed";
  const completed = status === "completed";
  const queued = status === "queued";
  const currentStage = String(run.progress_stage ?? details.stage ?? "");
  const phasePercent = (value: unknown) => {
    if (typeof value !== "number") return null;
    return Math.max(0, Math.min(100, Math.round(value)));
  };
  const phase = (id: string, label: string, percentValue: unknown = null): RunPhase => ({
    id,
    label,
    percent: completed ? 100 : phasePercent(percentValue),
    state: failed ? "error" : completed ? "done" : currentStage.includes(label) ? "active" : "pending",
  });
  if (action === "build_from_openalex") {
    return [
      {
        id: "download",
        label: "Скачивание файлов",
        percent: completed ? 100 : phasePercent(details.download_percent),
        state: failed ? "error" : completed ? "done" : queued ? "pending" : (currentStage.includes("Загрузка") ? "active" : "pending"),
      },
      phase("pack", "Упаковка среза", details.pack_percent),
      phase("normalize", "Подготовка таблиц"),
      phase("compute", "Расчет индексов"),
    ];
  }
  if (action === "fetch_slice_dump") {
    return [
      {
        id: "download",
        label: "Скачивание файлов",
        percent: completed ? 100 : phasePercent(details.download_percent),
        state: failed ? "error" : completed ? "done" : queued ? "pending" : "active",
      },
      phase("pack", "Упаковка среза", details.pack_percent),
    ];
  }
  if (action === "repair_dump") {
    return [
      phase("check", "Проверка файлов"),
      phase("pack", "Упаковка", details.pack_percent),
      phase("normalize", "Подготовка таблиц"),
      phase("compute", "Расчет индексов"),
    ];
  }
  if (action === "recalculate") {
    return [
      phase("check", "Проверка таблиц"),
      phase("compute", "Расчет индексов"),
      phase("report", "Паспорт и отчет"),
    ];
  }
  return [];
}

function PhaseBar({ phase }: { phase: RunPhase }) {
  return (
    <div className={`run-phase ${phase.state}`}>
      <div className="progress-meta">
        <span>{phase.label}</span>
        <b>{phase.percent === null ? phaseStateLabel(phase.state) : `${phase.percent}%`}</b>
      </div>
      <div className={`progress-track ${phase.state === "error" ? "error" : ""}`}>
        <span className={phase.percent === null && phase.state === "active" ? "indeterminate" : ""} style={{ width: phase.percent === null ? (phase.state === "done" ? "100%" : "0%") : `${phase.percent}%` }} />
      </div>
    </div>
  );
}

function phaseStateLabel(state: RunPhase["state"]) {
  if (state === "done") return "готово";
  if (state === "active") return "выполняется";
  if (state === "error") return "ошибка";
  return "ожидает";
}

function ProgressBar({ percent, label, tone = "normal" }: { percent: number | null; label: string; tone?: "normal" | "error" }) {
  return (
    <div className="progress-group" aria-label={percent === null ? label : `${label}: ${percent}%`}>
      <div className="progress-meta">
        <span>{label}</span>
        <b>{percent === null ? "выполняется" : `${percent}%`}</b>
      </div>
      <div className={`progress-track ${tone}`}>
        <span className={percent === null ? "indeterminate" : ""} style={{ width: percent === null ? "0%" : `${percent}%` }} />
      </div>
    </div>
  );
}

function JsonPanel({ title, value }: { title: string; value: unknown }) {
  return (
    <section className="panel json-panel">
      <h2>{title}</h2>
      <pre>{JSON.stringify(value ?? {}, null, 2)}</pre>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="field"><span>{label}</span>{children}</div>;
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
    queryFn: () => getJson<any>(`/openalex/subjects?q=${encodeURIComponent(queryText)}&limit=12`),
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
    queryFn: () => getJson<any>(`/openalex/institutions?q=${encodeURIComponent(queryText)}&limit=12`),
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

function extractDumpId(run: any) {
  return String(
    run?.result?.analysis_eligibility?.dump_id
    ?? run?.result?.build?.archive?.dump_id
    ?? run?.result?.fetch?.dump?.dump_id
    ?? run?.result?.archive?.dump_id
    ?? "",
  ).trim();
}

function formatElapsed(seconds: unknown) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes ? `${minutes} мин ${rest} сек` : `${rest} сек`;
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

function activeContextEligibility(value: boolean | null | undefined) {
  if (value === true) return { label: "Финальный анализ разрешен", className: "status-chip ok" };
  if (value === false) return { label: "Финальный анализ запрещен", className: "status-chip warn" };
  return { label: "Пригодность не определена", className: "status-chip" };
}

function activeContextSourceLabel(source?: string) {
  if (source === "materialization") return "загрузка среза";
  if (source === "recalculate") return "пересчет индексов";
  if (source === "import_local_file") return "локальный файл";
  return source || "не задан";
}

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return <div className="metric-card"><span>{label}</span><b>{value}</b></div>;
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return <div className="key-value"><span>{label}</span><b>{value || "не задано"}</b></div>;
}

function CheckPill({ active, label }: { active: boolean; label: string }) {
  return <span className={active ? "check-pill active" : "check-pill"}>{active && <CheckCircle2 size={14} />}{label}</span>;
}

createRoot(document.getElementById("root")!).render(<App />);
