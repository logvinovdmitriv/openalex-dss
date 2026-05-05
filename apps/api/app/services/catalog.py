from __future__ import annotations

from typing import Any

from app.providers import openalex_cli_provider
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
        "data_sources": config_registry.get("data_sources") or [],
        "ranking_profiles": ranking_profiles,
        "execution_limits": config_registry.get("execution_limits") or {},
        "storage_profiles": config_registry.get("storage_profiles") or [],
        "ui_options": config_registry.get("ui_options") or {},
        "openalex_filter_registry": config_registry.get("openalex_filter_registry") or {},
        "openalex_cli": openalex_cli_provider.cli_status(),
        "domain_presets": config_registry.get("domain_presets") or [],
        "organization_presets": config_registry.get("organization_presets") or [],
        "filter_schema": config_registry.get("filter_schema") or {},
        "safe_roots": filesystem.storage_overview()["safe_roots"],
        "openalex_snapshot_entities": snapshot.ENTITIES,
        "export_formats": ["csv", "json"],
        "workflow_stages": workflow.STAGE_DEFINITIONS,
        "author_filters": _openalex_filter_options(config_registry.get("openalex_filter_registry") or {}),
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


def _openalex_filter_options(filter_registry: dict[str, Any]) -> list[dict[str, str]]:
    filters = filter_registry.get("filters") or {}
    out: list[dict[str, str]] = []
    for filter_id, item in filters.items():
        if not isinstance(item, dict):
            continue
        works_filter = item.get("works_filter") or {}
        field = str(works_filter.get("field") or "").strip()
        if field and item.get("class") == "openalex_pushdown":
            out.append({"id": str(filter_id), "label": str(item.get("label") or filter_id), "source": f"works.{field}"})
    return out
