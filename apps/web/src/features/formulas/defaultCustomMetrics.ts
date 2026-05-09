import type { CustomMetricDefinition } from "../../api";

export const DEFAULT_CUSTOM_METRICS: CustomMetricDefinition[] = [
  {
    id: "custom_added_rating",
    label: "Пример собственного рейтинга",
    description: "Пример собственной формулы: сводный рейтинг по процентилям публикаций, индекса Хирша и долевых цитирований.",
    expression: "100 * (pr_p * pr_h * pr_c_frac) ** (1 / 3)",
  },
];

