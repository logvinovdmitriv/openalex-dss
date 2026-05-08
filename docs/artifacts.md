# Модель артефактов

DSS использует только артефакты выбранного среза как источник истины. Доступ к
данным привязан к явным `dump_id`, `run_id` и `report_scope_hash`; endpoints не
читают глобальные запасные файлы. В пользовательском интерфейсе `dump_id`
называется локальным срезом.

## Классы артефактов

| Артефакт | Класс | Владелец | Для чего используется |
| --- | --- | --- | --- |
| `raw/openalex_cli/{slice_id}/works.jsonl.gz` | основной | срез | неизменяемая сырая загрузка Works из установленного загрузчика OpenAlex |
| `raw/openalex_cli/{slice_id}/dump_manifest.json` | основной | срез | происхождение загрузки, подписи и пригодность для итогового анализа |
| `dumps/{dump_id}/dump_manifest.json` | основной | срез | проверки воспроизводимости и восстановление статуса пригодности |
| `dumps/{dump_id}/normalized/*.csv` | временный | срез | staging CSV только на время импорта |
| `dumps/{dump_id}/parquet/*_flat.parquet` | временный | срез | staging parquet только до материализации канонических таблиц |
| `dumps/{dump_id}/quality_report.json` | основной | срез | качество нормализации локального корпуса |
| `dumps/{dump_id}/fetch_meta.json` | основной | срез | происхождение импорта или скачивания локального корпуса |
| `tables/{dump_id}/works.parquet` | основной | срез | просмотр локальных данных, рейтинги, наукометрический анализ |
| `tables/{dump_id}/authorships.parquet` | основной | срез | просмотр локальных данных и построение таблицы авторов |
| `tables/{dump_id}/work_topics.parquet` | основной | срез | диагностика тематик локального корпуса |
| `runs/{run_id}/tables/author_work.csv` | основной | расчет | публикации авторов и локальные выгрузки |
| `runs/{run_id}/tables/indices.csv` | основной | расчет | рейтинги авторов, выборка TOP-N, наукометрический анализ |
| `runs/{run_id}/tables/ratings.csv` | основной | расчет | ранги и выгрузки рейтингов |
| `runs/{run_id}/passports/slice_passport.json` | основной | расчет | паспорт среза для пакета отчета |
| `runs/{run_id}/passports/calculation_passport.json` | основной | расчет | паспорт расчета и пригодность к итоговому анализу |
| `runs/{run_id}/passports/checksums.json` | основной | расчет | checksums артефактов выбранного среза |
| `runs/{run_id}/passports/sha256_manifest.txt` | основной | расчет | текстовый SHA-256 manifest рядом с `checksums.json` |
| `runs/{run_id}/passports/pipeline_summary.json` | основной | расчет | сводка расчета для пакета отчета |
| `runs/{run_id}/analytics/precompute_manifest.json` | основной | расчет | список заранее подготовленных аналитических артефактов |
| `runs/{run_id}/reports/report_{report_scope_hash}.json` | основной | отчет | воспроизводимый пакет отчета |
| `workbench/active_context.json` | указатель | текущий срез | маленький указатель на активные `run_id` и `dump_id` |

## Правила

- `dump_id` владеет локальным корпусом: raw manifest плюс `works`,
  `authorships` и `work_topics`.
- Сырые импорты нормализуются потоковым чтением JSONL в scoped staging
  `dumps/{dump_id}/normalized` и `dumps/{dump_id}/parquet`, затем создают
  канонические parquet-таблицы в `tables/{dump_id}`. После успешной
  материализации временный staging удаляется, чтобы не хранить одну и ту же
  информацию в нескольких форматах.
- Метаданные импорта или скачивания пишутся в
  `dumps/{dump_id}/fetch_meta.json` и копируются в
  `runs/{run_id}/passports/fetch_meta.json` из этого scoped-источника. Они не
  пишутся в глобальный путь паспортов.
- Запуски импорта включают `dumps/{dump_id}/fetch_meta.json` и
  `dumps/{dump_id}/quality_report.json` в checksum-паспорта вместе с таблицами
  среза и результатами расчета. Если manifest среза передан при импорте, он
  записывается до расчета и включается как `dump/dump_manifest.json`.
- Перерасчеты включают существующие файлы происхождения из `dumps/{dump_id}` в
  checksum-паспорта, если эти файлы есть.
- `run_id` владеет производными расчетами: строками автор-публикация,
  индексами, рейтингами, паспортами расчета и пакетами отчета.
- После скачивания или восстановления среза обязательные производные данные
  строятся один раз: `author_work`, `indices`, `ratings`, checksum-паспорта,
  дефолтный пакет отчета и дефолтный наукометрический cache для интерфейса.
  Повторное открытие выбранного среза использует эти scoped artifacts, а не
  пересчитывает аналитику заново.
- Паспорта среза, расчета, checksums и сводки pipeline пишутся прямо в
  `runs/{run_id}/passports`, когда известен `run_id`. Глобальные пути паспортов
  не являются источником для этих артефактов.
- Checksum-паспорта строятся из артефактов выбранного среза и расчета.
  Текстовый checksum manifest пишется рядом с
  `runs/{run_id}/passports/checksums.json` как
  `runs/{run_id}/passports/sha256_manifest.txt`.
- Создание паспортов требует явную карту primary artifacts от pipeline. Оно не
  сканирует глобальные normalized/results/passport пути и не пишет общий
  checksum manifest вне `runs/{run_id}`.
- Архивация расчета записывает или копирует артефакты `run_id` из scoped
  outputs и таблицы среза из scoped input manifest. Глобальные запасные пути не
  используются как источник архива.
- `author_work` принадлежит `run_id`; его нельзя архивировать как таблицу среза
  в `tables/{dump_id}`.
- `report_scope_hash` фиксирует воспроизводимость отчета для выбранной метрики,
  фильтров среза, ограничений из вкладки `Данные`, сортировки, TOP-N, базовой
  метрики и параметров наукометрического анализа.
- Выборка из вкладки `Данные` передается как единый контракт:
  `data_filters`, `data_sort`, `data_direction`, `data_limit`. Эти параметры
  применяются к индексам, графикам, наукометрическим CSV/Markdown export и
  пакету отчета.
- Просмотр локальных данных и CSV требуют явный `run_id`/`dump_id`.
- Analytics JSON, CSV и Markdown требуют явный `run_id`/`dump_id`.
- `/workbench` читает сводки таблиц из `active_context`, когда там есть активный
  `run_id` или `dump_id`. Без активного среза `/workbench` не показывает
  глобальные или запасные counts как текущие данные.
- `/workbench` читает quality summary из активного `run_id`. Без активного
  расчета quality summary пустая.
- Итоговый отчет и analytics paths требуют scoped artifacts и не используют
  неявные запасные пути.
- Чтобы хранилище не росло бесконечно, временный dump staging удаляется после
  materialization, на один run сохраняется ограниченное число report bundles и
  analytics cache files, а для одного среза сохраняются только последние
  расчетные runs.

## Указатель активного среза

`workbench/active_context.json` is intentionally small:

```json
{
  "active_run_id": "run_...",
  "active_dump_id": "dump_...",
  "source": "materialization|recalculate|import_local_file",
  "analysis_eligibility_status": "final",
  "allowed_for_final_analysis": true,
  "updated_at_utc": "2026-05-07T00:00:00Z"
}
```

`/workbench` отдает этот указатель для состояния интерфейса. UI может
использовать активный срез как значение по умолчанию для локальных таблиц,
рейтингов и наукометрического анализа, но итоговые отчеты
должны передавать явные параметры выбранного среза. Если указателя нет,
`/workbench` возвращает пустую сводку таблиц. Качество расчета читается только
из активного `run_id`; при срезе без расчета или без активного среза quality
summary пустая.
