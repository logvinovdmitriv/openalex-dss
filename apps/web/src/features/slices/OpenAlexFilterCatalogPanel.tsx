import { Field } from "../../components/ui";
import type { ActiveFilters } from "../../domain";
import type { OpenAlexFilterCatalogItem, OpenAlexFilterCatalogPayload } from "../../workbench";

const FILTER_BINDINGS: Record<string, keyof ActiveFilters> = {
  country: "country_code",
  institution: "institution_id",
  author: "author_id",
  source: "source_id",
  work_type: "work_type",
  from_publication_date: "from_publication_date",
  to_publication_date: "to_publication_date",
  language: "language",
  source_type: "source_type",
  open_access: "open_access_is_oa",
  has_abstract: "has_abstract",
  min_citations: "min_cited_by_count",
  doi: "doi",
  search: "text_search_query",
};

export function OpenAlexFilterCatalogPanel({
  catalog,
  filters,
  onChange,
}: {
  catalog?: OpenAlexFilterCatalogPayload | null;
  filters: ActiveFilters;
  onChange: (filters: ActiveFilters) => void;
}) {
  const groups = catalog?.groups ?? [];
  if (!groups.length) {
    return (
      <section className="notice">
        <b>Каталог фильтров OpenAlex</b>
        <span>Каталог пока не загружен. Основные поля среза остаются доступны выше.</span>
      </section>
    );
  }
  const boundFilters = groups.flatMap((group) => (group.filters ?? []).filter((item) => Boolean(bindingFor(item))));
  const riskyFilters = groups.flatMap((group) => (group.filters ?? []).filter((item) => item.fetch_pushdown_status === "risky"));
  return (
    <details className="technical-details">
      <summary>Каталог фильтров OpenAlex</summary>
      <div className="notice">
        <b>Catalog-driven режим</b>
        <span>Форма ниже построена по backend-каталогу: каждое поле имеет русское название, стадию применения и риск для финального анализа.</span>
      </div>
      <div className="form-grid tight">
        {boundFilters.map((item) => {
          const binding = bindingFor(item);
          if (!binding) return null;
          return (
            <CatalogFilterControl
              key={item.filter_id}
              item={item}
              value={String(filters[binding] ?? "")}
              onChange={(value) => onChange({ ...filters, [binding]: value })}
            />
          );
        })}
      </div>
      {riskyFilters.length > 0 && (
        <div className="notice warn">
          <b>Фильтры authorships лучше применять локально</b>
          <span>{riskyFilters.map((item) => item.short_label_ru || item.label_ru || item.filter_id).join(", ")}: для финального отчета эти ограничения безопаснее накладывать после нормализации скачанного предметного среза.</span>
        </div>
      )}
      <div className="filter-catalog-grid">
        {groups.map((group) => (
          <div className="mini-card" key={group.group_id}>
            <b>{group.label_ru || group.group_id}</b>
            <small>{(group.filters ?? []).map((item) => item.short_label_ru || item.label_ru || item.filter_id).join(" · ")}</small>
          </div>
        ))}
      </div>
    </details>
  );
}

function bindingFor(item: OpenAlexFilterCatalogItem): keyof ActiveFilters | undefined {
  const backendBinding = String(item.ui_binding || item.target_filter_field || "");
  return (backendBinding || FILTER_BINDINGS[item.filter_id]) as keyof ActiveFilters | undefined;
}

function CatalogFilterControl({ item, value, onChange }: { item: OpenAlexFilterCatalogItem; value: string; onChange: (value: string) => void }) {
  const label = item.short_label_ru || item.label_ru || item.filter_id;
  const hint = item.warning_ru || item.user_hint_ru || item.description_ru || item.risk_reason_ru || "";
  const inputType = item.input_type || "text";
  if (inputType === "boolean") {
    return (
      <Field label={label}>
        <select value={value} onChange={(event) => onChange(event.target.value)}>
          <option value="">Не задано</option>
          <option value="true">Да</option>
          <option value="false">Нет</option>
        </select>
        {hint && <small className="field-hint">{hint}</small>}
      </Field>
    );
  }
  if (inputType === "number") {
    return (
      <Field label={label}>
        <input type="number" value={value} onChange={(event) => onChange(event.target.value)} />
        {hint && <small className="field-hint">{hint}</small>}
      </Field>
    );
  }
  if (inputType === "date") {
    return (
      <Field label={label}>
        <input type="date" value={value} onChange={(event) => onChange(event.target.value)} />
        {hint && <small className="field-hint">{hint}</small>}
      </Field>
    );
  }
  return (
    <Field label={label}>
      <input value={value} onChange={(event) => onChange(event.target.value)} placeholder={item.value_source ? "ID или значение из справочника" : ""} />
      {hint && <small className="field-hint">{hint}</small>}
    </Field>
  );
}
