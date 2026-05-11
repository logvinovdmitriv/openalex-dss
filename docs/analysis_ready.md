# Analysis-Ready Checklist

Срез готов к аналитическому этапу, если выполнены все условия ниже.

## Scope

- выбран явный `dump_id`;
- выбран явный `run_id`;
- выбран `fraction_mode`;
- в аналитическом payload указаны `filters_hash`, `data_scope` и
  `analysis_author_scope`;
- `data_scope = full_filtered_slice` или явно указан другой backend-scope.

## Data Gate

- dump complete или запуск явно маркирован как exploratory;
- accepted signatures verified;
- local mart filters applied;
- truncated authorships отсутствуют, восстановлены или исключены выбранной
  policy;
- построены таблицы `works`, `authorships`, `work_topics`,
  `author_institutions`, `author_countries`, `author_work`, `indices`,
  `ratings`.

## Metrics Gate

В `indices` должны быть поля:

```text
p
c
c_frac
h
i10
g
rfi_log_frac
iupv_s   # extension, не baseline
```

Таблица `ratings` может содержать все материализованные метрики из `indices`.
Baseline-анализ и baseline-отчет по умолчанию используют только
`p,c,c_frac,h,i10,g`; для IUPV-S запускается отдельный extension-анализ или
явный report с этой метрикой.

Авторы с `rfi_log_frac = 0` должны иметь `iupv_s = 0`.

## Analytics Gate

`scientometric_analysis` должен содержать:

- descriptive;
- correlations;
- rank comparisons;
- metric rank summary;
- pairwise metric comparison;
- findings;
- conclusion draft.

## Report Gate

Должны быть построены:

- `report_bundle.json`;
- CSV exports для descriptive, correlations, findings и outliers;
- `conclusion.md`;
- checksum manifest.
