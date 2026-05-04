from __future__ import annotations

from typing import Any

from app.services import filesystem, registry, snapshot, warehouse, workflow


METRICS = [
    {"id": "p", "label": "P: число работ автора в срезе", "group": "Авторские индексы"},
    {"id": "c", "label": "C: суммарные цитирования работ", "group": "Авторские индексы"},
    {"id": "c_frac", "label": "C_frac: фракционные цитирования", "group": "Фракционный учет"},
    {"id": "cpp", "label": "CPP: средние цитирования на работу", "group": "Авторские индексы"},
    {"id": "h", "label": "h-index внутри выбранного среза", "group": "Авторские индексы"},
    {"id": "i10", "label": "i10: работы с 10+ цитированиями", "group": "Авторские индексы"},
    {"id": "g", "label": "g-index внутри выбранного среза", "group": "Авторские индексы"},
    {"id": "m_local", "label": "m_local: h-index на локальный публикационный возраст", "group": "Авторские индексы"},
    {"id": "top1_share", "label": "top1_share: доля цитирований top-1 работы", "group": "Диагностика"},
    {"id": "lrdi", "label": "LRDI: экспериментальный локальный робастный индекс", "group": "Экспериментальные"},
    {"id": "f5", "label": "f5: операционная threshold-метрика 5+ цитирований", "group": "Экспериментальные"},
    {"id": "fm5", "label": "fm5: операционная сумма долей для 5+ цитирований", "group": "Экспериментальные"},
    {"id": "iupv", "label": "IUPV: геометрическое среднее процентилей P/h/C_frac", "group": "Интегральная оценка"},
    {"id": "islv", "label": "ISLV: сбалансированный локальный вклад со штрафом top-1", "group": "Собственная формула"},
]

FRACTION_MODES = [
    {"id": "strict_authors_count", "label": "Строгий фракционный счет"},
    {"id": "renorm_valid_authors", "label": "Перенормировка валидных авторов"},
    {"id": "integer", "label": "Целочисленный счет"},
]

DATA_SOURCES = [
    {
        "id": "openalex_api",
        "label": "OpenAlex API",
        "role": "подсказки/ID, компактный фиксированный срез, точечное обогащение авторов и работ",
        "status": "implemented",
    },
    {
        "id": "openalex_snapshot",
        "label": "OpenAlex S3 snapshot",
        "role": "массовое обогащение, пакетные обновления, работа с полными дампами",
        "status": "prepared",
    },
    {
        "id": "local_filesystem",
        "label": "Локальная файловая система",
        "role": "импорт локальных JSONL/JSONL.GZ дампов, CSV/Parquet артефакты, DuckDB-витрины",
        "status": "implemented",
    },
]


def system_catalog() -> dict[str, Any]:
    config_registry = registry.registry()
    metric_registry = config_registry.get("metric_registry") or []
    native_metric_registry = config_registry.get("native_metric_registry") or []
    ranking_profiles = config_registry.get("ranking_profiles") or []
    return {
        "metrics": _catalog_metrics(metric_registry) or METRICS,
        "native_metrics": native_metric_registry,
        "fraction_modes": FRACTION_MODES,
        "tables": warehouse.list_tables(),
        "data_sources": DATA_SOURCES,
        "ranking_profiles": ranking_profiles,
        "execution_limits": config_registry.get("execution_limits") or {},
        "openalex_filter_registry": config_registry.get("openalex_filter_registry") or {},
        "domain_presets": config_registry.get("domain_presets") or [],
        "organization_presets": config_registry.get("organization_presets") or [],
        "filter_schema": config_registry.get("filter_schema") or {},
        "safe_roots": filesystem.storage_overview()["safe_roots"],
        "openalex_snapshot_entities": snapshot.ENTITIES,
        "export_formats": ["csv", "json"],
        "workflow_stages": workflow.STAGE_DEFINITIONS,
        "author_filters": [
            {"id": "field", "label": "Область OpenAlex", "source": "works.primary_topic.field.id"},
            {"id": "subfield", "label": "Подобласть OpenAlex", "source": "works.primary_topic.subfield.id"},
            {"id": "topic", "label": "Тема OpenAlex", "source": "works.primary_topic.id"},
            {"id": "keyword", "label": "Keyword OpenAlex", "source": "works.keywords.id"},
            {"id": "institution", "label": "Организация", "source": "works.authorships.institutions.id"},
            {"id": "country", "label": "Страна организации автора", "source": "works.authorships.institutions.country_code"},
            {"id": "period", "label": "Период публикаций", "source": "works.publication_date"},
            {"id": "type", "label": "Тип работы", "source": "works.type=article|review|conference-paper"},
        ],
    }


def _catalog_metrics(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for item in items:
        metric_id = str(item.get("metric_id") or "").strip()
        if not metric_id:
            continue
        metrics.append(
            {
                "id": metric_id,
                "label": str(item.get("label") or metric_id),
                "group": str(item.get("group") or ""),
                "source": str(item.get("source") or "computed_from_slice_works"),
                "formula": item.get("formula"),
                "algorithm": item.get("algorithm"),
                "warning": item.get("warning"),
            }
        )
    return metrics
