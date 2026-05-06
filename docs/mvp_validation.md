# MVP Validation

Дата контрольного прогона: 2026-05-06.

Этот документ фиксирует end-to-end проверку наукометрического MVP-контура:

```text
OpenAlex-like Works fixture
-> local dump import
-> run-scoped indices
-> author cohort
-> scientometric analysis
-> report bundle
-> JSON/CSV/Markdown exports
```

Документ обновляется по результатам запуска `scripts/validate_scientometric_mvp.py`.

## Режим проверки

Проверка выполнена на детерминированном локальном fixture, а не на сетевом OpenAlex CLI download. Причина: в текущем окружении нет `OPENALEX_API_KEY`, а установленный `openalex` CLI требует API key для materialization.

Назначение этого прогона - проверить воспроизводимый технический контур, согласованность scope и наличие всех аналитических артефактов. Он не является научным OpenAlex-срезом и не должен использоваться как содержательный результат по предметной области.

Для реального диссертационного прогона нужно выполнить тот же сценарий через
публичный workflow `slice -> estimate -> materialization plan -> materialization run`
с подтвержденными planner signatures и `allowed_for_final_analysis=true`.
Внутренние шаги `build_from_openalex` и `import_file` остаются сервисной
реализацией, а не публичным способом запуска.

## Команда

Из корня репозитория:

```bash
.venv/bin/python scripts/validate_scientometric_mvp.py --reset
```

По умолчанию данные пишутся вне репозитория:

```text
../openalex-dss-validation-data
```

## Зафиксированный scope

```text
validation_mode: deterministic_local_openalex_like_fixture
run_id: validation_scientometric_mvp
dump_id: validation_fixture_dump
cohort_id: cohort_validation
cohort_checksum: 0d5ecb3a73559e74b6d8be304386f62cc0bd0e45222d0e04b5cbff88f945aeb8
fraction_mode: integer
baseline_metric: h
rank_top_n: 5
metrics: p, c, c_frac, h, i10, g, islv
raw_works: 12
n_authors: 5
findings: 29
report_scope_hash: 66b4ae366925c1bd
```

`n_authors: 5` - это число авторов в зафиксированной Top-5 cohort, а не полное число авторов raw fixture. В fixture есть шестой автор, который не входит в Top-5 когорту по `h`.

Версии аналитических артефактов:

```text
report_bundle_version: report_bundle_v11
analysis_version: scientometrics_v4
findings_version: scientometric_findings_v2
conclusion_version: scientometric_conclusion_v3
```

Analysis eligibility:

```text
status: validation_fixture_not_for_final_analysis
allowed_for_final_analysis: false
warning: Deterministic local fixture validates the MVP pipeline and exports; it is not a real OpenAlex scientific slice.
```

## Артефакты

Все пути ниже указаны относительно `../openalex-dss-validation-data`:

```text
validation/raw/fixture_works.jsonl
validation/mvp_validation_manifest.json
validation/exports/validation_scientometric_mvp/scientometrics.json
validation/exports/validation_scientometric_mvp/descriptive.csv
validation/exports/validation_scientometric_mvp/correlations.csv
validation/exports/validation_scientometric_mvp/rank-shifts.csv
validation/exports/validation_scientometric_mvp/largest-rank-shifts.csv
validation/exports/validation_scientometric_mvp/outliers.csv
validation/exports/validation_scientometric_mvp/top-outliers.csv
validation/exports/validation_scientometric_mvp/findings.csv
validation/exports/validation_scientometric_mvp/conclusion.md
validation/exports/validation_scientometric_mvp/report_bundle.json
runs/validation_scientometric_mvp/reports/report_66b4ae366925c1bd.json
```

Run-scoped pipeline artifacts:

```text
runs/validation_scientometric_mvp/tables/works.csv
runs/validation_scientometric_mvp/tables/authorships.csv
runs/validation_scientometric_mvp/tables/work_topics.csv
runs/validation_scientometric_mvp/tables/author_work.csv
runs/validation_scientometric_mvp/tables/indices.csv
runs/validation_scientometric_mvp/tables/ratings.csv
runs/validation_scientometric_mvp/results/stats_summary.json
runs/validation_scientometric_mvp/results/theory_validation.json
runs/validation_scientometric_mvp/passports/slice_passport.json
runs/validation_scientometric_mvp/passports/calculation_passport.json
runs/validation_scientometric_mvp/passports/checksums.json
```

## Проверка согласованности scope

`scientometrics.json` и `report_bundle.json` содержат один и тот же основной scope:

```text
run_id: validation_scientometric_mvp
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
scientometrics_rank_shifts_csv
scientometrics_largest_rank_shifts_csv
scientometrics_outliers_csv
scientometrics_top_outliers_csv
scientometrics_findings_csv
scientometrics_conclusion_md
```

## Размеры экспортов

По контрольному прогону:

```text
descriptive.csv: 8 lines
correlations.csv: 148 lines
rank-shifts.csv: 31 lines
largest-rank-shifts.csv: 31 lines
outliers.csv: 2 lines
top-outliers.csv: 2 lines
findings.csv: 30 lines
conclusion.md: 55 lines
scientometrics.json: 4423 lines
report_bundle.json: 9338 lines
```

## Checksums

`validation/mvp_validation_manifest.json` содержит `artifact_checksums` для каждого export и run report artifact. Это фиксирует byte-level содержимое текущего validation-прогона и позволяет сравнивать артефакты между повторными запусками. Некоторые runtime artifacts могут включать системные или форматные метаданные, поэтому главным стабильным инвариантом проверки остается совпадение scope, versions, cohort checksum и report scope hash.

## Вывод проверки

Контрольный fixture-прогон подтвердил, что MVP-контур выполняется end-to-end:

1. OpenAlex-like Works JSONL импортируется как локальный dump.
2. Run-scoped таблицы, индексы, рейтинги, паспорта и theory/statistics artifacts создаются.
3. Top-N cohort фиксируется с checksum.
4. Scientometric analysis строится по тому же `run_id/dump_id/cohort_id/fraction_mode`.
5. Report bundle получает тот же scope hash и включает `scientometric_analysis`.
6. JSON/CSV/Markdown exports создаются и трассируются к одному scope.
7. Validation script проверяет инварианты scope, наличие report export links, существование файлов и SHA-256 checksums.

Ограничение: это validation fixture, а не финальный OpenAlex scientific slice. Следующий содержательный контроль должен повторить тот же протокол на реальном малом OpenAlex-срезе с `OPENALEX_API_KEY`, подтвержденными planner signatures и финальным dump manifest.
