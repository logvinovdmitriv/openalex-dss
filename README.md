# OpenAlex DSS

Русскоязычная СППР-лаборатория для воспроизводимых наукометрических срезов OpenAlex.

Ключевая логика проекта:

```text
срез -> оценка объема -> план материализации -> мини-дамп -> локальные индексы -> наукометрический анализ -> отчет и паспорта
```

OpenAlex API не используется как рабочая база данных. Он нужен для подсказок, сопоставления ID, оценки объема, просмотра доступных лимитов и точечного обогащения. Скачивание корпуса среза выполняется через установленный OpenAlex CLI, после чего индексы и рейтинги считаются локально из зафиксированного дампа.

## Что находится в репозитории

В Git хранится только кодовая база:

- `apps/api` - FastAPI backend.
- `apps/web` - React/Vite frontend.
- `src/openalex_dss` - аналитическое ядро.
- `configs` и `config` - версионируемые профили, реестры и пример конфигурации.
- `scripts` - воспроизводимые CLI-шаги.
- `tests` - unit-тесты.
- `docs` - методика и архитектура.
- `package-lock.json`, `requirements.lock` - lock-файлы для воспроизводимого разворачивания.

В Git не должны попадать:

- `node_modules/`
- `.venv/`
- `apps/web/dist/`
- raw OpenAlex dumps
- CSV/Parquet/JSONL/XLSX/ZIP отчеты
- DuckDB/SQLite runtime-базы
- screenshots и Playwright output
- любые данные из рабочих запусков

Это закреплено в `.gitignore`.

## Данные вне репозитория

По умолчанию все данные создаются рядом с проектом:

```text
../openalex-dss-data
```

Можно задать свой путь:

```bash
export OPENALEX_DSS_DATA_DIR="/absolute/path/to/openalex-dss-data"
```

Внешняя папка данных содержит raw-слой, нормализованные таблицы, marts, отчеты, паспорта, checksums, API-кэш и локальную metadata-БД. Она не коммитится.

## Быстрый старт

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r apps/api/requirements.txt
.venv/bin/pip install openalex-official
npm install
python3 scripts/run_dss.py
```

После запуска:

- UI: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8000/api/v1`
- Swagger: `http://127.0.0.1:8000/docs`

## Основные вкладки системы

Верхнее меню короткое, а полные названия и методические пояснения остаются внутри страниц:

- `Срез` - единый плоский сценарий: SliceDefinition, оценка объема, фасеты, бюджет и запуск скачивания.
- `Данные` - DumpManifest, локальные пакеты и готовность Parquet/CSV scoped таблиц.
- `Профили` - точечный поиск автора/ORCID, организации/ROR, работы/DOI и источника без смешения с локальными индексами.
- `Индексы` - локальные P, C, C_frac, CPP, h, i10, g, ISLV/IUPV/LRDI.
- `Когорты` - фиксация Top-N или ручной выборки авторов перед графиками и отчетом.
- `Графики` - распределения, histogram/log1p данные, boxplot-сводка, scatter и сравнение рейтингов.
- `Отчеты` - CSV/JSON bundle.
- `Паспорта` - воспроизводимость среза, дампа, расчета и качества данных.

## API-контур срезов

```text
POST /api/v1/slices
POST /api/v1/slices/{slice_id}/resolve
POST /api/v1/slices/{slice_id}/estimate
POST /api/v1/slices/{slice_id}/materialization-plans
POST /api/v1/materializations/{materialization_id}/run
GET  /api/v1/dumps
GET  /api/v1/workbench
GET  /api/v1/catalog
```

Справочники для UI берутся из OpenAlex и локального metadata-кэша:

```text
GET /api/v1/openalex/subjects
GET /api/v1/openalex/countries
GET /api/v1/openalex/work-types
GET /api/v1/openalex/institutions
GET /api/v1/openalex/authors
GET /api/v1/openalex/works
GET /api/v1/openalex/sources
```

Старый подход "скачать данные по фильтру" заменен slice-centric моделью:

```text
SliceDefinition != Dump
SliceDefinition -> ResolvedSlice -> SliceEstimate -> MaterializationPlan -> DumpManifest -> AnalysisRun
```

## Проверка перед коммитом

```bash
.venv/bin/python -m unittest discover -s tests
npm run build:web
git ls-files | rg '(^|/)(node_modules|\.venv|dist|data|output)(/|$)'
```

Последняя команда не должна находить пакеты, сборки и рабочие данные, кроме `data/README.md`.

## Приемка и эксплуатация

- `docs/acceptance.md` - минимальный gate перед передачей системы в пилотное использование.
- `docs/user_runbook.md` - короткий пользовательский сценарий и эксплуатационные ограничения.

## Чистка локальных артефактов

Обычная чистка удаляет кэши Python, frontend build, screenshots и временный `output/`:

```bash
npm run clean
```

Полная чистка рабочей папки удаляет также локальные зависимости, repo-local данные и пустые старые каталоги:

```bash
npm run clean:all
```

Скрипт не удаляет tracked-файлы и не трогает внешний каталог данных, заданный через `OPENALEX_DSS_DATA_DIR`.
