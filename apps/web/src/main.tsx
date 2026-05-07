import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
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
  Loader2,
  Search,
  Settings2,
  Sigma,
  UploadCloud,
  X,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, ComposedChart, Line, LineChart, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { API_BASE, deleteJson, getJson, postJson, type TableColumnFilters, type TableResponse } from "./api";
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
  analyticsUrl,
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
    onError: (error) => emitToast({ title: "Не удалось получить данные", message: mutationError(error), tone: "error" }),
  }),
  mutationCache: new MutationCache({
    onError: (error) => emitToast({ title: "Действие не выполнено", message: mutationError(error), tone: "error" }),
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

const COMMON_RANKING_METRICS = new Set(["p", "c", "c_frac", "cpp", "h", "i10", "g", "m_local", "f5", "fm5", "iupv", "islv", "lrdi"]);

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
  const [scientometricMetrics, setScientometricMetrics] = useState<string[]>(["p", "c", "c_frac", "h", "g", "iupv", "islv"]);
  const [baselineMetric, setBaselineMetric] = useState("h");
  const [storageProfileId, setStorageProfileId] = useState("");
  const [downloadDir, setDownloadDir] = useState("");
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
      setToasts((items) => [next, ...items].slice(0, 4));
      window.setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 7_000);
    };
    window.addEventListener(TOAST_EVENT, onToast);
    return () => window.removeEventListener(TOAST_EVENT, onToast);
  }, []);

  const navigate = (next: View) => {
    setView(next);
    window.history.replaceState(null, "", `#${next}`);
  };

  const onNavKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const current = NAV.findIndex((item) => item.id === view);
    if (current < 0) return;
    const last = NAV.length - 1;
    const nextIndex = {
      ArrowDown: Math.min(current + 1, last),
      ArrowRight: Math.min(current + 1, last),
      ArrowUp: Math.max(current - 1, 0),
      ArrowLeft: Math.max(current - 1, 0),
      Home: 0,
      End: last,
    }[event.key];
    if (nextIndex === undefined) return;
    event.preventDefault();
    const next = NAV[nextIndex].id;
    navigate(next);
    navRefs.current[nextIndex]?.focus();
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
      return status === "queued" || status === "running" ? 1000 : false;
    },
  });

  const notifiedRunRef = useRef("");
  useEffect(() => {
    const current = run.data;
    if (!current?.run_id || current.status === "queued" || current.status === "running") return;
    const key = `${current.run_id}:${current.status}:${current.error ?? ""}`;
    if (notifiedRunRef.current === key) return;
    notifiedRunRef.current = key;
    if (current.status === "failed") {
      emitToast({ title: "Загрузка среза завершилась ошибкой", message: String(current.error || "Проверьте параметры среза и журнал run."), tone: "error", key });
    } else if (current.status === "completed") {
      emitToast({ title: "Срез готов", message: "Локальные данные обновлены и доступны для выбора.", tone: "success", key });
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
  const filterKey = useMemo(() => JSON.stringify(filters), [filters]);
  const dataFilterKey = useMemo(() => JSON.stringify(dataColumnFilters), [dataColumnFilters]);
  const dataSelection = useMemo(() => ({
    filters: dataColumnFilters,
    search: dataSearch,
    sort: dataSort,
    direction: dataDirection,
    limit: topN,
    authorIds: selectedAuthorIds,
  }), [dataColumnFilters, dataSearch, dataSort, dataDirection, topN, selectedAuthorIds.join("|")]);
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
  const hasAuthorIndices = Boolean((localDataSummary.data?.tables as any)?.indices?.exists);
  const hasLocalAnalyticsData = scopeReady && hasAuthorIndices;
  const table = useQuery({
    queryKey: ["local-data-preview", localDataKind, dataSearch, dataFilterKey, topN, dataSort, dataDirection, fractionMode, effectiveRunId, effectiveDumpId],
    queryFn: () => getJson<TableResponse>(localDataPreviewUrl(localDataKind, { q: dataSearch, runId: effectiveRunId, dumpId: effectiveDumpId, limit: topN, sort: dataSort, direction: dataDirection, fractionMode, dataFilters: dataColumnFilters })),
    enabled: scopeReady && localDataKindAvailable,
  });
  const analytics = useQuery({
    queryKey: ["analytics", metric, fractionMode, effectiveRunId, effectiveDumpId, filterKey, dataSearch, dataFilterKey, dataSort, dataDirection, topN, selectedAuthorIds.join("|")],
    queryFn: () => getJson<any>(analyticsUrl(filters, fractionMode, metric, effectiveRunId, effectiveDumpId, "", dataSelection)),
    enabled: hasLocalAnalyticsData,
  });
  const ranking = useQuery({
    queryKey: ["analytics-ranking", metric, fractionMode, effectiveRunId, effectiveDumpId, filterKey, topN, dataSearch, dataFilterKey, dataSort, dataDirection, selectedAuthorIds.join("|")],
    queryFn: () => getJson<TableResponse>(analyticsRankingUrl(filters, fractionMode, metric, effectiveRunId, effectiveDumpId, topN, "", dataSelection)),
    enabled: hasLocalAnalyticsData,
  });
  const authorIndexTable = useQuery({
    queryKey: ["author-index-table", fractionMode, effectiveRunId, effectiveDumpId, topN, dataSearch, dataFilterKey, dataSort, dataDirection, selectedAuthorIds.join("|")],
    queryFn: () => getJson<TableResponse>(localDataPreviewUrl("indices", {
      q: dataSearch,
      runId: effectiveRunId,
      dumpId: effectiveDumpId,
      limit: topN,
      sort: dataSort,
      direction: dataDirection,
      fractionMode,
      dataFilters: dataColumnFilters,
    })),
    enabled: scopeReady && Boolean((localDataSummary.data?.tables as any)?.indices?.exists),
  });
  const scientometrics = useQuery({
    queryKey: ["scientometrics", scientometricMetricKey, baselineMetric, topN, fractionMode, effectiveRunId, effectiveDumpId, filterKey, dataSearch, dataFilterKey, dataSort, dataDirection, selectedAuthorIds.join("|")],
    queryFn: () => getJson<ScientometricAnalysisPayload>(scientometricsUrl({
      filters,
      fractionMode,
      metrics: scientometricMetrics,
      baselineMetric,
      rankTopN: topN,
      runId: effectiveRunId,
      dumpId: effectiveDumpId,
      dataSelection,
    })),
    enabled: hasLocalAnalyticsData && scientometricMetrics.length > 0,
  });
  const detail = useQuery({
    queryKey: ["detail", selected, effectiveRunId, effectiveDumpId],
    queryFn: () => getJson<any>(
      selected?.kind === "author"
        ? `/authors/${encodeURIComponent(selected.id)}?run_id=${encodeURIComponent(effectiveRunId)}&dump_id=${encodeURIComponent(effectiveDumpId)}`
        : `/works/${encodeURIComponent(selected?.id ?? "")}?run_id=${encodeURIComponent(effectiveRunId)}&dump_id=${encodeURIComponent(effectiveDumpId)}`,
    ),
    enabled: Boolean(selected) && scopeReady,
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
  const cliApiKeyReady = true;
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
      return postJson<any>(`/materializations/${encodeURIComponent(plan.materialization_id)}/run`, { ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}), ...(downloadDir.trim() ? { download_dir: downloadDir.trim() } : {}) });
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
      return postJson<any>(`/materializations/${encodeURIComponent(plan.materialization_id)}/run`, { ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}), ...(downloadDir.trim() ? { download_dir: downloadDir.trim() } : {}) });
    },
    onSuccess: (result) => {
      setApiKey("");
      setRunId(result?.run?.run_id ?? "");
      setDumpId("");
      qc.invalidateQueries({ queryKey: ["workbench"] });
      navigate("data");
    },
  });
  const deleteSavedSlice = useMutation({
    mutationFn: (sliceId: string) => deleteJson<any>(`/slices/${encodeURIComponent(sliceId)}`),
    onSuccess: (_result, sliceId) => {
      if (sliceDoc?.slice_id === sliceId) {
        setSliceDoc(null);
        setEstimate(null);
        setMaterialization(null);
      }
      qc.invalidateQueries({ queryKey: ["workbench"] });
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
    onSuccess: (_result, nextDumpId) => {
      setRunId("");
      setDumpId(nextDumpId);
      qc.invalidateQueries({ queryKey: ["workbench"] });
      qc.invalidateQueries({ queryKey: ["local-data-summary"] });
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
  const buildReport = useMutation({
    mutationFn: () => postJson<any>(`/reports/build?${filterParams(filters, {
      metric,
      fraction_mode: fractionMode,
      run_id: runId,
      dump_id: activeDumpId,
      limit: activeTopN > 0 ? Math.min(activeTopN, 500) : 50,
      scientometric_metrics: scientometricMetrics.join(","),
      baseline_metric: baselineMetric,
      rank_top_n: activeTopN > 0 ? activeTopN : 1000,
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
  const selectSavedSlice = (doc: any) => {
    setSliceDoc(doc);
    setFilters(filtersFromSlicePayload(doc?.technical_payload ?? doc, filters));
    setEstimate(doc?.current_estimate ?? null);
    setMaterialization(doc?.current_materialization_plan ?? null);
    const plan = doc?.current_materialization_plan ?? {};
    setRunId(String(plan.run_id ?? ""));
    setDumpId(String(plan.dump_id ?? plan.dump_manifest?.dump_id ?? ""));
    setDownloadDir(String(plan.download_dir ?? plan.technical_payload?.download_dir ?? ""));
    navigate("slices");
  };

  const selectMaterializationPlan = (plan: any) => {
    setMaterialization(plan);
    setEstimate(plan?.estimated ?? null);
    setFilters(filtersFromSlicePayload(plan?.technical_payload ?? {}, filters));
    const slice = (workbench.data?.slices ?? []).find((item: any) => String(item.slice_id ?? "") === String(plan?.slice_id ?? ""));
    if (slice) setSliceDoc(slice);
    setRunId(String(plan?.run_id ?? ""));
    setDumpId(String(plan?.dump_id ?? plan?.dump_manifest?.dump_id ?? ""));
    setDownloadDir(String(plan?.download_dir ?? plan?.technical_payload?.download_dir ?? ""));
    navigate(plan?.run_id ? "data" : "slices");
  };

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

  const running = run.data?.status === "queued" || run.data?.status === "running";
  const tables = localDataSummary.data?.tables ?? workbench.data?.tables ?? {};
  const errors = [
    mutationError(createSlice.error),
    mutationError(estimateSlice.error),
    mutationError(createMaterialization.error),
    mutationError(runMaterialization.error),
    mutationError(downloadSlice.error),
    mutationError(selectDownloadedDumpRemote.error),
    mutationError(deleteSavedSlice.error),
    mutationError(deleteDownloadedDump.error),
    mutationError(recalculate.error),
  ].filter(Boolean);
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
    analytics.error,
    ranking.error,
    scientometrics.error,
    detail.error,
  ].filter(Boolean);

  useEffect(() => {
    queryErrors.forEach((error) => emitToast({ title: "Не удалось получить данные", message: mutationError(error), tone: "error" }));
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
          {NAV.map((item, index) => (
            <button
              key={item.id}
              ref={(node) => { navRefs.current[index] = node; }}
              id={`tab-${item.id}`}
              role="tab"
              aria-selected={view === item.id}
              aria-controls={`panel-${item.id}`}
              className={view === item.id ? "active" : ""}
              onClick={() => navigate(item.id)}
            >
              {item.icon}
              <span>{item.label}</span>
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

        {view === "slices" && (
          <SlicesPage
            filters={filters}
            setFilters={setFilters}
            domainPresets={domainPresets}
            organizationPresets={organizationPresets}
            countryOptions={countryOptions}
            workTypeOptions={workTypeOptions}
            onOpenResolver={() => setResolverOpen(true)}
            onSave={() => createSlice.mutate({ ...slicePayload, title: humanSliceTitle(filters) })}
            onEstimate={() => estimateSlice.mutate()}
            estimate={estimate ?? sliceDoc?.current_estimate}
            materialization={materialization ?? sliceDoc?.current_materialization_plan}
            downloadDir={downloadDir}
            setDownloadDir={setDownloadDir}
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
              if (plan?.materialization_id && !plan?.run_id) runMaterialization.mutate();
              else downloadSlice.mutate();
            }}
            saving={createSlice.isPending}
            estimating={estimateSlice.isPending}
            materializing={downloadSlice.isPending || runMaterialization.isPending || running}
            downloadConfigReady={downloadConfigReady}
            run={run.data}
            sliceDoc={sliceDoc}
            savedSlices={workbench.data?.slices ?? []}
            materializations={workbench.data?.materializations ?? []}
            downloadedDumps={dumps.data?.dumps ?? workbench.data?.dumps ?? []}
            onSelectSavedSlice={selectSavedSlice}
            onSelectMaterialization={selectMaterializationPlan}
            onSelectDownloadedDump={selectDownloadedDump}
            onDeleteSavedSlice={(sliceId) => deleteSavedSlice.mutate(sliceId)}
            onDeleteDownloadedDump={(nextDumpId) => deleteDownloadedDump.mutate(nextDumpId)}
            deletingSliceId={String(deleteSavedSlice.variables ?? "")}
            deletingDumpId={String(deleteDownloadedDump.variables ?? "")}
            selectedSliceId={String(sliceDoc?.slice_id ?? "")}
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
            table={table.data}
            csvUrl={`${API_BASE}${localDataPreviewCsvUrl(localDataKind, { q: dataSearch, runId: effectiveRunId, dumpId: effectiveDumpId, limit: 100_000, sort: dataSort, direction: dataDirection, fractionMode, dataFilters: dataColumnFilters })}`}
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
            selectedAuthorIds={selectedAuthorIds}
            scientometrics={scientometrics.data}
            loadingScientometrics={scientometrics.isFetching}
            metricOptions={primaryMetricOptions}
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
            filters={filters}
            analytics={analytics.data}
            scientometrics={scientometrics.data}
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
            metricOptions={primaryMetricOptions}
            scientometricMetrics={scientometricMetrics}
            setScientometricMetrics={setScientometricMetrics}
            baselineMetric={baselineMetric}
            setBaselineMetric={setBaselineMetric}
            rankTopN={activeTopN}
            topN={activeTopN}
            dataFilters={dataColumnFilters}
            dataSearch={dataSearch}
            selectedAuthorIds={selectedAuthorIds}
            dataSort={dataSort}
            dataDirection={dataDirection}
          />
        )}

        {view === "reports" && (
          <ReportsPage filters={filters} metric={metric} fractionMode={fractionMode} runId={effectiveRunId} dumpId={effectiveDumpId} topN={activeTopN} scientometricMetrics={scientometricMetrics} baselineMetric={baselineMetric} rankTopN={activeTopN} dataFilters={dataColumnFilters} dataSort={dataSort} dataDirection={dataDirection} onBuild={() => buildReport.mutate()} building={buildReport.isPending} state={workbench.data} sliceDoc={sliceDoc} estimate={estimate} materialization={materialization} />
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
  onSave,
  onEstimate,
  estimate,
  materialization,
  downloadDir,
  setDownloadDir,
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
  saving,
  estimating,
  materializing,
  downloadConfigReady,
  run,
  sliceDoc,
  savedSlices,
  materializations,
  downloadedDumps,
  onSelectSavedSlice,
  onSelectMaterialization,
  onSelectDownloadedDump,
  onDeleteSavedSlice,
  onDeleteDownloadedDump,
  deletingSliceId,
  deletingDumpId,
  selectedSliceId,
  selectedDumpId,
}: {
  filters: ActiveFilters;
  setFilters: (value: ActiveFilters) => void;
  domainPresets: ResearchAreaPreset[];
  organizationPresets: OrganizationPreset[];
  countryOptions: SelectOption[];
  workTypeOptions: SelectOption[];
  onOpenResolver: () => void;
  onSave: () => void;
  onEstimate: () => void;
  estimate: any;
  materialization: any;
  downloadDir: string;
  setDownloadDir: (value: string) => void;
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
  saving: boolean;
  estimating: boolean;
  materializing: boolean;
  downloadConfigReady: boolean;
  run: any;
  sliceDoc: any;
  savedSlices: any[];
  materializations: any[];
  downloadedDumps: any[];
  onSelectSavedSlice: (doc: any) => void;
  onSelectMaterialization: (plan: any) => void;
  onSelectDownloadedDump: (dump: any) => void;
  onDeleteSavedSlice: (sliceId: string) => void;
  onDeleteDownloadedDump: (dumpId: string) => void;
  deletingSliceId: string;
  deletingDumpId: string;
  selectedSliceId: string;
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
    if (row.dump) {
      onSelectDownloadedDump(row.dump);
      return;
    }
  };
  const deleteSliceRow = (row: UnifiedSliceRow) => {
    if (!window.confirm(`Удалить локальный срез “${row.title}”? Будут удалены скачанные файлы и таблицы этого среза.`)) return;
    row.dumpIds.forEach(onDeleteDownloadedDump);
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
              selected={Boolean(row.dumpIds.length && row.dumpIds.includes(selectedDumpId))}
              onClick={() => selectSliceRow(row)}
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
            <button className="primary" onClick={onEstimate} disabled={estimating || dateInvalid || subjectMissing}>{estimating ? <Loader2 size={16} className="spin" /> : <Gauge size={16} />} Оценить объем</button>
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
          <button onClick={onEstimate} disabled={estimating || dateInvalid || subjectMissing}>{estimating ? <Loader2 size={16} className="spin" /> : <Gauge size={16} />} Обновить оценку</button>
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
                  {pickingDownloadDir ? <Loader2 size={16} className="spin" /> : <Database size={16} />} Выбрать папку
                </button>
              </div>
              <small className="field-hint">
                Пусто = стандартная папка внутри хранилища данных{dataRoot ? `: ${dataRoot}/raw/openalex_cli/<slice_id>` : ""}. Кнопка открывает системный выбор папки на этом компьютере.
              </small>
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
          <button className="primary" onClick={onRun} disabled={materializing || dateInvalid || subjectMissing || !hasEstimate || !downloadConfigReady || decision.can_execute === false}>{materializing ? <Loader2 size={16} className="spin" /> : <UploadCloud size={16} />} Скачать срез</button>
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
      return {
        key: dumpId || sliceId || String(dump?.raw_jsonl ?? index),
        title: downloadedSliceTitle(dump),
        meta: "скачан",
        detail: [records ? `${fmt(records)} работ` : "", Number.isFinite(mb) && mb > 0 ? `${fmt(mb)} МБ` : "", updated ? `обновлен: ${updated}` : ""].filter(Boolean).join(" · ") || "локальные файлы готовы",
        action: "Выбрать",
        sliceId,
        dumpIds: dumpId ? [dumpId] : [],
        dump,
      };
    })
    .sort((left, right) => left.title.localeCompare(right.title, "ru"));
}

function downloadedSliceTitle(dump: any) {
  const title = String(dump?.title ?? dump?.slice_title ?? "").trim();
  if (title) return title;
  const subject = String(dump?.subject_name ?? dump?.filters?.subject_name ?? "").trim();
  const period = [dump?.from_publication_date, dump?.to_publication_date].map((item) => String(item ?? "").trim()).filter(Boolean).join("–");
  const dumpId = String(dump?.dump_id ?? "").trim();
  return [subject || "Локальный срез", period, dumpId ? dumpId.replace(/^dump_/, "") : ""].filter(Boolean).join(" · ");
}

function ArtifactChoice({
  title,
  meta,
  detail,
  action,
  onClick,
  selected = false,
  deleteAction,
  deleting = false,
  onDelete,
}: {
  title: string;
  meta: string;
  detail: string;
  action: string;
  onClick: () => void;
  selected?: boolean;
  deleteAction?: string;
  deleting?: boolean;
  onDelete?: () => void;
}) {
  return (
    <div className={selected ? "artifact-choice selected" : "artifact-choice"}>
      <div>
        <strong>{title}</strong>
        <span>{meta}</span>
        <small>{detail}</small>
      </div>
      <div className="artifact-choice-actions">
        {selected && <span className="status-chip ok">выбран</span>}
        <button type="button" onClick={onClick}>{action}</button>
        {onDelete && (
          <button type="button" className="danger-button" onClick={onDelete} disabled={deleting || !deleteAction}>
            {deleting ? "Удаление..." : deleteAction}
          </button>
        )}
      </div>
    </div>
  );
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
  const hasDataRestrictions = Boolean(Object.keys(dataColumnFilters).length || dataSearch.trim() || dataSort || dataDirection !== "desc" || selectedAuthorIds.length);
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
          {hasDataRestrictions && <button type="button" className="ghost-button" onClick={resetDataRestrictions}>Сбросить ограничения</button>}
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
        <span className="selection-chip passive">Выбрано авторов: {fmt(selectedAuthorIds.length)}</span>
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
  selectedAuthorIds,
  scientometrics,
  loadingScientometrics,
  metricOptions,
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
  selectedAuthorIds: string[];
  scientometrics?: ScientometricAnalysisPayload;
  loadingScientometrics: boolean;
  metricOptions: SelectOption[];
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
  const distributionMetrics = (scientometrics?.metrics ?? visibleMetrics).filter((item) => visibleMetrics.includes(item));
  const [showBoxplot, setShowBoxplot] = useState(false);
  const [distributionView, setDistributionView] = useState<"normalized" | "raw">("normalized");
  const rankingTable = useMemo(() => selectedAuthorIndexTable(authorIndexTable ?? ranking, visibleMetrics, selectedAuthorIds), [authorIndexTable, ranking, visibleMetrics.join(","), selectedAuthorIds.join("|")]);
  const highlightAuthors = selectedAuthorIds.length ? rankingTable?.rows ?? [] : [];
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
            <small className="field-hint">По этому индексу строится рейтинг и верхний график.</small>
          </Field>
          <Field label="Учет вклада соавторов">
            <select value={fractionMode} onChange={(event) => setFractionMode(event.target.value)}>
              {ensureCurrentOption(fractionModeOptions, fractionMode).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
            <small className="field-hint">Настройка влияет на расчет авторских показателей.</small>
          </Field>
        </div>
        <div className="metric-grid">
          <MetricCard label="Показатель" value={metricLabel(metric)} />
          <MetricCard label="Учет вклада" value={modeLabel(fractionMode)} />
          <MetricCard label="Лимит из “Данных”" value={topN > 0 ? fmt(topN) : "все"} />
          <MetricCard label="Авторов в таблице" value={fmt(authorIndexTable?.total ?? ranking?.total ?? 0)} />
          <MetricCard label="Выбрано вручную" value={selectedAuthorIds.length ? fmt(selectedAuthorIds.length) : "нет"} />
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
            <span>Включайте показатели чекбоксами справа. Значок i рядом с каждым названием показывает смысл показателя и формулу расчета.</span>
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
                <label>
                  <input
                    type="checkbox"
                    checked={active}
                    disabled={pinned}
                    onChange={() => toggleMetric(item.value)}
                  />
                  <span>
                    <b>{item.label}</b>
                    {pinned && <small>основной индекс</small>}
                  </span>
                </label>
                <MetricInfoPopover metricName={item.value} />
              </div>
            );
          })}
        </div>
      </section>
      {scientometrics && (
        <>
          <DistributionComparisonPanel
            payload={scientometrics}
            metrics={distributionMetrics.length ? distributionMetrics : visibleMetrics}
            highlightedAuthors={highlightAuthors}
            loading={loadingScientometrics}
            viewMode={distributionView}
            onViewModeChange={setDistributionView}
          />
          <section className="panel">
            <div className="panel-head split">
              <div>
                <span className="step-badge">Дополнительно</span>
                <h2>Диапазоны значений</h2>
                <p>Этот слой показывает медиану и основной диапазон значений по выбранным индексам. Его можно включать только когда нужен быстрый контроль разброса.</p>
              </div>
              <button type="button" className={showBoxplot ? "choice-pill active" : "choice-pill"} onClick={() => setShowBoxplot(!showBoxplot)}>
                {showBoxplot ? "Скрыть ящик с усами" : "Показать ящик с усами"}
              </button>
            </div>
            {showBoxplot && <MetricBoxplotPanel payload={scientometrics} metrics={distributionMetrics.length ? distributionMetrics : visibleMetrics} />}
          </section>
        </>
      )}
      {!scientometrics && authorIndexTable && (
        <section className="notice">
          <b>График распределений загрузится после аналитического расчета</b>
          <span>Он использует те же ограничения, сортировку, выбранных авторов и число строк, что и вкладка “Данные”.</span>
        </section>
      )}
      <section className="panel table-panel">
        <div className="panel-head">
          <span className="step-badge">Таблица индексов</span>
          <h2>Авторский уровень данных</h2>
          <p>Это таблица авторов с выбранными индексами. Она использует те же ограничения, сортировку и число строк, которые заданы на вкладке “Данные”.</p>
        </div>
        <DataGrid data={rankingTable} onSelect={onSelect} hiddenFields={["author_id"]} />
      </section>
    </div>
  );
}

function selectedAuthorIndexTable(ranking: TableResponse | undefined, metrics: string[], selectedAuthorIds: string[] = []): TableResponse | undefined {
  if (!ranking) return undefined;
  const fields = ranking.fields ?? [];
  const identityFields = ["author_display_name", "author_id"].filter((field) => fields.includes(field));
  const metricFields = metrics.filter((field) => fields.includes(field));
  const contextFields = ["country_code", "subject_name", "n_flagged_works", "n_truncated_works"].filter((field) => fields.includes(field));
  const selectedFields = [...new Set([...identityFields, ...metricFields, ...contextFields])];
  const selected = new Set(selectedAuthorIds.map(String));
  const rows = selected.size
    ? (ranking.rows ?? []).filter((row) => selected.has(String(row.author_id ?? "")))
    : ranking.rows;
  return { ...ranking, fields: selectedFields.length ? selectedFields : fields, rows, total: selected.size ? rows.length : ranking.total };
}

function MetricInfoPopover({ metricName }: { metricName: string }) {
  const description = metricDescription(metricName);
  const formula = metricFormula(metricName);
  return (
    <span className="metric-info-popover-wrap">
      <span className="metric-info-icon" tabIndex={0} aria-label={`Описание показателя ${metricLabel(metricName)}`}>
        <Info size={14} />
      </span>
      <div className="metric-info-popover" role="tooltip">
        <b>{metricLabel(metricName)}</b>
        {description && <span>{description}</span>}
        <MetricFormulaMath metricName={metricName} fallback={formula} />
        <small>Формула применяется только к текущему выбранному срезу.</small>
      </div>
    </span>
  );
}

function MetricFormulaMath({ metricName, fallback }: { metricName: string; fallback: string }) {
  const markup = metricFormulaMarkup(metricName);
  if (markup) return <span className="formula-math" dangerouslySetInnerHTML={{ __html: markup }} />;
  return <code className="formula-fallback">{fallback}</code>;
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
  analytics,
  scientometrics,
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
  metricOptions,
  scientometricMetrics,
  setScientometricMetrics,
  baselineMetric,
  setBaselineMetric,
  rankTopN,
  topN,
  dataFilters,
  dataSearch,
  selectedAuthorIds,
  dataSort,
  dataDirection,
}: {
  filters: ActiveFilters;
  analytics: any;
  scientometrics?: ScientometricAnalysisPayload;
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
  metricOptions: SelectOption[];
  scientometricMetrics: string[];
  setScientometricMetrics: (value: string[]) => void;
  baselineMetric: string;
  setBaselineMetric: (value: string) => void;
  rankTopN: number;
  topN: number;
  dataFilters: TableColumnFilters;
  dataSearch: string;
  selectedAuthorIds: string[];
  dataSort: string;
  dataDirection: "asc" | "desc";
}) {
  const metrics = (scientometrics?.metrics ?? scientometricMetrics).filter(Boolean);
  const analyticsMetrics = metrics.length ? metrics : [metric].filter(Boolean);
  const warnings = scientometrics?.warnings ?? [];
  const [section, setSection] = useState<"overview" | "relations" | "findings">("overview");
  const scientometricMetricParam = scientometricMetrics.join(",");
  const selectionQuery = dataSelectionQuery({ filters: dataFilters, search: dataSearch, sort: dataSort, direction: dataDirection, limit: topN, authorIds: selectedAuthorIds });
  const scientometricParams = filterParams(filters, {
    fraction_mode: fractionMode,
    metrics: scientometricMetricParam,
    baseline_metric: baselineMetric,
    top_n: topN,
    run_id: runId,
    dump_id: dumpId,
    ...selectionQuery,
  });
  const hasAnalyticsExportScope = Boolean(runId || dumpId);
  const analyticsDownloads = {
    json: `${API_BASE}/analytics/scientometrics.json?${scientometricParams.toString()}`,
    descriptive: `${API_BASE}/analytics/scientometrics/descriptive.csv?${scientometricParams.toString()}`,
    correlations: `${API_BASE}/analytics/scientometrics/correlations.csv?${scientometricParams.toString()}`,
    rankShifts: `${API_BASE}/analytics/scientometrics/rank-shifts.csv?${scientometricParams.toString()}`,
    largestRankShifts: `${API_BASE}/analytics/scientometrics/largest-rank-shifts.csv?${scientometricParams.toString()}`,
    outliers: `${API_BASE}/analytics/scientometrics/outliers.csv?${scientometricParams.toString()}`,
    topOutliers: `${API_BASE}/analytics/scientometrics/top-outliers.csv?${scientometricParams.toString()}`,
    findings: `${API_BASE}/analytics/scientometrics/findings.csv?${scientometricParams.toString()}`,
    conclusion: `${API_BASE}/analytics/scientometrics/conclusion.md?${scientometricParams.toString()}`,
  };

  return (
    <div className="stack">
      <section className="notice">
        <b>Аналитика построена по выборке из “Данных”</b>
        <span>Поиск, фильтры, сортировка, выбранные авторы и число строк задаются во вкладке “Данные”. Здесь показаны только понятные графики и выводы по этой выборке.</span>
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
            <h2>Общая картина по выбранной выборке</h2>
            <p>На этой странице нет отдельных фильтров. Все графики ниже автоматически используют поиск, ограничения, сортировку, число строк и выбранных авторов из вкладки “Данные”.</p>
          </div>
          {loadingScientometrics && <span className="status-chip"><Loader2 size={14} className="spin" /> Обновление</span>}
        </div>
        <div className="analytics-context-line">
          <span><b>Строк из “Данных”:</b> {topN > 0 ? fmt(topN) : "все"}</span>
          <span><b>Основной показатель:</b> {metricLabel(baselineMetric)}</span>
          <span><b>Показатели:</b> {analyticsMetrics.map(metricLabel).join(", ")}</span>
        </div>
      </section>
      <div className="analytics-section-tabs" role="tablist" aria-label="Разделы аналитики">
        {[
          ["overview", "Обзор", "типичные значения и заметные отклонения"],
          ["relations", "Связь показателей", "насколько показатели дают похожий порядок"],
          ["findings", "Выводы", "короткие итоги и текст для отчета"],
        ].map(([id, label, detail]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={section === id}
            className={section === id ? "analytics-tab active" : "analytics-tab"}
            onClick={() => setSection(id as "overview" | "relations" | "findings")}
          >
            <b>{label}</b>
            <span>{detail}</span>
          </button>
        ))}
      </div>
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
            {warnings.map((warning: string) => <li key={warning}>{warning}</li>)}
          </ul>
        </section>
      )}
      <section className="metric-grid">
        <MetricCard label="Авторов в анализе" value={fmt(scientometrics?.n_authors ?? 0)} />
        <MetricCard label="Основной показатель" value={metricLabel(String(scientometrics?.scope?.baseline_metric ?? baselineMetric))} />
        <MetricCard label="Авторов в сравнении" value={selectedAuthorIds.length ? fmt(selectedAuthorIds.length) : fmt(scientometrics?.rank_top_n ?? rankTopN)} />
        <MetricCard label="Показателей на графиках" value={fmt(analyticsMetrics.length)} />
      </section>
      {selectedAuthorIds.length > 0 && (
        <section className="notice success">
          <b>Аналитика ограничена вручную выбранными авторами</b>
          <span>Используется {fmt(selectedAuthorIds.length)} авторов из чекбоксов во вкладке “Данные”. Чтобы вернуться к общему числу строк и фильтрам, нажмите “Сбросить ограничения” на странице “Данные”.</span>
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
      {scientometrics && section === "overview" && (
        <>
          <section className="panel">
            <div className="panel-head split">
              <div>
                <span className="step-badge">Скачать</span>
                <h2>Краткая сводка</h2>
              </div>
              <div className="download-inline">
                {hasAnalyticsExportScope && <DownloadLink href={analyticsDownloads.descriptive} label="Сводная таблица" compact />}
              </div>
            </div>
          </section>
          <AnalyticsOverviewPanel payload={scientometrics} metrics={analyticsMetrics} />
        </>
      )}
      {scientometrics && section === "relations" && (
        <>
          <section className="panel">
            <div className="panel-head split">
              <div>
                <span className="step-badge">Скачать</span>
                <h2>Связь показателей и изменение мест</h2>
              </div>
              <div className="download-inline">
                {hasAnalyticsExportScope && <DownloadLink href={analyticsDownloads.correlations} label="Связь показателей" compact />}
                {hasAnalyticsExportScope && <DownloadLink href={analyticsDownloads.rankShifts} label="Изменение мест" compact />}
                {hasAnalyticsExportScope && <DownloadLink href={analyticsDownloads.largestRankShifts} label="Самые большие изменения" compact />}
              </div>
            </div>
          </section>
          <section className="analytics-large-grid">
            <CorrelationMatrixPanels payload={scientometrics} method="spearman" metrics={analyticsMetrics} />
            <RankShiftPanel payload={scientometrics} />
          </section>
        </>
      )}
      {scientometrics && section === "findings" && (
        <>
          <section className="panel">
            <div className="panel-head split">
              <div>
                <span className="step-badge">Скачать</span>
                <h2>Выводы и текст для отчета</h2>
              </div>
              <div className="download-inline">
                {hasAnalyticsExportScope && <DownloadLink href={analyticsDownloads.findings} label="Таблица выводов" compact />}
                {hasAnalyticsExportScope && <DownloadLink href={analyticsDownloads.conclusion} label="Текст заключения" compact />}
              </div>
            </div>
          </section>
          <FindingsPanel payload={scientometrics} />
          <ConclusionDraftPanel payload={scientometrics} />
        </>
      )}
    </div>
  );
}

function ScientometricScopePanel({ payload, fallbackN }: { payload: any; fallbackN: number }) {
  const scope = payload?.scope ?? {};
  return (
    <section className="panel">
      <div className="panel-head">
        <span className="step-badge">Область анализа</span>
        <h2>Паспорт аналитической области</h2>
      </div>
      <div className="key-grid">
        <KeyValue label="Расчет" value={String(scope.run_id ?? "")} />
        <KeyValue label="Локальный срез" value={String(scope.dump_id ?? "")} />
        <KeyValue label="Учет вклада авторов" value={modeLabel(String(scope.fraction_mode ?? ""))} />
        <KeyValue label="Авторов" value={fmt(scope.n_authors ?? payload?.n_authors ?? 0)} />
        <KeyValue label="Авторов в сравнении" value={fmt(scope.rank_top_n ?? fallbackN)} />
        <KeyValue label="Область авторов" value={scope.analysis_author_scope === "all_resolved_authors" ? "все авторы выбранного среза" : String(scope.analysis_author_scope ?? "")} />
      </div>
    </section>
  );
}

function AnalyticsOverviewPanel({ payload, metrics }: { payload: ScientometricAnalysisPayload; metrics: string[] }) {
  const rows = metrics
    .map((metricName) => {
      const descriptive = (payload.descriptive ?? {})[metricName] ?? {};
      const boxplot = (payload.boxplots ?? {})[metricName] ?? {};
      const hasData = [descriptive.median, descriptive.mean, boxplot.outlier_count].some((value) => Number.isFinite(Number(value)));
      return {
        metricName,
        median: Number(descriptive.median ?? boxplot.median ?? 0),
        mean: Number(descriptive.mean ?? 0),
        outliers: Number(boxplot.outlier_count ?? 0),
        hasData,
      };
    })
    .filter((row) => row.hasData);
  const topOutlier = [...rows].sort((left, right) => right.outliers - left.outliers)[0];
  const medianBaseline = rows.find((row) => row.metricName === String(payload.scope?.baseline_metric ?? "")) ?? rows[0];
  return (
    <section className="panel">
      <div className="panel-head">
        <span className="step-badge">Сводка</span>
        <h2>Главное по текущей выборке</h2>
        <p>Подробные распределения и включение отдельных индексов находятся во вкладке “Индексы”. Здесь оставлены только ориентиры для чтения результатов.</p>
      </div>
      <div className="metric-grid">
        <MetricCard label="Авторов в анализе" value={fmt(payload.n_authors ?? 0)} />
        <MetricCard label="Показателей" value={fmt(metrics.length)} />
        <MetricCard label="Медиана основного показателя" value={medianBaseline ? `${metricLabel(medianBaseline.metricName)}: ${formatAnalysisValue(medianBaseline.median)}` : "—"} />
        <MetricCard label="Больше всего выделяющихся значений" value={topOutlier ? `${metricLabel(topOutlier.metricName)}: ${fmt(topOutlier.outliers)}` : "—"} />
      </div>
    </section>
  );
}

const CHART_COLORS = ["#155e75", "#167343", "#8a5a00", "#5b5fc7", "#9a3412", "#0f766e", "#7c3aed", "#be123c"];

function DistributionComparisonPanel({
  payload,
  metrics,
  highlightedAuthors,
  loading = false,
  viewMode,
  onViewModeChange,
}: {
  payload: ScientometricAnalysisPayload;
  metrics: string[];
  highlightedAuthors?: Record<string, unknown>[];
  loading?: boolean;
  viewMode: "normalized" | "raw";
  onViewModeChange: (value: "normalized" | "raw") => void;
}) {
  const visibleMetrics = metrics.filter(Boolean);
  const rows = visibleMetrics
    .map((metricName) => ({ metricName, rows: rawDistributionRows(payload, metricName) }))
    .filter((item) => item.rows.length > 0);
  const normalizedRows = normalizedDistributionRows(payload, visibleMetrics);
  const highlightRows = selectedAuthorDistributionMarkers(payload, visibleMetrics, highlightedAuthors ?? [], viewMode, normalizedRows);
  const hasHighlights = highlightRows.length > 0;
  return (
    <section className="panel analytics-main-chart">
      <div className="panel-head split">
        <div>
          <span className="step-badge">Распределение</span>
          <h2>Сравнение наукометрических индексов</h2>
          <p>{viewMode === "normalized" ? "Значения каждого индекса приведены к общей шкале 0–100, чтобы сравнивать форму распределения между показателями." : "По горизонтали показано исходное значение индекса, по вертикали количество авторов. Каждый показатель показан отдельно, чтобы не смешивать разные единицы."}</p>
        </div>
        {loading && <span className="status-chip"><Loader2 size={14} className="spin" /> Обновление</span>}
      </div>
      <div className="segmented-row" role="group" aria-label="Масштаб графика">
        <button type="button" className={viewMode === "normalized" ? "choice-pill active" : "choice-pill"} onClick={() => onViewModeChange("normalized")}>
          Общая шкала 0–100
        </button>
        <button type="button" className={viewMode === "raw" ? "choice-pill active" : "choice-pill"} onClick={() => onViewModeChange("raw")}>
          Исходные значения
        </button>
      </div>
      {hasHighlights && (
        <div className="selection-summary active">
          <span>Красные точки показывают выбранных авторов из таблицы “Данные”.</span>
        </div>
      )}
      {visibleMetrics.length === 0 || (viewMode === "normalized" ? normalizedRows.length === 0 : rows.length === 0) ? (
        <EmptyState title="Выберите хотя бы один индекс" detail="Включите показатель в блоке “Какие индексы показывать” выше." />
      ) : viewMode === "normalized" ? (
        <div className="chart-box main-distribution-chart">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={normalizedRows} margin={{ left: 10, right: 24, top: 16, bottom: 18 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="position" type="number" domain={[0, 100]} tickFormatter={(value) => `${fmt(value)}`} label={{ value: "Значение индекса, приведенное к общей шкале", position: "insideBottom", offset: -8 }} />
              <YAxis allowDecimals={false} label={{ value: "Авторов", angle: -90, position: "insideLeft" }} />
              <Tooltip
                labelFormatter={(value) => `Общая шкала: ${fmt(value)}`}
                formatter={(value, name, item: any) => {
                  if (item?.payload?.author) return [`${metricLabel(String(item.payload.metricName))}: ${formatAnalysisValue(item.payload.value)}`, item.payload.author];
                  return [fmt(value), metricLabel(String(name))];
                }}
              />
              {visibleMetrics.map((metricName, index) => (
                <Line
                  key={metricName}
                  type="monotone"
                  dataKey={metricName}
                  name={metricName}
                  stroke={CHART_COLORS[index % CHART_COLORS.length]}
                  strokeWidth={3}
                  dot={false}
                  activeDot={{ r: 4 }}
                  connectNulls
                />
              ))}
              {hasHighlights && (
                <Scatter
                  name="Выбранные авторы"
                  data={highlightRows}
                  dataKey="count"
                  fill="#be123c"
                  shape="circle"
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="distribution-small-multiples">
          {rows.map((item, index) => (
            <div key={item.metricName} className="distribution-multiple-card">
              <div className="distribution-multiple-head">
                <b>{metricLabel(item.metricName)}</b>
                <span>{fmt(item.rows.reduce((sum, row) => sum + row.count, 0))} авторов</span>
              </div>
              <div className="chart-box index-distribution-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={item.rows} margin={{ left: 8, right: 14, top: 8, bottom: 18 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="center" type="number" tickFormatter={(value) => fmt(value)} />
                    <YAxis allowDecimals={false} />
                    <Tooltip
                      labelFormatter={(_, payloadRows) => {
                        const row = payloadRows?.[0]?.payload;
                        if (row?.author) return `${row.author}: ${formatAnalysisValue(row.value)}`;
                        return row ? `${formatAnalysisValue(row.lo)} – ${formatAnalysisValue(row.hi)}` : "";
                      }}
                      formatter={(value, name, item: any) => {
                        if (item?.payload?.author) return [`${metricLabel(String(item.payload.metricName))}: ${formatAnalysisValue(item.payload.value)}`, "выбранный автор"];
                        return [fmt(value), "авторов"];
                      }}
                    />
                    <Line type="monotone" dataKey="count" stroke={CHART_COLORS[index % CHART_COLORS.length]} strokeWidth={3} dot={false} activeDot={{ r: 4 }} name="Авторов" />
                    <Scatter
                      name="Выбранные авторы"
                      data={highlightRows.filter((row) => row.metricName === item.metricName)}
                      dataKey="count"
                      fill="#be123c"
                      shape="circle"
                    />
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

function normalizedDistributionRows(payload: ScientometricAnalysisPayload, metrics: string[]) {
  const prepared = metrics
    .map((metricName) => {
      const rows = rawDistributionRows(payload, metricName);
      if (!rows.length) return null;
      const min = Math.min(...rows.map((row) => row.lo));
      const max = Math.max(...rows.map((row) => row.hi));
      return { metricName, rows, min, max };
    })
    .filter(Boolean) as Array<{ metricName: string; rows: ReturnType<typeof rawDistributionRows>; min: number; max: number }>;
  const maxBins = Math.max(0, ...prepared.map((item) => item.rows.length));
  if (!maxBins) return [];
  return Array.from({ length: maxBins }, (_, index) => {
    const position = maxBins === 1 ? 0 : Math.round((index / (maxBins - 1)) * 100);
    const row: Record<string, number> = { position };
    prepared.forEach((item) => {
      const sourceIndex = Math.round((index / Math.max(1, maxBins - 1)) * Math.max(0, item.rows.length - 1));
      row[item.metricName] = Number(item.rows[sourceIndex]?.count ?? 0);
    });
    return row;
  });
}

type DistributionMarker = {
  position?: number;
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
  viewMode: "normalized" | "raw",
  normalizedRows: Array<Record<string, number>>,
): DistributionMarker[] {
  if (!authors.length) return [];
  return metrics.flatMap((metricName) => {
    const bins = rawDistributionRows(payload, metricName);
    if (!bins.length) return [];
    const min = Math.min(...bins.map((row) => row.lo));
    const max = Math.max(...bins.map((row) => row.hi));
    const out: DistributionMarker[] = [];
    authors.forEach((author) => {
        const value = Number(author[metricName]);
        if (!Number.isFinite(value)) return;
        const authorName = String(author.author_display_name || author.author_id || "Выбранный автор");
        if (viewMode === "normalized") {
          const position = max > min ? Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100)) : 50;
          const nearest = nearestDistributionRow(normalizedRows, position);
          out.push({
            position,
            count: Math.max(1, Number(nearest?.[metricName] ?? 1)),
            value,
            metricName,
            author: authorName,
          });
          return;
        }
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

function nearestDistributionRow(rows: Array<Record<string, number>>, position: number) {
  return rows.reduce<Record<string, number> | null>((best, row) => {
    if (!best) return row;
    return Math.abs(Number(row.position) - position) < Math.abs(Number(best.position) - position) ? row : best;
  }, null);
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

function MetricBoxplotPanel({ payload, metrics }: { payload: ScientometricAnalysisPayload; metrics: string[] }) {
  const rows = metrics
    .map((metricName) => {
      const boxplot = (payload.boxplots ?? {})[metricName] ?? {};
      const min = numberOrNull(boxplot.min_whisker ?? boxplot.min);
      const q1 = numberOrNull(boxplot.q1);
      const median = numberOrNull(boxplot.median);
      const q3 = numberOrNull(boxplot.q3);
      const max = numberOrNull(boxplot.max_whisker ?? boxplot.max);
      if (![min, q1, median, q3, max].every((value) => value !== null)) return null;
      const left = Math.min(min as number, q1 as number, median as number, q3 as number, max as number);
      const right = Math.max(min as number, q1 as number, median as number, q3 as number, max as number);
      const pct = (value: number | null) => {
        if (value === null || right <= left) return 50;
        return Math.max(0, Math.min(100, ((value - left) / (right - left)) * 100));
      };
      return {
        metricName,
        min: min as number,
        q1: q1 as number,
        median: median as number,
        q3: q3 as number,
        max: max as number,
        outliers: Number(boxplot.outlier_count ?? 0),
        minPct: pct(min),
        q1Pct: pct(q1),
        medianPct: pct(median),
        q3Pct: pct(q3),
        maxPct: pct(max),
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
      minPct: number;
      q1Pct: number;
      medianPct: number;
      q3Pct: number;
      maxPct: number;
    }>;
  if (!rows.length) {
    return <EmptyState title="Нет диапазонов" detail="Для выбранных индексов нет достаточного числа числовых значений." />;
  }
  return (
    <div className="boxplot-simple-list">
      <div className="boxplot-simple-scale" aria-hidden="true">
        <span>меньше</span>
        <span>больше</span>
      </div>
      {rows.map((row) => {
        const boxLeft = Math.min(row.q1Pct, row.q3Pct);
        const boxWidth = Math.max(1.5, Math.abs(row.q3Pct - row.q1Pct));
        const whiskerLeft = Math.min(row.minPct, row.maxPct);
        const whiskerWidth = Math.max(1.5, Math.abs(row.maxPct - row.minPct));
        return (
          <div key={row.metricName} className="boxplot-simple-row">
            <div className="boxplot-simple-label">
              <b>{metricLabel(row.metricName)}</b>
              <span>медиана {formatAnalysisValue(row.median)}{row.outliers ? ` · выделяется ${fmt(row.outliers)}` : ""}</span>
            </div>
            <div
              className="boxplot-simple-track"
              title={`Минимум ${formatAnalysisValue(row.min)}, 25% ${formatAnalysisValue(row.q1)}, медиана ${formatAnalysisValue(row.median)}, 75% ${formatAnalysisValue(row.q3)}, максимум ${formatAnalysisValue(row.max)}`}
            >
              <span className="boxplot-simple-whisker" style={{ left: `${whiskerLeft}%`, width: `${whiskerWidth}%` }} />
              <span className="boxplot-simple-cap" style={{ left: `${row.minPct}%` }} />
              <span className="boxplot-simple-cap" style={{ left: `${row.maxPct}%` }} />
              <span className="boxplot-simple-box" style={{ left: `${boxLeft}%`, width: `${boxWidth}%` }} />
              <span className="boxplot-simple-median" style={{ left: `${row.medianPct}%` }} />
            </div>
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

function rankShiftChartRows(payload: ScientometricAnalysisPayload) {
  const comparisons = payload.rank_comparisons ?? {};
  return Object.entries(comparisons)
    .flatMap(([compareMetric, comparison]: [string, any]) => {
      const rows = (comparison?.largest_shifts ?? []) as Array<Record<string, unknown>>;
      return rows.slice(0, 8).map((row) => {
        const author = String(row.author_display_name || row.author_id || "Автор");
        const value = Number(row.abs_rank_delta ?? 0);
        return {
          label: `${author.length > 24 ? `${author.slice(0, 23)}...` : author} · ${metricShortLabel(compareMetric)}`,
          tooltip: `${author}: ${metricLabel(String(comparison?.baseline_metric ?? payload.scope?.baseline_metric ?? ""))} → ${metricLabel(compareMetric)}`,
          value,
        };
      });
    })
    .filter((row) => Number.isFinite(row.value) && row.value > 0)
    .sort((left, right) => right.value - left.value)
    .slice(0, 14);
}

const CORRELATION_METRIC_GROUPS = [
  { title: "Публикации и цитирование", metrics: ["p", "c", "c_frac", "cpp"] },
  { title: "Классические индексы", metrics: ["h", "i10", "g", "m_local"] },
  { title: "Дополнительные индексы", metrics: ["f5", "fm5", "iupv", "islv", "lrdi"] },
];

function CorrelationMatrixPanels({ payload, method, metrics }: { payload: any; method: "spearman" | "pearson_log1p" | "kendall_tau_b"; metrics: string[] }) {
  const matrix = method === "kendall_tau_b" ? payload?.correlations?.kendall_tau_b?.matrix ?? {} : payload?.correlations?.[method] ?? {};
  const skipped = payload?.correlations?.kendall_tau_b?.skipped ?? [];
  const groups = correlationMetricGroups(metrics);
  return (
    <section className="panel correlation-panel-wide">
      <div className="panel-head">
        <span className="step-badge">Связь показателей</span>
        <h2>{correlationLabel(method)} по группам</h2>
        <p>Матрицы разделены по смысловым группам, чтобы сравнение мест в рейтинге читалось проще.</p>
      </div>
      {method === "kendall_tau_b" && skipped.length > 0 && <div className="notice warn"><b>Часть пар не рассчитана</b><span>Слишком много наблюдений для выбранного способа сравнения. Уменьшите число строк или уточните фильтр во вкладке “Данные”.</span></div>}
      {groups.length === 0 ? (
        <EmptyState title="Недостаточно показателей" detail="Для матрицы нужно выбрать минимум два показателя одной смысловой группы." />
      ) : (
        <div className="correlation-matrix-grid">
          {groups.map((group) => (
            <div key={group.title} className="correlation-matrix-card">
              <b>{group.title}</b>
              <div className="heatmap-grid compact-heatmap" style={{ gridTemplateColumns: `minmax(96px, 1fr) repeat(${group.metrics.length}, minmax(56px, 1fr))` }}>
                <span />
                {group.metrics.map((metricName) => <b key={metricName}>{metricShortLabel(metricName)}</b>)}
                {group.metrics.map((left) => (
                  <div className="heatmap-row-fragment" key={left}>
                    <b>{metricShortLabel(left)}</b>
                    {group.metrics.map((right) => {
                      const value = matrix?.[left]?.[right];
                      return <span key={`${group.title}-${left}-${right}`} style={{ background: correlationColor(value) }}>{value === null || value === undefined ? "—" : fmt(value)}</span>;
                    })}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function correlationMetricGroups(metrics: string[]) {
  const selected = new Set(metrics);
  const groups = CORRELATION_METRIC_GROUPS
    .map((group) => ({
      title: group.title,
      metrics: group.metrics.filter((metricName) => selected.has(metricName)),
    }))
    .filter((group) => group.metrics.length >= 2);
  const grouped = new Set(groups.flatMap((group) => group.metrics));
  const other = metrics.filter((metricName) => !grouped.has(metricName));
  if (other.length >= 2) {
    groups.push({ title: "Другие выбранные показатели", metrics: other });
  }
  return groups;
}

function RankShiftPanel({ payload }: { payload: ScientometricAnalysisPayload }) {
  const rows = rankShiftChartRows(payload);
  return (
    <section className="panel">
      <div className="panel-head">
        <span className="step-badge">Изменение мест</span>
        <h2>Как меняются места авторов при смене показателя</h2>
        <p>Диаграмма показывает самые большие изменения места относительно основного показателя. Чем выше столбец, тем сильнее автор меняет позицию.</p>
      </div>
      {rows.length === 0 ? (
        <EmptyState title="Изменений мест нет" detail="Выберите минимум два показателя для сравнения или увеличьте выборку авторов." />
      ) : (
        <div className="chart-box compact-chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis type="category" dataKey="label" width={150} />
              <Tooltip formatter={(value, _name, item: any) => [fmt(value), item?.payload?.tooltip ?? "Изменение места"]} />
              <Bar dataKey="value" fill="#155e75" name="Изменение места" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

function FindingsPanel({ payload }: { payload: ScientometricAnalysisPayload }) {
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
        <MetricCard label="Рекомендуемый показатель" value={summary.candidate_metric ? metricLabel(String(summary.candidate_metric)) : "—"} />
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

function ConclusionDraftPanel({ payload }: { payload: ScientometricAnalysisPayload }) {
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
              <small>Показатели: {(paragraph.evidence_metrics ?? []).map(metricLabel).join(", ")}</small>
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
          <span>Показатели: {scientometricMetrics.map(metricLabel).join(", ")}. Основной показатель: {metricLabel(baselineMetric)}. Строк из “Данных”: {rankTopN > 0 ? fmt(rankTopN) : "все"}. Ограничений по столбцам: {activeRestrictionCount}.</span>
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

function SingleChoicePicker({ options, selected, onChange }: { options: SelectOption[]; selected: string; onChange: (value: string) => void }) {
  return (
    <div className="choice-grid compact" role="group">
      {options.map((item) => (
        <button
          key={item.value}
          type="button"
          className={String(selected) === String(item.value) ? "choice-pill active" : "choice-pill"}
          onClick={() => onChange(String(item.value))}
          title={item.description}
        >
          {item.label}
        </button>
      ))}
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
      <span><Gauge size={15} /> {running ? `${progress.label} · ${progress.percent}%` : run?.status ?? state?.workflow?.active_stage ?? "idle"}</span>
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
  return (
    <div className={`run-card ${run.status === "failed" ? "error" : ""} ${live.active ? "live" : ""}`}>
      <div className="run-live-head">
        <span className={`live-dot ${live.active ? "active" : ""}`} aria-hidden="true" />
        <div>
          <b>{live.title}</b>
          <small>{live.detail}</small>
        </div>
      </div>
        <span>{runActionTitle(run.action)}: {run.run_id}</span>
      <ProgressBar percent={progress.percent} label={progress.label} tone={run.status === "failed" ? "error" : "normal"} />
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
  return "Задача";
}

function runLiveState(run: WorkbenchRun) {
  const action = String(run.action ?? "");
  const status = String(run.status ?? "");
  const isSliceLoad = action === "build_from_openalex" || action === "fetch_slice_dump";
  if (status === "queued") return { active: true, title: "Срез в очереди", detail: "Загрузка начнется автоматически." };
  if (status === "running" && isSliceLoad) return { active: true, title: "Загрузка среза", detail: "Статус обновляется в реальном времени." };
  if (status === "running") return { active: true, title: "Выполнение", detail: "Статус обновляется в реальном времени." };
  if (status === "completed" && isSliceLoad) return { active: false, title: "Срез готов", detail: "Локальные таблицы доступны для анализа." };
  if (status === "completed") return { active: false, title: "Готово", detail: "Задача завершена." };
  if (status === "failed") return { active: false, title: "Ошибка выполнения", detail: "Подробности показаны ниже и в уведомлении." };
  return { active: false, title: action || "Run", detail: status || "нет статуса" };
}

function ProgressBar({ percent, label, tone = "normal" }: { percent: number; label: string; tone?: "normal" | "error" }) {
  return (
    <div className="progress-group" aria-label={`${label}: ${percent}%`}>
      <div className="progress-meta">
        <span>{label}</span>
        <b>{percent}%</b>
      </div>
      <div className={`progress-track ${tone}`}>
        <span style={{ width: `${percent}%` }} />
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

function metricShortLabel(value: string) {
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
