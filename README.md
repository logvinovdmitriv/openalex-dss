# OpenAlex DSS

Русскоязычная СППР-лаборатория для воспроизводимых наукометрических срезов OpenAlex.

Ключевая логика проекта:

```text
срез -> оценка объема -> скачивание среза -> локальные таблицы -> индексы -> графики -> отчет и паспорта
```

OpenAlex API не используется как рабочая база данных. Он нужен для подсказок,
сопоставления ID, оценки объема, просмотра доступных лимитов и точечного
обогащения. Корпус материализуется выбранной backend-стратегией: OpenAlex CLI,
API cursor, ids-then-hydrate, локальный snapshot scan или импорт уже
скачанного JSONL. После этого индексы и рейтинги считаются локально из
выбранного среза.

## Что находится в репозитории

В Git хранится только кодовая база:

- `apps/api` - FastAPI backend.
- `apps/web` - React/Vite frontend.
- `src/openalex_dss` - аналитическое ядро.
- `configs` и `config` - версионируемые настройки, реестры и пример конфигурации.
- `scripts` - воспроизводимые служебные скрипты.
- `tests` - unit-тесты.
- `docs` - методика и архитектура.
- `package-lock.json`, `requirements.lock` - lock-файлы для воспроизводимого разворачивания.

В Git не должны попадать:

- `node_modules/`
- `.venv/`
- `apps/web/dist/`
- raw-файлы OpenAlex
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

Внешняя папка данных содержит исходные файлы срезов, нормализованные таблицы, отчеты, паспорта, контрольные суммы, API-кэш и локальную metadata-БД. Она не коммитится.

## Быстрый старт

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r apps/api/requirements.txt
.venv/bin/pip install openalex-official
npm install
./start
```

После запуска:

- UI: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8000/api/v1`
- Swagger: `http://127.0.0.1:8000/docs`

Управление локальными сервисами из корня проекта:

```bash
./start    # запустить backend и frontend в фоне
./status   # проверить процессы, порты и адреса
./stop     # остановить backend и frontend
./restart  # перезапустить оба сервиса
```

То же самое доступно через `npm start`, `npm run status`, `npm stop`, `npm restart`.
Логи пишутся в `.runtime/logs/`, pid-файлы - в `.runtime/`.

## Основные вкладки системы

Верхнее меню короткое, а полные названия и методические пояснения остаются внутри страниц:

- `Срез` - единый сценарий: фильтры, выбор уже скачанного среза, оценка объема, папка загрузки и запуск скачивания.
- `Данные` - единая таблица выбранного среза: выбор таблицы кнопками, ограничения по каждому столбцу через заголовок, подсветка активных ограничений, сортировка и TOP-N.
- `Индексы` - публикации, цитирования, средняя цитируемость, индекс Хирша, i10-индекс, g-индекс и рейтинги авторов.
- `Аналитика` - распределения, диапазоны значений, корреляции и выводы по выборке из `Данные`, разнесенные по подразделам внутри страницы.
- `Отчеты` - пакет отчета, выгрузки локальных таблиц и подраздел с паспортами воспроизводимости.

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

Рабочий путь среза:

```text
описание среза -> оценка объема -> план скачивания -> локальные файлы -> расчет индексов -> отчет
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
- `docs/analysis_ready.md` - checklist готовности выбранного run/dump к аналитике.
- `docs/report_outline.md` - структура аналитической записки по результатам запуска.
- `docs/architecture_extension.md` - границы модулей и правила дальнейшего расширения системы.

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
