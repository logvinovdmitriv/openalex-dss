import { MetricCard } from "../../components/ui";
import { fmt } from "../../domain";
import { bytesToMb, type EstimatePayload, type RateLimitPayload } from "../../workbench";

type EstimateValues = NonNullable<EstimatePayload["estimate"]>;
type EstimateDecision = NonNullable<EstimatePayload["decision"]>;

export function RateLimitPanel({
  rateLimit,
  apiKeySet,
  estimate,
}: {
  rateLimit?: RateLimitPayload | null;
  apiKeySet: boolean;
  estimate?: EstimateValues | null;
}) {
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

export function EstimateBudget({ estimate, decision }: { estimate?: EstimateValues | null; decision?: EstimateDecision | null }) {
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

export function EstimateFacets({ facets }: { facets?: EstimateValues["facets"] | null }) {
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

