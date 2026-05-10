import { metricDescription, metricFormula, metricLabel, type SelectOption } from "../../domain";

const COMMON_RANKING_METRICS = new Set(["p", "c", "c_frac", "h", "i10", "g"]);

export function rankingMetricOptions(metricCatalogOptions: SelectOption[], fallback: SelectOption[]) {
  const configured = metricCatalogOptions
    .filter((item) => COMMON_RANKING_METRICS.has(item.value))
    .map((item) => ({
      ...item,
      label: item.label || metricLabel(item.value),
      description: item.description || metricDescription(item.value),
      formula: item.formula || metricFormula(item.value),
    }));
  return configured.length ? configured : fallback;
}

export function metricLabelMap(options: SelectOption[]) {
  return Object.fromEntries(options.map((item) => [item.value, item.label]));
}
