import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Search } from "lucide-react";

import { getJson } from "../../api";
import { EmptyState } from "../../components/ui";
import { fmt } from "../../domain";
import type { EntitySuggestion } from "../../workbench";

type ListPayload<T = Record<string, unknown>> = {
  results?: T[];
};

export type PointLookupTab = "author" | "institution" | "work" | "source";

export function SliceEntityLookup({
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
