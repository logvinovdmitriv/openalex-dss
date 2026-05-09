import { useMemo } from "react";
import { Loader2 } from "lucide-react";
import type { TableColumnFilters, TableResponse } from "../../api";
import { RunCard } from "../../components/JobProgress";
import { DataGrid, EmptyState, Field, MetricCard } from "../../components/ui";
import { fmt, type SelectOption } from "../../domain";
import {
  localDataMissingScopeState,
  type LocalDataKind,
  type LocalDataSummary,
  type WorkbenchActiveContext,
  type WorkbenchRun,
} from "../../workbench";
import { DataRestrictionChips } from "./DataRestrictionChips";

type DataViewProps = {
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
  run?: WorkbenchRun;
  running: boolean;
  activeContext?: WorkbenchActiveContext;
  usingActiveContextScope: boolean;
  effectiveRunId: string;
  effectiveDumpId: string;
  onRefresh: () => void;
  onSelect: (value: { kind: "author" | "work"; id: string }) => void;
};

export function DataView({
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
}: DataViewProps) {
  const missingScope = localDataMissingScopeState({ runId: effectiveRunId, dumpId: effectiveDumpId, activeContext });
  const availableTables = (Object.values(localDataSummary?.tables ?? {}) as Array<Record<string, unknown>>).filter((entry) => Boolean(entry.exists));
  const hasAvailableTables = localDataKindOptions.length > 0;
  const materializationActions = new Set(["build_from_openalex", "fetch_slice_dump", "repair_dump"]);
  const runAction = String(run?.action ?? "");
  const runStatus = String(run?.status ?? "");
  const slicePreparationActive = materializationActions.has(runAction) && ["queued", "running", "cancelling"].includes(runStatus);
  const slicePreparationFailed = materializationActions.has(runAction) && runStatus === "failed";
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
          {availableTables.map((entry) => (
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
          <b>{slicePreparationActive ? "Срез еще готовится" : slicePreparationFailed ? "Срез не подготовлен" : "В выбранном срезе нет доступных локальных таблиц"}</b>
          <span>
            {slicePreparationActive
              ? "Таблицы появятся после скачивания, упаковки и расчета индексов. Следите за этапами ниже."
              : slicePreparationFailed
                ? "Подготовка завершилась ошибкой. Если часть файлов уже скачана, используйте восстановление или продолжение загрузки во вкладке “Срезы”."
                : "Вкладка “Данные” показывает только файлы, которые реально существуют в скачанном срезе или созданном расчете. Выберите другой срез или запустите расчет индексов."}
          </span>
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
          <EmptyState
            title={slicePreparationActive ? "Таблицы еще создаются" : slicePreparationFailed ? "Таблицы не созданы" : "Нет локальных таблиц"}
            detail={
              slicePreparationActive
                ? "Данные будут доступны автоматически после завершения подготовки среза."
                : slicePreparationFailed
                  ? "Откройте вкладку “Срезы”, восстановите частичный срез или запустите загрузку повторно."
                  : "В выбранном срезе пока нет скачанных таблиц или результатов расчета, которые можно показать."
            }
          />
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

function activeContextEligibility(value: boolean | null | undefined) {
  if (value === true) return { label: "Готов для финального отчета", className: "status-chip ok" };
  if (value === false) return { label: "Предварительный срез", className: "status-chip warn" };
  return { label: "Пригодность не определена", className: "status-chip" };
}

function activeContextSourceLabel(source?: string) {
  if (source === "materialization") return "загрузка среза";
  if (source === "recalculate") return "пересчет индексов";
  if (source === "import_local_file") return "локальный файл";
  return source || "не задан";
}
