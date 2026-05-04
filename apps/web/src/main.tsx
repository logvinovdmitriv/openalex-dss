import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  BookOpenCheck,
  Boxes,
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
  Table2,
  UploadCloud,
  X,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { API_BASE, getJson, postJson, type TableResponse } from "./api";
import {
  DEFAULT_FILTERS,
  DUMP_SIZE_OPTIONS,
  FRACTION_MODES,
  LOAD_LIMIT_OPTIONS,
  PRIMARY_METRIC_OPTIONS,
  countryLabel,
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
  MATERIALIZATION_PROFILES,
  TOP_N_OPTIONS,
  analyticsUrl,
  buildPayload,
  bytesToMb,
  humanSliceTitle,
  mutationError,
  pageLead,
  pageTitle,
  progressForRun,
  rankingChartRows,
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
  { id: "slices", label: "Срезы", icon: <Layers3 size={17} /> },
  { id: "estimate", label: "Оценка и загрузка", icon: <Gauge size={17} /> },
  { id: "data", label: "Локальные данные", icon: <Database size={17} /> },
  { id: "enrichment", label: "Обогащение", icon: <Sparkles size={17} /> },
  { id: "rankings", label: "Индексы", icon: <Sigma size={17} /> },
  { id: "statistics", label: "Статистика", icon: <BarChart3 size={17} /> },
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
  const [metric, setMetric] = useState("islv");
  const [fractionMode, setFractionMode] = useState("strict_authors_count");
  const [maxWorks, setMaxWorks] = useState(1000);
  const [maxDumpBytes, setMaxDumpBytes] = useState(524288000);
  const [topN, setTopN] = useState(100);
  const [profileId, setProfileId] = useState("minimal_analytics");
  const [apiKey, setApiKey] = useState("");
  const [sliceDoc, setSliceDoc] = useState<any>(null);
  const [estimate, setEstimate] = useState<any>(null);
  const [materialization, setMaterialization] = useState<any>(null);
  const [runId, setRunId] = useState("");
  const [resolverOpen, setResolverOpen] = useState(false);
  const [selected, setSelected] = useState<{ kind: "author" | "work"; id: string } | null>(null);
  const [tableName, setTableName] = useState("authors_local_metrics");
  const [tableQ, setTableQ] = useState("");
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
  const countries = useQuery({ queryKey: ["countries"], queryFn: () => getJson<any>("/openalex/countries?limit=50") });
  const workTypes = useQuery({ queryKey: ["work-types"], queryFn: () => getJson<any>("/openalex/work-types?limit=50") });
  const table = useQuery({
    queryKey: ["table", tableName, tableQ, metric, fractionMode, topN],
    queryFn: () => getJson<TableResponse>(`/tables/${tableName}?q=${encodeURIComponent(tableQ)}&fraction_mode=${encodeURIComponent(fractionMode)}&metric=${encodeURIComponent(metric)}&limit=${topN}`),
  });
  const analytics = useQuery({
    queryKey: ["analytics", metric, fractionMode],
    queryFn: () => getJson<any>(analyticsUrl(filters, fractionMode, metric)),
    enabled: Boolean(filters.subject_id || filters.keyword_id || filters.text_search_query),
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
  const detail = useQuery({
    queryKey: ["detail", selected],
    queryFn: () => getJson<any>(selected?.kind === "author" ? `/authors/${encodeURIComponent(selected.id)}` : `/works/${encodeURIComponent(selected?.id ?? "")}`),
    enabled: Boolean(selected),
  });

  const payload = useMemo(() => buildPayload(filters, fractionMode, maxWorks, maxDumpBytes, apiKey), [filters, fractionMode, maxWorks, maxDumpBytes, apiKey]);
  const domainPresets = (registry.data?.domain_presets ?? []) as ResearchAreaPreset[];
  const organizationPresets = (registry.data?.organization_presets ?? []) as OrganizationPreset[];
  const countryOptions = catalogOptions(countries.data?.results ?? []);
  const workTypeOptions = catalogOptions(workTypes.data?.results ?? []);

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
      const result = await postJson<any>(`/slices/${encodeURIComponent(doc.slice_id)}/estimate`, { max_dump_bytes: maxDumpBytes });
      return { doc, result };
    },
    onSuccess: ({ doc, result }) => {
      setSliceDoc({ ...doc, latest_estimate: result, state: "estimated" });
      setEstimate(result);
      qc.invalidateQueries({ queryKey: ["workbench"] });
      navigate("estimate");
    },
  });
  const createMaterialization = useMutation({
    mutationFn: async () => {
      const doc = sliceDoc ?? (await postJson<any>("/slices", { ...payload, title: humanSliceTitle(filters) }));
      setSliceDoc(doc);
      return postJson<any>(`/slices/${encodeURIComponent(doc.slice_id)}/materialization-plans`, { profile_id: profileId, max_dump_bytes: maxDumpBytes });
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
  const buildAuthorPreview = useMutation({
    mutationFn: () => postJson<any>("/runs", { action: "author_preview", payload: { ...payload, workflow_mode: "author_preview" } }),
    onSuccess: (result) => {
      setRunId(result.run_id);
      navigate("enrichment");
    },
  });
  const recalculate = useMutation({
    mutationFn: () => postJson<any>("/runs", { action: "recalculate", payload }),
    onSuccess: (result) => {
      setRunId(result.run_id);
      navigate("rankings");
    },
  });
  const buildReport = useMutation({
    mutationFn: () => postJson<any>(`/reports/build?metric=${encodeURIComponent(metric)}&fraction_mode=${encodeURIComponent(fractionMode)}&limit=100`, {}),
    onSuccess: () => qc.invalidateQueries(),
  });

  const running = run.data?.status === "queued" || run.data?.status === "running";
  const tables = state.data?.tables ?? {};
  const qualityCounts = state.data?.quality?.quality_counts ?? {};
  const tableRows = table.data?.rows ?? [];
  const chartRows = useMemo(() => rankingChartRows(tableRows, metric), [tableRows, metric]);
  const errors = [
    mutationError(createSlice.error),
    mutationError(estimateSlice.error),
    mutationError(createMaterialization.error),
    mutationError(runMaterialization.error),
    mutationError(recalculate.error),
    mutationError(buildAuthorPreview.error),
  ].filter(Boolean);

  return (
    <main className="app-shell">
      <aside className="side-nav" aria-label="Основные разделы">
        <div className="brand">
          <span>OA</span>
          <b>СППР-срезы OpenAlex</b>
        </div>
        <div role="tablist" aria-orientation="vertical" className="nav-list" onKeyDown={onNavKeyDown}>
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
      </aside>

      <section className="workbench" id={`panel-${view}`} role="tabpanel" aria-labelledby={`tab-${view}`}>
        <header className="page-header">
          <div>
            <span className="eyebrow">Slice-Centric Analytical Workbench</span>
            <h1>{pageTitle(view)}</h1>
            <p>{pageLead(view)}</p>
          </div>
          <StatusRail state={state.data} run={run.data} running={running} />
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
            onSave={() => createSlice.mutate({ ...payload, title: humanSliceTitle(filters) })}
            onEstimate={() => estimateSlice.mutate()}
            saving={createSlice.isPending}
            estimating={estimateSlice.isPending}
            sliceDoc={sliceDoc}
          />
        )}

        {view === "estimate" && (
          <EstimatePage
            filters={filters}
            estimate={estimate ?? sliceDoc?.latest_estimate}
            materialization={materialization ?? sliceDoc?.latest_materialization_plan}
            profileId={profileId}
            setProfileId={setProfileId}
            maxWorks={maxWorks}
            setMaxWorks={setMaxWorks}
            maxDumpBytes={maxDumpBytes}
            setMaxDumpBytes={setMaxDumpBytes}
            onEstimate={() => estimateSlice.mutate()}
            onPlan={() => createMaterialization.mutate()}
            onRun={() => runMaterialization.mutate()}
            estimating={estimateSlice.isPending}
            planning={createMaterialization.isPending}
            materializing={runMaterialization.isPending || running}
            run={run.data}
          />
        )}

        {view === "data" && (
          <LocalDataPage
            workbench={workbench.data}
            dumps={dumps.data}
            tables={tables}
            run={run.data}
            running={running}
            onRefresh={() => qc.invalidateQueries()}
          />
        )}

        {view === "enrichment" && (
          <EnrichmentPage
            qualityCounts={qualityCounts}
            tables={tables}
            onPreview={() => buildAuthorPreview.mutate()}
            previewing={buildAuthorPreview.isPending || running}
            run={run.data}
          />
        )}

        {view === "rankings" && (
          <RankingsPage
            metric={metric}
            setMetric={setMetric}
            fractionMode={fractionMode}
            setFractionMode={setFractionMode}
            tableName={tableName}
            setTableName={setTableName}
            tableQ={tableQ}
            setTableQ={setTableQ}
            topN={topN}
            setTopN={setTopN}
            table={table.data}
            chartRows={chartRows}
            onSelect={(next) => setSelected(next)}
            onRecalculate={() => recalculate.mutate()}
            recalculating={recalculate.isPending || running}
          />
        )}

        {view === "statistics" && (
          <StatisticsPage analytics={analytics.data} table={table.data} metric={metric} chartRows={chartRows} topN={topN} />
        )}

        {view === "reports" && (
          <ReportsPage metric={metric} fractionMode={fractionMode} topN={topN} onBuild={() => buildReport.mutate()} building={buildReport.isPending} />
        )}

        {view === "passports" && (
          <PassportsPage state={state.data} sliceDoc={sliceDoc} estimate={estimate} materialization={materialization} />
        )}
      </section>

      {resolverOpen && (
        <ResolverDialog
          filters={filters}
          setFilters={setFilters}
          onClose={() => setResolverOpen(false)}
        />
      )}

      {selected && <DetailDrawer selected={selected} onClose={() => setSelected(null)} detail={detail.data} />}
    </main>
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
  saving,
  estimating,
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
  saving: boolean;
  estimating: boolean;
  sliceDoc: any;
}) {
  const dateInvalid = Boolean(filters.from_publication_date && filters.to_publication_date && filters.from_publication_date > filters.to_publication_date);
  const subjectMissing = !filters.subject_id && !filters.keyword_id && !filters.text_search_query;
  const selectedDomain = domainPresets.find((item) => (
    item.subject_level === filters.subject_level
    && item.subject_id === filters.subject_id
    && item.filter_mode === filters.filter_mode
  ))?.value ?? "";
  const selectedOrg = organizationPresets.find((item) => item.institution_id === filters.institution_id)?.value ?? (filters.institution_id ? "custom" : "all");
  const visibleOrgPresets = organizationPresets.length ? organizationPresets : [{
    value: "all",
    label: "Любая организация",
    description: "Без ограничения по организации.",
    institution_id: "",
    institution_name: "",
  }];
  const visibleWorkTypeOptions = ensureOption(
    workTypeOptions.length ? workTypeOptions : [],
    filters.work_type,
    filters.work_type || "Тип не выбран",
  );

  return (
    <div className="slice-layout">
      <section className="panel">
        <div className="panel-head">
          <span className="step-badge">1. SliceDefinition</span>
          <h2>Логическое описание среза</h2>
          <p>Пользователь задает предметный смысл. OpenAlex-фильтр, дамп и Parquet появятся только после оценки и материализации.</p>
        </div>
        <div className="form-grid">
          <Field label="Направление">
            <select value={selectedDomain} onChange={(event) => {
              const preset = domainPresets.find((item) => item.value === event.target.value);
              if (!preset) return;
              setFilters({
                ...filters,
                subject_level: preset.subject_level,
                subject_id: preset.subject_id,
                subject_name: preset.subject_name,
                filter_mode: preset.filter_mode,
              });
            }}>
              <option value="">Выберите направление</option>
              {domainPresets.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </Field>
          <Field label="Страна">
            <CountryInput value={filters.country_code} options={countryOptions} onChange={(countryCode) => setFilters({ ...filters, country_code: countryCode })} />
          </Field>
          <Field label="Организация">
            <select value={selectedOrg} onChange={(event) => {
              const preset = visibleOrgPresets.find((item) => item.value === event.target.value);
              if (!preset || preset.value === "custom") {
                onOpenResolver();
                return;
              }
              setFilters({
                ...filters,
                institution_id: preset.institution_id,
                institution_name: preset.institution_name,
                institution_ror: preset.ror ?? "",
                country_code: preset.country_code || filters.country_code,
              });
            }}>
              {visibleOrgPresets.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              <option value="custom">Найти другую организацию</option>
            </select>
          </Field>
          <Field label="С даты">
            <input type="date" value={filters.from_publication_date} onChange={(event) => setFilters({ ...filters, from_publication_date: event.target.value })} />
          </Field>
          <Field label="По дату">
            <input type="date" value={filters.to_publication_date} onChange={(event) => setFilters({ ...filters, to_publication_date: event.target.value })} />
          </Field>
          <Field label="Типы публикаций">
            <select value={filters.work_type} onChange={(event) => setFilters({ ...filters, work_type: event.target.value })}>
              {visibleWorkTypeOptions.map((item: SelectOption) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </Field>
        </div>
        <div className="quality-row">
          <CheckPill active label="Исключать отозванные" />
          <CheckPill active label="Исключать служебные тексты" />
          <CheckPill active label="XPAC выключен" />
        </div>
        {subjectMissing && <div className="notice"><b>Выберите направление</b><span>Используйте список пресетов или поиск OpenAlex в тонкой настройке. Без предметного среза загрузка не запускается.</span></div>}
        {dateInvalid && <div className="notice error"><b>Проверьте период</b><span>Дата начала не должна быть позже даты окончания.</span></div>}
        <div className="action-row">
          <button onClick={onOpenResolver}><Settings2 size={16} /> Тонкая настройка</button>
          <button onClick={onSave} disabled={saving || dateInvalid || subjectMissing}>{saving ? <Loader2 size={16} className="spin" /> : <BookOpenCheck size={16} />} Сохранить срез</button>
          <button className="primary" onClick={onEstimate} disabled={estimating || dateInvalid || subjectMissing}>{estimating ? <Loader2 size={16} className="spin" /> : <Gauge size={16} />} Оценить</button>
        </div>
      </section>

      <aside className="panel context-panel">
        <span className="step-badge">Текущий срез</span>
        <h2>{humanSliceTitle(filters)}</h2>
        <KeyValue label="Направление" value={filters.subject_name || "не выбрано"} />
        <KeyValue label="Территория" value={filters.country_code ? countryDisplay(filters.country_code, countryOptions) : "Все страны"} />
        <KeyValue label="Организация" value={filters.institution_name || "Любая организация"} />
        <KeyValue label="Период" value={`${filters.from_publication_date} — ${filters.to_publication_date}`} />
        <KeyValue label="Публикации" value={filters.work_type || "Все поддерживаемые типы"} />
        <KeyValue label="Состояние" value={sliceDoc?.state ?? "draft"} />
      </aside>
    </div>
  );
}

function EstimatePage({
  filters,
  estimate,
  materialization,
  profileId,
  setProfileId,
  maxWorks,
  setMaxWorks,
  maxDumpBytes,
  setMaxDumpBytes,
  onEstimate,
  onPlan,
  onRun,
  estimating,
  planning,
  materializing,
  run,
}: {
  filters: ActiveFilters;
  estimate: any;
  materialization: any;
  profileId: string;
  setProfileId: (value: string) => void;
  maxWorks: number;
  setMaxWorks: (value: number) => void;
  maxDumpBytes: number;
  setMaxDumpBytes: (value: number) => void;
  onEstimate: () => void;
  onPlan: () => void;
  onRun: () => void;
  estimating: boolean;
  planning: boolean;
  materializing: boolean;
  run: any;
}) {
  const decision = estimate?.decision ?? {};
  const rawEstimate = estimate?.estimate ?? {};
  const hasEstimate = Boolean(estimate);
  const canRun = hasEstimate && decision.can_execute !== false;
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">2. SliceEstimate</span>
            <h2>Оценка до скачивания</h2>
            <p>Сначала легкий запрос OpenAlex получает `meta.count`, прогнозирует размер и проверяет лимиты.</p>
          </div>
          <button onClick={onEstimate} disabled={estimating}>{estimating ? <Loader2 size={16} className="spin" /> : <Gauge size={16} />} Обновить оценку</button>
        </div>
        <div className="metric-grid">
          <MetricCard label="Работ найдено" value={fmt(rawEstimate.estimate_count ?? 0)} />
          <MetricCard label="К загрузке" value={fmt(decision.records_to_fetch ?? rawEstimate.planned_records ?? 0)} />
          <MetricCard label="API-запросов" value={fmt(decision.api_requests_planned ?? rawEstimate.api_requests_planned ?? 0)} />
          <MetricCard label="Прогноз raw" value={`${fmt(decision.estimated_raw_mb ?? rawEstimate.estimated_raw_mb ?? 0)} МБ`} />
        </div>
        <div className={canRun ? "notice success" : hasEstimate ? "notice error" : "notice"}>
          <b>{canRun ? "Материализация допустима" : hasEstimate ? "Нужно уточнить срез" : "Оценка еще не выполнена"}</b>
          <span>{decision.strategy ?? "Оценка еще не выполнена"} · {decision.status ?? "нет статуса"}</span>
        </div>
        {[...(decision.reasons ?? []), ...(decision.warnings ?? [])].length > 0 && (
          <ul className="plain-list">
            {[...(decision.reasons ?? []), ...(decision.warnings ?? [])].map((item: string) => <li key={item}>{item}</li>)}
          </ul>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <span className="step-badge">3. Download confirmation</span>
          <h2>Подтверждение загрузки среза</h2>
          <p>Пользователь подтверждает исследовательский срез. Storage plan и ограничения работают только как технические предохранители.</p>
        </div>
        {materialization && (
          <div className="materialization-card">
            <b>{materialization.profile?.label}</b>
            <span>{materialization.materialization_id}</span>
            <small>{materialization.profile?.description}</small>
          </div>
        )}
        <details className="technical-details">
          <summary>Технический бюджет и storage plan</summary>
          <div className="form-grid tight">
            <Field label="Внутренний режим хранения">
              <select value={profileId} onChange={(event) => setProfileId(event.target.value)}>
                {MATERIALIZATION_PROFILES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </Field>
            <Field label="Защитный порог raw">
              <select value={String(maxDumpBytes)} onChange={(event) => setMaxDumpBytes(Number(event.target.value))}>
                {DUMP_SIZE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </Field>
            <Field label="Предохранитель записей">
              <select value={String(maxWorks)} onChange={(event) => setMaxWorks(Number(event.target.value))}>
                {LOAD_LIMIT_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </Field>
          </div>
          <div className="action-row">
            <button onClick={onPlan} disabled={planning || !estimate}>{planning ? <Loader2 size={16} className="spin" /> : <Boxes size={16} />} Подготовить storage plan</button>
          </div>
        </details>
        <div className="action-row">
          <button className="primary" onClick={onRun} disabled={materializing || !canRun}>{materializing ? <Loader2 size={16} className="spin" /> : <UploadCloud size={16} />} Скачать срез</button>
        </div>
      </section>

      <ProgressPanel filters={filters} estimate={estimate} materialization={materialization} run={run} />
    </div>
  );
}

function LocalDataPage({ workbench, dumps, tables, run, running, onRefresh }: { workbench: any; dumps: any; tables: any; run: any; running: boolean; onRefresh: () => void }) {
  const dumpRows = dumps?.dumps ?? workbench?.dumps ?? [];
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">DumpManifest</span>
            <h2>Физические материализации</h2>
            <p>Здесь видны только сохраненные локальные артефакты. Они не являются срезом, а только его материализацией.</p>
          </div>
          <button onClick={onRefresh}><Loader2 size={16} className={running ? "spin" : ""} /> Обновить</button>
        </div>
        {run && <RunCard run={run} />}
        <div className="dump-list">
          {dumpRows.length === 0 && <EmptyState title="Мини-дампов пока нет" detail="Сначала оцените срез и создайте материализацию." />}
          {dumpRows.map((dump: any) => (
            <div className="dump-card" key={`${dump.slice_id}-${dump.raw_jsonl}`}>
              <b>{dump.slice_id}</b>
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
        </div>
        <div className="metric-grid">
          <MetricCard label="Works" value={fmt(tables?.works?.rows ?? 0)} />
          <MetricCard label="Authorships" value={fmt(tables?.authorships?.rows ?? 0)} />
          <MetricCard label="Author-work mart" value={fmt(tables?.author_work?.rows ?? 0)} />
          <MetricCard label="Author indices" value={fmt(tables?.indices?.rows ?? 0)} />
        </div>
      </section>
    </div>
  );
}

function EnrichmentPage({ qualityCounts, tables, onPreview, previewing, run }: { qualityCounts: any; tables: any; onPreview: () => void; previewing: boolean; run: any }) {
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head split">
          <div>
            <span className="step-badge">API enrichment</span>
            <h2>Точечная дозагрузка недостающих сущностей</h2>
            <p>API используется для подсказок, ORCID/ROR/ID и профильной дозагрузки, но не как рабочая база для пересчета индексов.</p>
          </div>
          <button onClick={onPreview} disabled={previewing}>{previewing ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />} Обогатить авторов</button>
        </div>
        {run && <RunCard run={run} />}
        <div className="metric-grid">
          <MetricCard label="Null author" value={fmt(qualityCounts?.authorships_null_author_id ?? 0)} />
          <MetricCard label="Нет авторств" value={fmt(qualityCounts?.works_without_authorships ?? 0)} />
          <MetricCard label="Authors preview" value={fmt(tables?.authors_preview?.rows ?? 0)} />
          <MetricCard label="Флаги качества" value={fmt(Object.values(qualityCounts ?? {}).reduce((a: number, b: any) => a + Number(b || 0), 0))} />
        </div>
      </section>
    </div>
  );
}

function RankingsPage({
  metric,
  setMetric,
  fractionMode,
  setFractionMode,
  tableName,
  setTableName,
  tableQ,
  setTableQ,
  topN,
  setTopN,
  table,
  chartRows,
  onSelect,
  onRecalculate,
  recalculating,
}: {
  metric: string;
  setMetric: (value: string) => void;
  fractionMode: string;
  setFractionMode: (value: string) => void;
  tableName: string;
  setTableName: (value: string) => void;
  tableQ: string;
  setTableQ: (value: string) => void;
  topN: number;
  setTopN: (value: number) => void;
  table?: TableResponse;
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
            {PRIMARY_METRIC_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          <select value={fractionMode} onChange={(event) => setFractionMode(event.target.value)}>
            {FRACTION_MODES.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <select value={tableName} onChange={(event) => setTableName(event.target.value)}>
            <option value="authors_local_metrics">Локальные авторские метрики</option>
            <option value="indices">Индексы</option>
            <option value="ratings">Рейтинговые позиции</option>
            <option value="works">Работы</option>
            <option value="authorships">Авторства</option>
          </select>
          <select value={String(topN)} onChange={(event) => setTopN(Number(event.target.value))}>
            {TOP_N_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          <input value={tableQ} onChange={(event) => setTableQ(event.target.value)} placeholder="Поиск по таблице" />
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
                <Bar dataKey="score" fill="#2563eb" name={metricLabel(metric)} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="panel table-panel">
          <DataGrid data={table} onSelect={onSelect} hiddenFields={["slice_id", "run_id", "fraction_mode"]} />
        </div>
      </section>
    </div>
  );
}

function StatisticsPage({ analytics, table, metric, chartRows, topN }: { analytics: any; table?: TableResponse; metric: string; chartRows: any[]; topN: number }) {
  const scatter = (table?.rows ?? []).slice(0, 120).map((row: any) => ({
    x: Number(row.h ?? row.h_raw ?? 0),
    y: Number(row.c_frac ?? row.c_frac_raw ?? row.score ?? 0),
    name: row.author_display_name,
  }));
  return (
    <div className="stack">
      <section className="metric-grid">
        <MetricCard label={`Когорта Top-${topN}`} value={fmt(table?.total ? Math.min(Number(table.total), topN) : 0)} />
        <MetricCard label="Авторов в распределении" value={fmt(analytics?.distribution?.n ?? 0)} />
        <MetricCard label="Среднее" value={fmt(analytics?.distribution?.mean ?? 0)} />
        <MetricCard label="Медиана" value={fmt(analytics?.distribution?.median ?? 0)} />
      </section>
      <section className="chart-table-grid">
        <div className="panel">
          <h2>Box/Bar распределение индекса</h2>
          <div className="chart-box">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartRows}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" />
                <YAxis />
                <Tooltip />
                <Bar dataKey="score" fill="#0f766e" name={metricLabel(metric)} />
              </BarChart>
            </ResponsiveContainer>
          </div>
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
                <Scatter data={scatter} fill="#7c3aed" />
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

function ReportsPage({ metric, fractionMode, topN, onBuild, building }: { metric: string; fractionMode: string; topN: number; onBuild: () => void; building: boolean }) {
  const rankingUrl = `${API_BASE}/analytics/ranking.csv?fraction_mode=${encodeURIComponent(fractionMode)}&metric=${encodeURIComponent(metric)}&limit=${topN}`;
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
          <a href={`${API_BASE}/reports/bundle.json`}>JSON-пакет отчета</a>
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
      <JsonPanel title="Паспорт материализации" value={materialization ?? sliceDoc?.latest_materialization_plan ?? {}} />
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
  return (
    <div className={`run-card ${run.status === "failed" ? "error" : ""}`}>
      <b>{run.action} · {run.status}</b>
      <span>{run.run_id}</span>
      <ProgressBar percent={progress.percent} label={progress.label} tone={run.status === "failed" ? "error" : "normal"} />
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
  return <label className="field"><span>{label}</span>{children}</label>;
}

function CountryInput({ value, options, onChange }: { value: string; options: SelectOption[]; onChange: (value: string) => void }) {
  const [draft, setDraft] = useState(value ? countryDisplay(value, options) : "");
  const [error, setError] = useState("");

  useEffect(() => {
    setDraft(value ? countryDisplay(value, options) : "");
    setError("");
  }, [value, options]);

  const commit = () => {
    const next = resolveCountryInput(draft);
    if (!draft.trim()) {
      setError("");
      onChange("");
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
        placeholder="Россия, RU или United States"
      />
      <datalist id="country-options">
        {options.filter((item) => item.value).map((item) => (
          <option key={item.value} value={`${item.label} (${item.value})`} />
        ))}
      </datalist>
      {error && <small id="country-error" className="field-error">{error}</small>}
    </div>
  );
}

function countryDisplay(value: string, options: SelectOption[]) {
  const option = options.find((item) => item.value.toUpperCase() === value.toUpperCase());
  return option ? `${option.label} (${option.value})` : countryLabel(value);
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

function ensureOption(options: SelectOption[], value: string, label: string) {
  if (!value || options.some((item) => item.value === value)) return options;
  return [{ value, label }, ...options];
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
