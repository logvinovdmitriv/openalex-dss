# Приемочный gate

Документ фиксирует минимальную проверку перед передачей OpenAlex DSS в пилотное
использование. Проверка локальная и воспроизводимая: backend-тесты, frontend
build, чистота репозитория и детерминированный end-to-end сценарий.

## Обязательные команды

Запускайте из корня репозитория:

```bash
pytest tests/test_repository_hygiene.py -q
pytest tests/test_pipeline_integrity.py -q
pytest tests/test_edge_cases.py -q
pytest tests/test_slice_workbench.py -q
pytest tests/test_analytics_routes.py -q
pytest tests/test_local_data_routes.py -q
pytest tests/test_web_workbench_scope.py -q
pytest tests/test_api_surface.py -q
pytest tests/test_validation_script.py -q
pytest tests/test_scientometrics.py -q
```

Затем соберите frontend:

```bash
cd apps/web
npm run build
cd ../..
```

Затем запустите детерминированную end-to-end проверку:

```bash
python scripts/validate_scientometric_dss.py --reset
```

## Критерии приемки

Система готова к пилотной передаче, если выполнены все условия:

- Тест чистоты репозитория проходит.
- Перечисленные backend-тесты проходят.
- Production build frontend проходит.
- Validation script возвращает `status: ok`.
- Validation output содержит `report_bundle_schema: report_bundle`.
- Validation output содержит `analysis_schema: scientometric_analysis`.
- Validation output содержит `findings_schema: scientometric_findings`.
- Validation output содержит `conclusion_schema: scientometric_conclusion`.
- Validation output содержит checksums для пакета отчета, наукометрического JSON,
  findings CSV, conclusion Markdown и табличных export-файлов.
- Пакет отчета строится из явных `run_id` и `dump_id`.
- Local-data и analytics routes требуют выбранный срез.
- API errors возвращаются в едином JSON-виде `error.title`, `error.message`,
  `error.action`; интерфейс показывает эти сообщения как уведомления, а не
  техническое `HTTP 422` или `Internal Server Error`.
- Ошибки OpenAlex API возвращаются как контролируемые `502` с диагностикой, а не
  как необработанный Internal Server Error.
- Уже скачанные срезы можно выбрать, проанализировать и удалить без API.
- Scoped dump tables доступны для `works`, `authorships`, `work_topics`,
  `author_institutions`, `author_countries`, а расчетные таблицы доступны для
  `author_work`, `indices`, `ratings`.
- Интерактивные JSON-таблицы ограничены страницей/разумным лимитом ответа.
  Большие выгрузки выполняются через CSV endpoints; тяжелые фильтры,
  сортировка, TOP-N и собственные формулы применяются на backend.
- `indices` и `ratings` содержат `rfi_log_frac` и `iupv_s`; авторы с
  `rfi_log_frac = 0` получают `iupv_s = 0`.
- `iupv_s` не входит в базовый набор `P`, `C`, `C_frac`, `h`, `i10`, `g` и
  используется только как дополнительная авторская формула.
- Формульное поле `pr_rfi_log_frac` в Python- и DuckDB-пути дает тот же
  positive-only percentile policy, что и встроенный `iupv_s`.
- Использование ключа OpenAlex видно пользователю: справочники, оценка объема,
  проверка лимитов, точечное обогащение и новая загрузка среза. Установленный
  загрузчик OpenAlex может требовать ключ для новой загрузки.

## Инварианты контракта

Принятая система использует такую модель владения артефактами:

```text
dumps/<dump_id>/...
tables/<dump_id>/...
runs/<run_id>/tables/...
runs/<run_id>/passports/...
runs/<run_id>/reports/report_<report_scope_hash>.json
workbench/active_context.json
```

Публичные названия таблиц:

```text
works
authorships
work_topics
author_institutions
author_countries
author_work
indices
ratings
```

Слой отчета:

```text
scientometric_analysis
findings
conclusion
checksums
exports
```

## Примечание для передачи

Детерминированная validation fixture подтверждает внутреннюю согласованность
pipeline, артефактов, пакета отчета, export-файлов и checksums. Она не доказывает
научные утверждения по реальной предметной области OpenAlex. Реальный анализ
требует подходящий корпус, подтвержденные подписи оценки/загрузки и экспертную
проверку сформированного отчета.
