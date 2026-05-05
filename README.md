# OpenAlex DSS

Русскоязычная СППР-лаборатория для воспроизводимых наукометрических срезов OpenAlex.

Ключевая логика проекта:

```text
срез -> оценка объема -> план материализации -> мини-дамп -> локальные индексы -> статистика -> отчет и паспорта
```

OpenAlex API не используется как рабочая база данных. Он нужен для подсказок, сопоставления ID, оценки объема, компактной материализации Works-среза и точечного обогащения. Индексы и рейтинги считаются локально из зафиксированного среза.

## Что находится в репозитории

В Git хранится только кодовая база:

- `apps/api` - FastAPI backend.
- `apps/web` - React/Vite frontend.
- `src/openalex_mvp` - аналитическое ядро.
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
npm install
python3 scripts/run_dss.py
```

После запуска:

- UI: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8000/api/v1`
- Swagger: `http://127.0.0.1:8000/docs`

## Основные вкладки системы

- `Срез и загрузка` - единый плоский сценарий: SliceDefinition, оценка объема, фасеты, бюджет и запуск скачивания.
- `Локальные данные` - DumpManifest и готовность таблиц.
- `Точечное обогащение` - поиск и дозагрузка отдельных сущностей без смешения с локальными индексами.
- `Индексы` - локальные P, C, C_frac, CPP, h, i10, g, ISLV/IUPV/LRDI.
- `Когорты` - фиксация Top-N или ручной выборки авторов перед статистикой.
- `Статистика` - распределения, histogram/log1p данные, boxplot-сводка, scatter и сравнение рейтингов.
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
