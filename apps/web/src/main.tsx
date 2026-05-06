import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  BarChart3,
  BookOpenCheck,
  CheckCircle2,
  Database,
  Download,
  FileJson,
  Gauge,
  GitCompareArrows,
  Layers3,
  Loader2,
  Search,
  Settings2,
  Sigma,
  Sparkles,
  UploadCloud,
  X,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { API_BASE, getJson, postJson, type TableResponse } from "./api";
import {
  DEFAULT_FILTERS,
  countryLabel,
  filterParams,
  fmt,
  resolveCountryInput,
  metricLabel,
  type ActiveFilters,
  type OrganizationPreset,
  type ResearchAreaPreset,
  type SelectOption,
} from "./domain";
import { DataGrid, DetailDrawer, EmptyState } from "./components/ui";
import {
  analyticsRankingUrl,
  analyticsUrl,
  buildDownloadPolicy,
  buildSlicePayload,
  bytesToMb,
  humanSliceTitle,
  mutationError,
  pageLead,
  pageTitle,
  progressForRun,
  rankingChartRows,
  sliceSubjectTitle,
  viewFromHash,
  type EntitySuggestion,
  type ResolverTab,
  type View,
  type WorkbenchRun,
} from "./workbench";
import "./styles.css";

const queryClient = new QueryClient({
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
  { id: "enrichment", label: "Профили", icon: <Sparkles size={17} /> },
  { id: "rankings", label: "Индексы", icon: <Sigma size={17} /> },
  { id: "cohorts", label: "Когорты", icon: <GitCompareArrows size={17} /> },
  { id: "statistics", label: "Графики", icon: <BarChart3 size={17} /> },
  { id: "reports", label: "Отчеты", icon: <Download size={17} /> },
  { id: "passports", label: "Паспорта", icon: <FileJson size={17} /> },
];

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Workbench />
    </QueryClientProvider>
  );
}

function Workbench() {
  const qc = useQueryClient();
  const [view, setView] = useState<View>(() => viewFromHash(window.location.hash));
  const [filters, setFilters] = useState<ActiveFilters>(DEFAULT_FILTERS);
  const [metric, setMetric] = useState("h");
  const [fractionMode, setFractionMode] = useState("strict_authors_count");
  const [topN, setTopN] = useState(0);
  const [storageProfileId, setStorageProfileId] = useState("");
  const [sourceStrategy, setSourceStrategy] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [sliceDoc, setSliceDoc] = useState<any>(null);
  const [estimate, setEstimate] = useState<any>(null);
  const [materialization, setMaterialization] = useState<any>(null);
  const [runId, setRunId] = useState("");
  const [resolverOpen, setResolverOpen] = useState(false);
  const [selected, setSelected] = useState<{ kind: "author" | "work"; id: string } | null>(null);
  const [tableName, setTableName] = useState("authors_local_metrics");
  const [tableQ, setTableQ] = useState("");
  const [selectedCohortId, setSelectedCohortId] = useState("");
  const [cohortSource, setCohortSource] = useState<"top_n" | "metric_filter">("top_n");
  const [cohortName, setCohortName] = useState("Top авторов текущего среза");
  const [minPublications, setMinPublications] = useState(0);
  const [minH, setMinH] = useState(0);
  const [minMetricValue, setMinMetricValue] = useState(0);
  const navRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    const onHashChange = () => setView(viewFromHash(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
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
  const state = useQuery({ queryKey: ["state"], queryFn: () => getJson<any>("/state") });
  const workbench = useQuery({ queryKey: ["workbench"], queryFn: () => getJson<any>("/workbench") });
  const dumps = useQuery({ queryKey: ["dumps"], queryFn: () => getJson<any>("/dumps?limit=50") });
  const cohorts = useQuery({ queryKey: ["cohorts"], queryFn: () => getJson<any>("/cohorts?limit=50") });
  const countries = useQuery({ queryKey: ["countries"], queryFn: () => getJson<any>("/openalex/countries?limit=50") });
  const workTypes = useQuery({ queryKey: ["work-types"], queryFn: () => getJson<any>("/openalex/work-types?limit=50") });
  const rateLimit = useQuery({
    queryKey: ["openalex-rate-limit", apiKey],
    queryFn: () => getJson<any>(`/openalex/rate-limit?api_key=${encodeURIComponent(apiKey.trim())}`),
    enabled: Boolean(apiKey.trim()),
  });
  const cohortStats = useQuery({
    queryKey: ["cohort-stats", selectedCohortId],
    queryFn: () => postJson<any>(`/cohorts/${encodeURIComponent(selectedCohortId)}/statistics`, {}),
    enabled: Boolean(selectedCohortId),
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
  const activeDumpId = extractDumpId(run.data);
  const filterKey = useMemo(() => JSON.stringify(filters), [filters]);
  const hasLocalAnalyticsData = Boolean(runId || activeDumpId || state.data?.tables?.author_work?.rows || state.data?.tables?.indices?.rows);
  const table = useQuery({
    queryKey: ["table", tableName, tableQ, topN, runId, activeDumpId],
    queryFn: () => getJson<TableResponse>(`/tables/${tableName}?q=${encodeURIComponent(tableQ)}&run_id=${encodeURIComponent(runId)}&dump_id=${encodeURIComponent(activeDumpId)}&limit=${Math.max(1, topN || 1)}`),
  });
  const analytics = useQuery({
    queryKey: ["analytics", metric, fractionMode, runId, activeDumpId, filterKey],
    queryFn: () => getJson<any>(analyticsUrl(filters, fractionMode, metric, runId, activeDumpId)),
    enabled: hasLocalAnalyticsData,
  });
  const ranking = useQuery({
    queryKey: ["analytics-ranking", metric, fractionMode, runId, activeDumpId, filterKey, topN],
    queryFn: () => getJson<TableResponse>(analyticsRankingUrl(filters, fractionMode, metric, runId, activeDumpId, Math.max(1, topN || 100))),
    enabled: hasLocalAnalyticsData,
  });
  const detail = useQuery({
    queryKey: ["detail", selected, runId, activeDumpId],
    queryFn: () => getJson<any>(
      selected?.kind === "author"
        ? `/authors/${encodeURIComponent(selected.id)}?run_id=${encodeURIComponent(runId)}&dump_id=${encodeURIComponent(activeDumpId)}`
        : `/works/${encodeURIComponent(selected?.id ?? "")}?run_id=${encodeURIComponent(runId)}&dump_id=${encodeURIComponent(activeDumpId)}`,
    ),
    enabled: Boolean(selected),
  });

  const domainPresets = (registry.data?.domain_presets ?? []) as ResearchAreaPreset[];
  const organizationPresets = (registry.data?.organization_presets ?? []) as OrganizationPreset[];
  const countryOptions = catalogOptions(countries.data?.results ?? []);
  const workTypeOptions = catalogOptions(workTypes.data?.results ?? []);
  const storageProfileOptions = configuredOptions(catalog.data?.storage_profiles ?? []);
  const uiOptions = catalog.data?.ui_options ?? {};
  const topNOptions = configuredOptions(uiOptions.top_n ?? []);
  const primaryMetricOptions = configuredOptions(catalog.data?.metrics ?? []);
  const fractionModeOptions = configuredOptions(catalog.data?.fraction_modes ?? []);
  const tableOptions = Object.keys(state.data?.tables ?? {}).map((value) => ({ value, label: value }));
  const sourceStrategyOptions = configuredOptions(catalog.data?.data_sources ?? [])
    .filter((item) => ["openalex_cli"].includes(item.value));
  const defaultStorageProfileId = String(defaultOption(storageProfileOptions)?.value ?? "minimal_analytics");
  const defaultSourceStrategy = String(defaultOption(sourceStrategyOptions)?.value ?? "openalex_cli");
  const defaultTopN = Number(defaultOption(topNOptions)?.value ?? 100);
  const activeStorageProfileId = storageProfileId || defaultStorageProfileId;
  const activeSourceStrategy = sourceStrategy || defaultSourceStrategy;
  const activeTopN = topN || defaultTopN;
  const payload = useMemo(() => buildSlicePayload(filters, fractionMode, apiKey, fractionModeOptions.map((item) => item.value)), [filters, fractionMode, apiKey, fractionModeOptions]);
  const downloadConfigReady = Boolean(activeStorageProfileId && activeSourceStrategy);
  const downloadPolicy = useMemo(() => buildDownloadPolicy(), []);

  useEffect(() => {
    if (!storageProfileId && defaultStorageProfileId) setStorageProfileId(defaultStorageProfileId);
  }, [storageProfileId, defaultStorageProfileId]);

  useEffect(() => {
    if (!sourceStrategy && defaultSourceStrategy) setSourceStrategy(defaultSourceStrategy);
  }, [sourceStrategy, defaultSourceStrategy]);

  useEffect(() => {
    if (!topN && defaultTopN) setTopN(defaultTopN);
  }, [topN, defaultTopN]);

  const createSlice = useMutation({
    mutationFn: (body: any) => postJson<any>("/slices", body),
    onSuccess: (doc) => {
      setSliceDoc(doc);
      qc.invalidateQueries({ queryKey: ["workbench"] });
    },
  });
  const estimateSlice = useMutation({
    mutationFn: async () => {
      const doc = await postJson<any>("/slices", { ...payload, title: humanSliceTitle(filters) });
      setSliceDoc(doc);
      const result = await postJson<any>(`/slices/${encodeURIComponent(doc.slice_id)}/estimate`, { download_policy: downloadPolicy });
      return { doc, result };
    },
    onSuccess: ({ doc, result }) => {
      setSliceDoc({ ...doc, latest_estimate: result, state: "estimated" });
      setEstimate(result);
      qc.invalidateQueries({ queryKey: ["workbench"] });
      navigate("slices");
    },
  });
  const createMaterialization = useMutation({
    mutationFn: async () => {
      const doc = sliceDoc ?? (await postJson<any>("/slices", { ...payload, title: humanSliceTitle(filters) }));
      setSliceDoc(doc);
      return postJson<any>(`/slices/${encodeURIComponent(doc.slice_id)}/materialization-plans`, { storage_profile_id: activeStorageProfileId, source_strategy: activeSourceStrategy, download_policy: downloadPolicy });
    },
    onSuccess: (plan) => {
      setMaterialization(plan);
      qc.invalidateQueries({ queryKey: ["workbench"] });
    },
  });
  const runMaterialization = useMutation({
    mutationFn: async () => {
      const plan = materialization ?? (await createMaterialization.mutateAsync());
      return postJson<any>(`/materializations/${encodeURIComponent(plan.materialization_id)}/run`, apiKey.trim() ? { api_key: apiKey.trim() } : {});
    },
    onSuccess: (result) => {
      setApiKey("");
      setRunId(result?.run?.run_id ?? "");
      qc.invalidateQueries({ queryKey: ["workbench"] });
      navigate("data");
    },
  });
  const downloadSlice = useMutation({
    mutationFn: async () => {
      const doc = await postJson<any>("/slices", { ...payload, title: humanSliceTitle(filters) });
      setSliceDoc(doc);
      const estimateResult = await postJson<any>(`/slices/${encodeURIComponent(doc.slice_id)}/estimate`, { download_policy: downloadPolicy });
      setEstimate(estimateResult);
      setSliceDoc({ ...doc, latest_estimate: estimateResult, state: "estimated" });
      const decision = estimateResult?.decision ?? {};
      if (decision.can_execute === false) {
        const reason = [...(decision.reasons ?? []), ...(decision.warnings ?? [])].filter(Boolean).join(" ");
        throw new Error(reason || "OpenAlex не вернул работ для выбранных фильтров.");
      }
      const plan = await postJson<any>(`/slices/${encodeURIComponent(doc.slice_id)}/materialization-plans`, { storage_profile_id: activeStorageProfileId, source_strategy: activeSourceStrategy, download_policy: downloadPolicy });
      setMaterialization(plan);
      return postJson<any>(`/materializations/${encodeURIComponent(plan.materialization_id)}/run`, apiKey.trim() ? { api_key: apiKey.trim() } : {});
    },
    onSuccess: (result) => {
      setApiKey("");
      setRunId(result?.run?.run_id ?? "");
      qc.invalidateQueries({ queryKey: ["workbench"] });
      navigate("data");
    },
  });
  const recalculate = useMutation({
    mutationFn: () => postJson<any>("/runs", { action: "recalculate", payload: { ...payload, dump_id: activeDumpId || undefined } }),
    onSuccess: (result) => {
      setRunId(result.run_id);
      navigate("rankings");
    },
  });
  const buildReport = useMutation({
    mutationFn: () => postJson<any>(`/reports/build?${filterParams(filters, { metric, fraction_mode: fractionMode, run_id: runId, dump_id: activeDumpId, limit: Math.max(1, activeTopN || 1), cohort_id: selectedCohortId }).toString()}`, {}),
    onSuccess: () => qc.invalidateQueries(),
  });
  const createCohort = useMutation({
    mutationFn: () => postJson<any>("/cohorts", {
      slice_id: sliceDoc?.slice_id ?? "current",
      run_id: runId || undefined,
      dump_id: activeDumpId || undefined,
      name: cohortName,
      source: cohortSource,
      metric,
      fraction_mode: fractionMode,
      top_n: cohortSource === "top_n" ? activeTopN : undefined,
      min_publications: minPublications || undefined,
      min_h: minH || undefined,
      min_metric_value: cohortSource === "metric_filter" && minMetricValue ? minMetricValue : undefined,
      country_code: filters.country_code || undefined,
      institution_id: filters.institution_id || undefined,
      subject_level: filters.subject_level || undefined,
      subject_id: filters.subject_id || undefined,
      filter_mode: filters.filter_mode || undefined,
      keyword_id: filters.keyword_id || undefined,
      keyword_display_name: filters.keyword_name || undefined,
      text_search_query: filters.text_search_query || undefined,
      author_id: filters.author_id || undefined,
      author_display_name: filters.author_name || undefined,
      author_orcid: filters.author_orcid || undefined,
      doi: filters.doi || undefined,
      affiliation_mode: filters.affiliation_mode || undefined,
      source_id: filters.source_id || undefined,
      source_display_name: filters.source_name || undefined,
      source_type: filters.source_type || undefined,
      language: filters.language || undefined,
      open_access_is_oa: filters.open_access_is_oa || undefined,
      has_abstract: filters.has_abstract || undefined,
      min_cited_by_count: filters.min_cited_by_count ? Number(filters.min_cited_by_count) : undefined,
      from_publication_date: filters.from_publication_date || undefined,
      to_publication_date: filters.to_publication_date || undefined,
      work_type: filters.work_type || undefined,
    }),
    onSuccess: (cohort) => {
      setSelectedCohortId(cohort.cohort_id ?? "");
      qc.invalidateQueries({ queryKey: ["cohorts"] });
      qc.invalidateQueries({ queryKey: ["cohort-stats"] });
      navigate("cohorts");
    },
  });

  useEffect(() => {
    const first = cohorts.data?.cohorts?.[0]?.cohort_id;
    if (!selectedCohortId && first) setSelectedCohortId(first);
  }, [cohorts.data, selectedCohortId]);

  const running = run.data?.status === "queued" || run.data?.status === "running";
  const tables = state.data?.tables ?? {};
  const qualityCounts = state.data?.quality?.quality_counts ?? {};
  const rankingRows = ranking.data?.rows ?? [];
  const chartRows = useMemo(() => rankingChartRows(rankingRows, metric), [rankingRows, metric]);
  const errors = [
    mutationError(createSlice.error),
    mutationError(estimateSlice.error),
    mutationError(createMaterialization.error),
    mutationError(runMaterialization.error),
    mutationError(downloadSlice.error),
    mutationError(recalculate.error),
    mutationError(createCohort.error),
  ].filter(Boolean);

  return (
    <motion.main className="app-shell" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.22, ease: "easeOut" }}>
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
        <StatusRail state={state.data} run={run.data} running={running} />
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
            <span className="eyebrow">Slice-centric pipeline</span>
            <h1>{pageTitle(view)}</h1>
            <p>{pageLead(view)}</p>
          </div>
        </header>
        <WorkflowStepper view={view} estimate={estimate ?? sliceDoc?.latest_estimate} materialization={materialization ?? sliceDoc?.latest_materialization_plan} run={run.data} hasIndices={Boolean(tables?.indices?.rows)} hasCohort={Boolean(selectedCohortId)} />

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
            onSave={() => createSlice.mutate({ ...payload, title: humanSliceTitle(filters) })}
            onEstimate={() => estimateSlice.mutate()}
            estimate={estimate ?? sliceDoc?.latest_estimate}
            materialization={materialization ?? sliceDoc?.latest_materialization_plan}
            storageProfileId={activeStorageProfileId}
            setStorageProfileId={setStorageProfileId}
            storageProfileOptions={storageProfileOptions}
            sourceStrategy={activeSourceStrategy}
            setSourceStrategy={setSourceStrategy}
            sourceStrategyOptions={sourceStrategyOptions}
            apiKey={apiKey}
            setApiKey={setApiKey}
            rateLimit={rateLimit.data}
            onRun={() => downloadSlice.mutate()}
            saving={createSlice.isPending}
            estimating={estimateSlice.isPending}
            materializing={downloadSlice.isPending || runMaterialization.isPending || running}
            downloadConfigReady={downloadConfigReady}
            run={run.data}
            sliceDoc={sliceDoc}
          />
        )}

        {view === "data" && (
          <LocalDataPage
            workbench={workbench.data}
            dumps={dumps.data}
            tables={tables}
            tableName={tableName}
            setTableName={setTableName}
            tableOptions={tableOptions}
            tableQ={tableQ}
            setTableQ={setTableQ}
            table={table.data}
            run={run.data}
            running={running}
            onRefresh={() => qc.invalidateQueries()}
            onSelect={(next) => setSelected(next)}
          />
        )}

        {view === "enrichment" && (
          <EnrichmentPage
            qualityCounts={qualityCounts}
            tables={tables}
            run={run.data}
            onSelect={setSelected}
          />
        )}

        {view === "rankings" && (
          <RankingsPage
            metric={metric}
            setMetric={setMetric}
            metricOptions={primaryMetricOptions}
            fractionMode={fractionMode}
            setFractionMode={setFractionMode}
            fractionModeOptions={fractionModeOptions}
            topN={activeTopN}
            setTopN={setTopN}
            topNOptions={topNOptions}
            ranking={ranking.data}
            chartRows={chartRows}
            onSelect={(next) => setSelected(next)}
            onRecalculate={() => recalculate.mutate()}
            recalculating={recalculate.isPending || running}
          />
        )}

        {view === "cohorts" && (
          <CohortsPage
            cohorts={cohorts.data}
            selectedCohortId={selectedCohortId}
            setSelectedCohortId={setSelectedCohortId}
            cohortStats={cohortStats.data}
            metric={metric}
            setMetric={setMetric}
            metricOptions={primaryMetricOptions}
            fractionMode={fractionMode}
            setFractionMode={setFractionMode}
            fractionModeOptions={fractionModeOptions}
            topN={activeTopN}
            setTopN={setTopN}
            topNOptions={topNOptions}
            cohortSource={cohortSource}
            setCohortSource={setCohortSource}
            cohortName={cohortName}
            setCohortName={setCohortName}
            minPublications={minPublications}
            setMinPublications={setMinPublications}
            minH={minH}
            setMinH={setMinH}
            minMetricValue={minMetricValue}
            setMinMetricValue={setMinMetricValue}
            onCreate={() => createCohort.mutate()}
            creating={createCohort.isPending}
            loadingStats={cohortStats.isFetching}
          />
        )}

        {view === "statistics" && (
          <StatisticsPage
            analytics={analytics.data}
            table={ranking.data}
            metric={metric}
            chartRows={chartRows}
            topN={activeTopN}
            cohortStats={cohortStats.data}
            selectedCohortId={selectedCohortId}
            onOpenCohorts={() => navigate("cohorts")}
          />
        )}

        {view === "reports" && (
          <ReportsPage filters={filters} metric={metric} fractionMode={fractionMode} runId={runId} dumpId={activeDumpId} cohortId={selectedCohortId} topN={activeTopN} onBuild={() => buildReport.mutate()} building={buildReport.isPending} />
        )}

        {view === "passports" && (
          <PassportsPage state={state.data} sliceDoc={sliceDoc} estimate={estimate} materialization={materialization} />
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
  storageProfileId,
  setStorageProfileId,
  storageProfileOptions,
  sourceStrategy,
  setSourceStrategy,
  sourceStrategyOptions,
  apiKey,
  setApiKey,
  rateLimit,
  onRun,
  saving,
  estimating,
  materializing,
  downloadConfigReady,
  run,
  sliceDoc,
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
  storageProfileId: string;
  setStorageProfileId: (value: string) => void;
  storageProfileOptions: SelectOption[];
  sourceStrategy: string;
  setSourceStrategy: (value: string) => void;
  sourceStrategyOptions: SelectOption[];
  apiKey: string;
  setApiKey: (value: string) => void;
  rateLimit: any;
  onRun: () => void;
  saving: boolean;
  estimating: boolean;
  materializing: boolean;
  downloadConfigReady: boolean;
  run: any;
  sliceDoc: any;
}) {
  const dateInvalid = Boolean(filters.from_publication_date && filters.to_publication_date && filters.from_publication_date > filters.to_publication_date);
  const subjectMissing = false;
  const selectedWorkTypes = splitValues(filters.work_type);
  const visibleWorkTypeOptions = ensureWorkTypeOptions(workTypeOptions.length ? workTypeOptions : [], selectedWorkTypes);
  const decision = estimate?.decision ?? {};
  const rawEstimate = estimate?.estimate ?? {};
  const hasEstimate = Boolean(estimate);
  const canRun = hasEstimate && decision.can_execute !== false;

  return (
    <div className="stack">
      <div className="slice-layout">
        <section className="panel">
          <div className="panel-head">
            <span className="step-badge">1. SliceDefinition</span>
            <h2>Логическое описание среза</h2>
            <p>Пользователь задает предметный смысл. Оценка и скачивание настраиваются здесь же, без перехода на отдельный экран.</p>
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
            <button onClick={onSave} disabled={saving || dateInvalid || subjectMissing}>{saving ? <Loader2 size={16} className="spin" /> : <BookOpenCheck size={16} />} Сохранить срез</button>
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
          <KeyValue label="Публикации" value={filters.work_type || "Все поддерживаемые типы"} />
          <KeyValue label="Состояние" value={sliceDoc?.state ?? "draft"} />
        </aside>
      </div>

      <section className="panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">2. Оценка и скачивание</span>
            <h2>Настройка локального пакета</h2>
            <p>Система автоматически считает объем и стоимость среза. Решение скачивать или ужесточать фильтры принимает пользователь.</p>
          </div>
          <button onClick={onEstimate} disabled={estimating || dateInvalid || subjectMissing}>{estimating ? <Loader2 size={16} className="spin" /> : <Gauge size={16} />} Обновить оценку</button>
        </div>
        <div className="metric-grid">
          <MetricCard label="Работ найдено" value={fmt(rawEstimate.estimate_count ?? 0)} />
          <MetricCard label="Полный срез / к загрузке" value={`${fmt(rawEstimate.estimate_count ?? 0)} / ${fmt(decision.records_to_fetch ?? rawEstimate.planned_records ?? 0)}`} />
          <MetricCard label="API-запросов" value={fmt(decision.api_requests_planned ?? rawEstimate.api_requests_planned ?? 0)} />
          <MetricCard label="CLI metadata прогноз" value={`${fmt(rawEstimate.estimated_cli_metadata_mb ?? decision.estimated_raw_mb ?? rawEstimate.estimated_raw_mb ?? 0)} МБ`} />
          <MetricCard label="API preview прогноз" value={`${fmt(rawEstimate.estimated_selected_api_mb ?? rawEstimate.estimated_raw_mb ?? 0)}–${fmt(rawEstimate.estimated_raw_mb_p90 ?? decision.estimated_raw_mb ?? 0)} МБ`} />
          <MetricCard label="Parquet прогноз" value={`${fmt(rawEstimate.estimated_parquet_mb ?? 0)} МБ`} />
        </div>
        <EstimateBudget estimate={rawEstimate} decision={decision} />
        <EstimateFacets facets={rawEstimate.facets} />
        <div className={canRun ? "notice success" : hasEstimate ? "notice error" : "notice"}>
          <b>{canRun ? "Можно скачивать или уточнить фильтры" : hasEstimate ? "Скачивание недоступно для текущего плана" : "Сначала оцените объем"}</b>
          <span>{decision.strategy ?? "Оценка еще не выполнена"} · {decision.status ?? "нет статуса"}</span>
        </div>
        {[...(decision.reasons ?? []), ...(decision.warnings ?? [])].length > 0 && (
          <ul className="plain-list">
            {[...(decision.reasons ?? []), ...(decision.warnings ?? [])].map((item: string) => <li key={item}>{item}</li>)}
          </ul>
        )}
        <details className="technical-details">
          <summary>Настроить скачивание</summary>
          <div className="form-grid tight">
            <Field label="Состав сохраняемых данных">
              <SingleChoicePicker
                options={storageProfileOptions}
                selected={storageProfileId}
                onChange={setStorageProfileId}
              />
            </Field>
            <Field label="Способ загрузки">
              <SingleChoicePicker
                options={sourceStrategyOptions}
                selected={sourceStrategy}
                onChange={setSourceStrategy}
              />
            </Field>
            <Field label="OpenAlex API key">
              <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Нужен для OpenAlex CLI и повышенных лимитов API" />
            </Field>
          </div>
        </details>
        <RateLimitPanel rateLimit={rateLimit} apiKeySet={Boolean(apiKey.trim())} estimate={rawEstimate} />
        {materialization && (
          <div className="materialization-card">
            <b>{materialization.profile?.label}</b>
            <span>{materialization.materialization_id}</span>
            <small>{materialization.profile?.description}</small>
          </div>
        )}
        <div className="action-row">
          <button className="primary" onClick={onRun} disabled={materializing || dateInvalid || subjectMissing || !hasEstimate || !downloadConfigReady || decision.can_execute === false}>{materializing ? <Loader2 size={16} className="spin" /> : <UploadCloud size={16} />} Скачать срез через OpenAlex CLI</button>
        </div>
      </section>

      <ProgressPanel filters={filters} estimate={estimate} materialization={materialization} run={run} />
    </div>
  );
}

function LocalDataPage({
  workbench,
  dumps,
  tables,
  tableName,
  setTableName,
  tableOptions,
  tableQ,
  setTableQ,
  table,
  run,
  running,
  onRefresh,
  onSelect,
}: {
  workbench: any;
  dumps: any;
  tables: any;
  tableName: string;
  setTableName: (value: string) => void;
  tableOptions: SelectOption[];
  tableQ: string;
  setTableQ: (value: string) => void;
  table?: TableResponse;
  run: any;
  running: boolean;
  onRefresh: () => void;
  onSelect: (value: { kind: "author" | "work"; id: string }) => void;
}) {
  const dumpRows = dumps?.dumps ?? workbench?.dumps ?? [];
  const totalRawMb = dumpRows.reduce((sum: number, dump: any) => sum + bytesToMb(Number(dump.bytes_written ?? dump.raw_size_bytes ?? 0)), 0);
  return (
    <div className="stack">
      <section className="metric-grid">
        <MetricCard label="Локальных дампов" value={fmt(dumpRows.length)} />
        <MetricCard label="Raw на диске" value={`${fmt(totalRawMb)} МБ`} />
        <MetricCard label="Parquet таблиц" value={fmt(["works", "authorships", "work_topics", "author_work"].filter((name) => tables?.[name]?.exists).length)} />
        <MetricCard label="Индексов авторов" value={fmt(tables?.indices?.rows ?? 0)} />
      </section>
      <section className="panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">DumpManifest</span>
            <h2>Локальные пакеты данных</h2>
            <p>Здесь видны только сохраненные локальные артефакты. Они не являются срезом, а только его физической загрузкой.</p>
          </div>
          <button onClick={onRefresh}><Loader2 size={16} className={running ? "spin" : ""} /> Обновить</button>
        </div>
        {run && <RunCard run={run} />}
        <div className="dump-list">
          {dumpRows.length === 0 && <EmptyState title="Мини-дампов пока нет" detail="Сначала оцените срез и скачайте локальный пакет данных." />}
          {dumpRows.map((dump: any) => (
            <div className="dump-card" key={`${dump.dump_id ?? dump.slice_id}-${dump.raw_jsonl}`}>
              <div className="dump-card-head">
                <b>{dump.slice_id}</b>
                <span className={dump.allowed_for_final_analysis === false ? "status-chip warn" : "status-chip ok"}>{dump.scientific_completeness ?? "complete"}</span>
              </div>
              <span>{dump.dump_id ?? "dump_id не указан"}</span>
              <span>{dump.raw_jsonl}</span>
              <small>{fmt(dump.records_downloaded ?? 0)} работ · {fmt(bytesToMb(dump.bytes_written ?? 0))} МБ · {dump.stop_reason}</small>
            </div>
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <span className="step-badge">Local Data Lake</span>
          <h2>Готовность локальных таблиц</h2>
          <p>Это физические таблицы выбранного run/dump. Фильтры аналитической выборки применяются во вкладке “Индексы”.</p>
        </div>
        <div className="metric-grid">
          <MetricCard label="Works" value={fmt(tables?.works?.rows ?? 0)} />
          <MetricCard label="Authorships" value={fmt(tables?.authorships?.rows ?? 0)} />
          <MetricCard label="Author-work mart" value={fmt(tables?.author_work?.rows ?? 0)} />
          <MetricCard label="Author indices" value={fmt(tables?.indices?.rows ?? 0)} />
        </div>
      </section>
      <section className="panel table-panel">
        <div className="panel-head">
          <span className="step-badge">Physical table</span>
          <h2>Просмотр локальной таблицы</h2>
        </div>
        <div className="toolbar">
          <select value={tableName} onChange={(event) => setTableName(event.target.value)}>
            {ensureCurrentOption(tableOptions, tableName).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          <input value={tableQ} onChange={(event) => setTableQ(event.target.value)} placeholder="Поиск по физической таблице" />
        </div>
        <DataGrid data={table} onSelect={onSelect} hiddenFields={["slice_id"]} />
      </section>
    </div>
  );
}

type PointLookupTab = "author" | "institution" | "work" | "source";

function EnrichmentPage({
  qualityCounts,
  tables,
  run,
  onSelect,
}: {
  qualityCounts: any;
  tables: any;
  run: any;
  onSelect: (value: { kind: "author" | "work"; id: string }) => void;
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
    queryKey: ["point-enrichment", tab, query.trim()],
    queryFn: () => getJson<any>(`${endpoint}?q=${encodeURIComponent(query.trim())}&limit=10`),
    enabled: query.trim().length >= 2,
  });
  const results = (lookup.data?.results ?? []) as EntitySuggestion[];
  const selectPoint = (item: EntitySuggestion) => {
    const id = String(item.openalex_id || item.id || "").trim();
    setPicked(item);
    if (!id) return;
    if (tab === "author") onSelect({ kind: "author", id });
    if (tab === "work") onSelect({ kind: "work", id });
  };

  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head">
          <div>
            <span className="step-badge">Point enrichment</span>
            <h2>Точечная дозагрузка профилей</h2>
            <p>Один поиск используется для ORCID, ROR, DOI и OpenAlex ID. Глобальные профили не подменяют локальные индексы среза.</p>
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
          {query.trim().length < 2 && <EmptyState title="Введите запрос" detail="Точечное обогащение запускается только по явному запросу пользователя." />}
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
          <b>Не смешивать с локальными метриками</b>
          <span>Профили OpenAlex нужны для проверки и карточек. Итоговые P, C_frac, h, i10 и g считаются только по сохраненному works-срезу.</span>
        </div>
        {picked && (
          <div className="materialization-card">
            <b>{picked.name}</b>
            <span>{picked.level_label ?? picked.level ?? "OpenAlex entity"}</span>
            <small>{picked.openalex_id ?? picked.id} {picked.ror ? `· ROR: ${picked.ror}` : ""} {picked.orcid ? `· ORCID: ${picked.orcid}` : ""} {(picked as any).doi ? `· DOI: ${(picked as any).doi}` : ""}</small>
          </div>
        )}
        {run && <RunCard run={run} />}
        <div className="metric-grid">
          <MetricCard label="Null author" value={fmt(qualityCounts?.authorships_null_author_id ?? 0)} />
          <MetricCard label="Нет авторств" value={fmt(qualityCounts?.works_without_authorships ?? 0)} />
          <MetricCard label="Локальные авторы" value={fmt(tables?.indices?.rows ?? 0)} />
          <MetricCard label="Флаги качества" value={fmt(Object.values(qualityCounts ?? {}).reduce((a: number, b: any) => a + Number(b || 0), 0))} />
        </div>
      </section>
    </div>
  );
}

function RankingsPage({
  metric,
  setMetric,
  metricOptions,
  fractionMode,
  setFractionMode,
  fractionModeOptions,
  topN,
  setTopN,
  topNOptions,
  ranking,
  chartRows,
  onSelect,
  onRecalculate,
  recalculating,
}: {
  metric: string;
  setMetric: (value: string) => void;
  metricOptions: SelectOption[];
  fractionMode: string;
  setFractionMode: (value: string) => void;
  fractionModeOptions: SelectOption[];
  topN: number;
  setTopN: (value: number) => void;
  topNOptions: SelectOption[];
  ranking?: TableResponse;
  chartRows: any[];
  onSelect: (value: { kind: "author" | "work"; id: string }) => void;
  onRecalculate: () => void;
  recalculating: boolean;
}) {
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">AnalysisRun</span>
            <h2>Индексы, рейтинги и когорта авторов</h2>
            <p>Top-N здесь является параметром результата и статистической когорты, а не ограничением первичной загрузки работ.</p>
          </div>
          <button className="primary" onClick={onRecalculate} disabled={recalculating}>{recalculating ? <Loader2 size={16} className="spin" /> : <Sigma size={16} />} Рассчитать</button>
        </div>
        <div className="toolbar">
          <select value={metric} onChange={(event) => setMetric(event.target.value)}>
            {ensureCurrentOption(metricOptions, metric).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          <select value={fractionMode} onChange={(event) => setFractionMode(event.target.value)}>
            {ensureCurrentOption(fractionModeOptions, fractionMode).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          <select value={String(topN)} onChange={(event) => setTopN(Number(event.target.value))}>
            {topNOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </div>
        <div className="notice">
          <b>Текущая аналитическая выборка</b>
          <span>Этот рейтинг пересчитывается поверх выбранного dump/run с учетом активных фильтров. Физические таблицы без аналитической фильтрации находятся во вкладке “Данные”.</span>
        </div>
      </section>
      <section className="chart-table-grid">
        <div className="panel">
          <h2>Когорта Top-{topN} по {metricLabel(metric)}</h2>
          <div className="chart-box">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartRows}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" />
                <YAxis />
                <Tooltip />
                <Bar dataKey="score" fill="#155e75" name={metricLabel(metric)} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="panel table-panel">
          <DataGrid data={ranking} onSelect={onSelect} hiddenFields={["slice_id", "run_id", "fraction_mode"]} />
        </div>
      </section>
    </div>
  );
}

function CohortsPage({
  cohorts,
  selectedCohortId,
  setSelectedCohortId,
  cohortStats,
  metric,
  setMetric,
  metricOptions,
  fractionMode,
  setFractionMode,
  fractionModeOptions,
  topN,
  setTopN,
  topNOptions,
  cohortSource,
  setCohortSource,
  cohortName,
  setCohortName,
  minPublications,
  setMinPublications,
  minH,
  setMinH,
  minMetricValue,
  setMinMetricValue,
  onCreate,
  creating,
  loadingStats,
}: {
  cohorts: any;
  selectedCohortId: string;
  setSelectedCohortId: (value: string) => void;
  cohortStats: any;
  metric: string;
  setMetric: (value: string) => void;
  metricOptions: SelectOption[];
  fractionMode: string;
  setFractionMode: (value: string) => void;
  fractionModeOptions: SelectOption[];
  topN: number;
  setTopN: (value: number) => void;
  topNOptions: SelectOption[];
  cohortSource: "top_n" | "metric_filter";
  setCohortSource: (value: "top_n" | "metric_filter") => void;
  cohortName: string;
  setCohortName: (value: string) => void;
  minPublications: number;
  setMinPublications: (value: number) => void;
  minH: number;
  setMinH: (value: number) => void;
  minMetricValue: number;
  setMinMetricValue: (value: number) => void;
  onCreate: () => void;
  creating: boolean;
  loadingStats: boolean;
}) {
  const rows = cohorts?.cohorts ?? [];
  const selected = rows.find((row: any) => row.cohort_id === selectedCohortId);
  const describe = cohortStats?.descriptive?.[metric] ?? {};
  const box = cohortStats?.boxplots?.[metric] ?? {};
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">AuthorCohort</span>
            <h2>Фиксация аналитической выборки</h2>
            <p>Когорта сохраняет список author_id, метрику сортировки, Top-N и пороги. Именно по ней считаются графики и статистика.</p>
          </div>
          <button className="primary" onClick={onCreate} disabled={creating}>{creating ? <Loader2 size={16} className="spin" /> : <GitCompareArrows size={16} />} Создать когорту</button>
        </div>
        <div className="form-grid tight">
          <Field label="Название когорты">
            <input value={cohortName} onChange={(event) => setCohortName(event.target.value)} />
          </Field>
          <Field label="Источник когорты">
            <select value={cohortSource} onChange={(event) => setCohortSource(event.target.value as "top_n" | "metric_filter")}>
              <option value="top_n">Top-N по индексу</option>
              <option value="metric_filter">Все авторы по порогам</option>
            </select>
          </Field>
          <Field label="Метрика сортировки">
            <select value={metric} onChange={(event) => setMetric(event.target.value)}>
              {ensureCurrentOption(metricOptions, metric).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </Field>
          <Field label="Режим фракционирования">
            <select value={fractionMode} onChange={(event) => setFractionMode(event.target.value)}>
              {ensureCurrentOption(fractionModeOptions, fractionMode).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </Field>
          {cohortSource === "top_n" && (
            <Field label="Размер Top-N">
              <select value={String(topN)} onChange={(event) => setTopN(Number(event.target.value))}>
                {topNOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </Field>
          )}
          <Field label="Минимум публикаций">
            <input type="number" min={0} value={minPublications} onChange={(event) => setMinPublications(Number(event.target.value || 0))} />
          </Field>
          <Field label="Минимум h-index">
            <input type="number" min={0} value={minH} onChange={(event) => setMinH(Number(event.target.value || 0))} />
          </Field>
          {cohortSource === "metric_filter" && (
            <Field label={`Минимум ${metricLabel(metric)}`}>
              <input type="number" min={0} value={minMetricValue} onChange={(event) => setMinMetricValue(Number(event.target.value || 0))} />
            </Field>
          )}
        </div>
        <div className="notice">
          <b>{cohortSource === "top_n" ? "Top-N когорта" : "Когорта по порогам"}</b>
          <span>{cohortSource === "top_n" ? "Сначала выбираются первые N авторов по метрике, затем применяются минимальные пороги." : "Top-N не применяется: в когорту войдут все авторы текущей аналитической выборки, прошедшие пороги."}</span>
        </div>
      </section>

      <section className="chart-table-grid">
        <div className="panel">
          <div className="panel-head">
            <span className="step-badge">Сохраненные когорты</span>
            <h2>Выберите выборку для статистики</h2>
          </div>
          <div className="cohort-list">
            {rows.length === 0 && <EmptyState title="Когорты еще не созданы" detail="Сначала рассчитайте индексы и создайте Top-N когорту." />}
            {rows.map((row: any) => (
              <button key={row.cohort_id} className={row.cohort_id === selectedCohortId ? "cohort-card active" : "cohort-card"} onClick={() => setSelectedCohortId(row.cohort_id)}>
                <b>{row.name}</b>
                <span>{fmt(row.n_authors ?? 0)} авторов · {metricLabel(row.metric)} · {row.fraction_mode}</span>
                <small>{row.cohort_id}</small>
              </button>
            ))}
          </div>
        </div>
        <div className="panel">
          <div className="panel-head">
            <span className="step-badge">{loadingStats ? "Расчет" : "Статистика"}</span>
            <h2>{selected?.name ?? "Когорта не выбрана"}</h2>
          </div>
          {!selected && <EmptyState title="Нет активной когорты" detail="Создайте или выберите когорту, чтобы перейти к статистике." />}
          {selected && (
            <div className="metric-grid">
              <MetricCard label="Авторов" value={fmt(selected.n_authors ?? 0)} />
              <MetricCard label="Среднее" value={fmt(describe.mean ?? 0)} />
              <MetricCard label="Медиана" value={fmt(describe.median ?? 0)} />
              <MetricCard label="IQR" value={fmt(describe.iqr ?? 0)} />
              <MetricCard label="Q1" value={fmt(box.q1 ?? 0)} />
              <MetricCard label="Q3" value={fmt(box.q3 ?? 0)} />
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function StatisticsPage({
  analytics,
  table,
  metric,
  chartRows,
  topN,
  cohortStats,
  selectedCohortId,
  onOpenCohorts,
}: {
  analytics: any;
  table?: TableResponse;
  metric: string;
  chartRows: any[];
  topN: number;
  cohortStats: any;
  selectedCohortId: string;
  onOpenCohorts: () => void;
}) {
  const scatter = (table?.rows ?? []).slice(0, 120).map((row: any) => ({
    x: Number(row.h ?? row.h_raw ?? 0),
    y: Number(row.c_frac ?? row.c_frac_raw ?? row.score ?? 0),
    name: row.author_display_name,
  }));
  const describe = cohortStats?.descriptive?.[metric] ?? {};
  const box = cohortStats?.boxplots?.[metric] ?? {};
  const histogramRows = (cohortStats?.histograms?.[metric]?.raw ?? []).map((row: any, index: number) => ({
    label: `${fmt(row.bin_start)}-${fmt(row.bin_end)}`,
    score: Number(row.count ?? 0),
    author: `bin-${index + 1}`,
  }));
  const activeN = cohortStats?.cohort?.n_authors ?? (table?.total ? Math.min(Number(table.total), topN) : 0);
  const distributionRows = histogramRows.length ? histogramRows : chartRows;
  return (
    <div className="stack">
      {!selectedCohortId && (
        <section className="notice">
          <b>Сначала зафиксируйте когорту авторов</b>
          <span>Статистика должна иметь паспорт выборки: metric, Top-N, фильтры и checksum author_id.</span>
          <div className="action-row"><button onClick={onOpenCohorts}><GitCompareArrows size={16} /> Перейти к когортам</button></div>
        </section>
      )}
      <section className="metric-grid">
        <MetricCard label={cohortStats?.cohort?.name ?? `Когорта Top-${topN}`} value={fmt(activeN)} />
        <MetricCard label="Авторов в распределении" value={fmt(describe.n ?? analytics?.distribution?.n ?? 0)} />
        <MetricCard label="Среднее" value={fmt(describe.mean ?? analytics?.distribution?.mean ?? 0)} />
        <MetricCard label="Медиана" value={fmt(describe.median ?? analytics?.distribution?.median ?? 0)} />
        <MetricCard label="Zero-rate" value={fmt(describe.zero_rate ?? 0)} />
        <MetricCard label="Tie-rate" value={fmt(describe.tie_rate ?? 0)} />
        <MetricCard label="Skewness" value={fmt(describe.skewness ?? 0)} />
      </section>
      <section className="chart-table-grid">
        <div className="panel">
          <h2>Распределение индекса</h2>
          <div className="chart-box">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={distributionRows}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" />
                <YAxis />
                <Tooltip />
                <Bar dataKey="score" fill="#167343" name={histogramRows.length ? "Авторов в bin" : metricLabel(metric)} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          {box.n > 0 && (
            <div className="box-summary">
              <KeyValue label="Boxplot" value={`min ${fmt(box.min)} · Q1 ${fmt(box.q1)} · median ${fmt(box.median)} · Q3 ${fmt(box.q3)} · max ${fmt(box.max)}`} />
            </div>
          )}
        </div>
        <div className="panel">
          <h2>Scatter h vs C_frac</h2>
          <div className="chart-box">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart>
                <CartesianGrid />
                <XAxis dataKey="x" name="h" />
                <YAxis dataKey="y" name="C_frac" />
                <Tooltip cursor={{ strokeDasharray: "3 3" }} />
                <Scatter data={scatter} fill="#155e75" />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>
      <section className="panel">
        <h2>Методы доказательной аналитики</h2>
        <p>Графики и таблицы интерпретируются для текущей авторской когорты. Состав когорты должен фиксироваться в отчете вместе с метрикой сортировки и Top-N.</p>
        <div className="method-grid">
          {["Spearman/Kendall корреляции", "Top-N overlap", "Rank-shift", "Remove-top-1 sensitivity", "Tie-rate и zero-rate", "Bootstrap stability"].map((item) => <CheckPill key={item} active label={item} />)}
        </div>
      </section>
    </div>
  );
}

function ReportsPage({
  filters,
  metric,
  fractionMode,
  runId,
  dumpId,
  cohortId,
  topN,
  onBuild,
  building,
}: {
  filters: ActiveFilters;
  metric: string;
  fractionMode: string;
  runId: string;
  dumpId: string;
  cohortId: string;
  topN: number;
  onBuild: () => void;
  building: boolean;
}) {
  const reportParams = filterParams(filters, { fraction_mode: fractionMode, metric, limit: topN, run_id: runId, dump_id: dumpId, cohort_id: cohortId });
  const rankingUrl = `${API_BASE}/analytics/ranking.csv?${reportParams.toString()}`;
  const bundleUrl = `${API_BASE}/reports/bundle.json?${reportParams.toString()}`;
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">Report</span>
            <h2>Отчеты и пакет воспроизводимости</h2>
            <p>Отчет фиксирует срез исследования, локальную загрузку, когорту Top-{topN}, расчет индексов, графики, ограничения и паспорта.</p>
          </div>
          <button onClick={onBuild} disabled={building}>{building ? <Loader2 size={16} className="spin" /> : <Download size={16} />} Собрать HTML</button>
        </div>
        <div className="download-grid">
          <a href={rankingUrl}>CSV рейтинга</a>
          <a href={bundleUrl}>JSON-пакет отчета</a>
          <a href={`${API_BASE}/state`}>JSON состояния</a>
          <a href={`${API_BASE}/catalog`}>Каталог конфигураций</a>
        </div>
      </section>
    </div>
  );
}

function PassportsPage({ state, sliceDoc, estimate, materialization }: { state: any; sliceDoc: any; estimate: any; materialization: any }) {
  return (
    <div className="passport-grid">
      <JsonPanel title="Паспорт среза" value={sliceDoc ?? state?.workflow?.current_slice ?? {}} />
      <JsonPanel title="Паспорт оценки" value={estimate ?? sliceDoc?.latest_estimate ?? {}} />
      <JsonPanel title="Паспорт загрузки и хранения" value={materialization ?? sliceDoc?.latest_materialization_plan ?? {}} />
      <JsonPanel title="Quality report" value={state?.quality ?? {}} />
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
            <span className="step-badge">OpenAlex Resolver</span>
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

function WorkflowStepper({
  view,
  estimate,
  materialization,
  run,
  hasIndices,
  hasCohort,
}: {
  view: View;
  estimate: any;
  materialization: any;
  run: any;
  hasIndices: boolean;
  hasCohort: boolean;
}) {
  const steps: Array<{ id: View; label: string; ready: boolean }> = [
    { id: "slices", label: "Срез и загрузка", ready: true },
    { id: "data", label: "Локальные данные", ready: run?.status === "completed" || Boolean(materialization) },
    { id: "rankings", label: "Индексы", ready: hasIndices },
    { id: "cohorts", label: "Когорты", ready: hasCohort },
    { id: "statistics", label: "Статистика", ready: Boolean(hasCohort) },
    { id: "reports", label: "Отчет", ready: false },
  ];
  return (
    <div className="workflow-stepper" aria-label="Логика работы системы">
      {steps.map((step, index) => (
        <span key={step.id} className={[view === step.id ? "active" : "", step.ready ? "ready" : ""].filter(Boolean).join(" ")}>
          <b>{index + 1}</b>
          {step.label}
        </span>
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
      <MetricCard label="API key" value={apiKeySet ? "задан" : "не задан"} />
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
        <span>Прогноз: API preview {fmt(bytesToMb(avg))} МБ, CLI metadata {fmt(bytesToMb(p90))} МБ</span>
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
        <span className="step-badge">Lifecycle</span>
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
      <span><Database size={15} /> Works: {fmt(tables?.works?.rows ?? 0)}</span>
      <span><Sigma size={15} /> Authors: {fmt(tables?.indices?.rows ?? 0)}</span>
      <span><Gauge size={15} /> {running ? `${progress.label} · ${progress.percent}%` : run?.status ?? state?.workflow?.active_stage ?? "idle"}</span>
    </div>
  );
}

function RunCard({ run }: { run: WorkbenchRun }) {
  if (!run) return null;
  const progress = progressForRun(run);
  const details = (run as any).progress ?? {};
  return (
    <div className={`run-card ${run.status === "failed" ? "error" : ""}`}>
      <b>{run.action} · {run.status}</b>
      <span>{run.run_id}</span>
      <ProgressBar percent={progress.percent} label={progress.label} tone={run.status === "failed" ? "error" : "normal"} />
      {Object.keys(details).length > 0 && (
        <div className="run-progress-details">
          <span>{fmt(details.fetched ?? 0)} / {fmt(details.target_records ?? details.total_available ?? 0)} работ</span>
          <span>{fmt(details.page_count ?? 0)} страниц</span>
          <span>{fmt(bytesToMb(details.bytes_written ?? 0))} МБ</span>
        </div>
      )}
      {run.error && <small>{run.error}</small>}
    </div>
  );
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
      {!error && <small className="field-hint">Подсказки: локальные пресеты + OpenAlex Topics/Fields/Subfields.</small>}
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
      {!error && <small className="field-hint">Пустое поле означает: без ограничения по организации.</small>}
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
      id: String(item.openalex_id ?? item.id ?? "").trim(),
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
