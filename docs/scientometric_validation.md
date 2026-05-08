# DSS Validation

Дата контрольного прогона: 2026-05-06.

Этот документ фиксирует end-to-end проверку наукометрического DSS-контура:

```text
локальный Works fixture в формате OpenAlex
-> импорт локального среза
-> расчет индексов
-> выборка TOP-N авторов
-> наукометрический анализ
-> пакет отчета
-> JSON/CSV/Markdown exports
```

Документ обновляется по результатам запуска `scripts/validate_scientometric_dss.py`.

## Режим проверки

Проверка выполнена на детерминированном локальном fixture, а не на сетевом скачивании OpenAlex. Причина: в текущем окружении нет ключа OpenAlex, а установленный загрузчик может требовать ключ для новой загрузки.

Назначение этого прогона - проверить воспроизводимый технический контур, согласованность выбранного среза и наличие всех аналитических артефактов. Он не является научным OpenAlex-срезом и не должен использоваться как содержательный результат по предметной области.

Для реального диссертационного прогона нужно выполнить тот же сценарий через
публичный путь `срез -> оценка -> план скачивания -> скачивание среза`
с подтвержденными подписями оценки/загрузки и `allowed_for_final_analysis=true`.
Внутренний шаг `build_from_openalex` остается сервисной реализацией, а не
публичным способом запуска.

## Команда

Из корня репозитория:

```bash
.venv/bin/python scripts/validate_scientometric_dss.py --reset
```

По умолчанию данные пишутся вне репозитория:

```text
../openalex-dss-validation-data
```

## Зафиксированный срез

```text
validation_mode: deterministic_local_openalex_like_fixture
run_id: validation_scientometric
dump_id: validation_fixture_dump
cohort_id: cohort_validation
cohort_checksum: 0d5ecb3a73559e74b6d8be304386f62cc0bd0e45222d0e04b5cbff88f945aeb8
fraction_mode: integer
baseline_metric: h
rank_top_n: 5
metrics: p, c, cpp, h, i10, g
raw_works: 12
n_authors: 5
findings: 21
report_scope_hash: c65f380e4da05a8e
```

`n_authors: 5` - это число авторов в проверочной выборке TOP-5, а не полное число авторов raw fixture. В fixture есть шестой автор, который не входит в TOP-5 по индексу Хирша.

Схемы аналитических артефактов:

```text
report_bundle_schema: report_bundle
analysis_schema: scientometric_analysis
findings_schema: scientometric_findings
conclusion_schema: scientometric_conclusion
```

Analysis eligibility:

```text
status: validation_fixture_not_for_final_analysis
allowed_for_final_analysis: false
warning: Deterministic local fixture validates the DSS pipeline and exports; it is not a real OpenAlex scientific slice.
```

## Артефакты

Все пути ниже указаны относительно `../openalex-dss-validation-data`:

```text
validation/raw/fixture_works.jsonl
validation/scientometric_validation_manifest.json
validation/exports/validation_scientometric/scientometrics.json
validation/exports/validation_scientometric/descriptive.csv
validation/exports/validation_scientometric/correlations.csv
validation/exports/validation_scientometric/outliers.csv
validation/exports/validation_scientometric/top-outliers.csv
validation/exports/validation_scientometric/findings.csv
validation/exports/validation_scientometric/conclusion.md
validation/exports/validation_scientometric/report_bundle.json
runs/validation_scientometric/reports/report_c65f380e4da05a8e.json
```

Артефакты расчетного запуска:

```text
runs/validation_scientometric/tables/author_work.csv
runs/validation_scientometric/tables/author_work.parquet
runs/validation_scientometric/tables/indices.csv
runs/validation_scientometric/tables/indices.parquet
runs/validation_scientometric/tables/ratings.csv
runs/validation_scientometric/tables/ratings.parquet
runs/validation_scientometric/passports/slice_passport.json
runs/validation_scientometric/passports/calculation_passport.json
runs/validation_scientometric/passports/checksums.json
runs/validation_scientometric/passports/sha256_manifest.txt
```

## Проверка согласованности среза

`scientometrics.json` и `report_bundle.json` содержат один и тот же выбранный срез:

```text
run_id: validation_scientometric
dump_id: validation_fixture_dump
cohort_id: cohort_validation
fraction_mode: integer
baseline_metric: h
rank_top_n: 5
```

`report_bundle.json` содержит ссылки на аналитические exports:

```text
scientometrics_json
scientometrics_descriptive_csv
scientometrics_correlations_csv
scientometrics_outliers_csv
scientometrics_top_outliers_csv
scientometrics_findings_csv
scientometrics_conclusion_md
```

## Размеры экспортов

По контрольному прогону:

```text
descriptive.csv: 7 lines
correlations.csv: 109 lines
outliers.csv: 2 lines
top-outliers.csv: 2 lines
findings.csv: 22 lines
conclusion.md: 47 lines
scientometrics.json: 3566 lines
report_bundle.json: 4240 lines
```

## Checksums

`validation/scientometric_validation_manifest.json` содержит `artifact_checksums` для каждого export и report artifact. Это фиксирует byte-level содержимое текущего validation-прогона и позволяет сравнивать артефакты между повторными запусками. Некоторые runtime artifacts могут включать системные или форматные метаданные, поэтому главным стабильным инвариантом проверки остается совпадение выбранного среза, schema markers, checksum выборки авторов и report scope hash.

## Вывод проверки

Контрольный fixture-прогон подтвердил, что DSS-контур выполняется end-to-end:

1. Works JSONL в формате OpenAlex импортируется как локальный срез.
2. Таблицы, индексы, рейтинги и паспорта создаются.
3. Выборка первых авторов фиксируется с checksum.
4. Scientometric analysis строится по тому же `run_id/dump_id/fraction_mode` и выбранному TOP-N.
5. Report bundle получает тот же scope hash и включает `scientometric_analysis`.
6. JSON/CSV/Markdown exports создаются и трассируются к одному scope.
7. Validation script проверяет инварианты выбранного среза, наличие report export links, существование файлов и SHA-256 checksums.

Ограничение: это validation fixture, а не финальный научный срез OpenAlex. Следующий содержательный контроль должен повторить тот же протокол на реальном малом OpenAlex-срезе с ключом OpenAlex, подтвержденными подписями оценки/загрузки и финальным manifest среза.
