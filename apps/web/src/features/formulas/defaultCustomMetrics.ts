import type { CustomMetricDefinition } from "../../api";

export const DEFAULT_CUSTOM_METRICS: CustomMetricDefinition[] = [
  {
    id: "custom_iupv_s",
    label: "IUPV-S",
    description: "Простая авторская формула: все работы, долевой вклад, log1p-сглаживание и процентильная шкала 0-100.",
    expression: "100 * pr_rfi_log_frac",
  },
];
