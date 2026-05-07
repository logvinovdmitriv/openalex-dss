from __future__ import annotations

import sys
from typing import Any

from app.core.paths import ROOT, SRC
from app.services import author_slice, warehouse

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_dss.config import config_to_dict, load_config  # noqa: E402


STAGE_DEFINITIONS = [
    {
        "id": "slice",
        "label": "Срез",
        "description": "Выбраны предметный срез OpenAlex, период публикаций и необязательная страна организации автора.",
    },
    {
        "id": "ingestion",
        "label": "Загрузка",
        "description": "Создан или импортирован фиксированный локальный срез OpenAlex Works JSONL.",
    },
    {
        "id": "flatten",
        "label": "Таблицы",
        "description": "JSON приведён к плоским таблицам работ и авторств.",
    },
    {
        "id": "indices",
        "label": "Индексы",
        "description": "Сформированы публикации, цитирования, средняя цитируемость, индекс Хирша, работы с 10+ цитированиями, индекс g и дополнительные исследовательские показатели.",
    },
    {
        "id": "analytics",
        "label": "Аналитика",
        "description": "Построены распределения, устойчивость и рейтинг авторов.",
    },
    {
        "id": "export",
        "label": "Экспорт",
        "description": "Результаты доступны через CSV, JSON, Parquet и воспроизводимый report bundle.",
    },
]


def state() -> dict[str, Any]:
    tables = warehouse.list_tables()
    fetch_meta = warehouse.read_json_doc("fetch_meta") or {}
    quality = warehouse.read_json_doc("quality") or {}
    cfg = load_config(ROOT / "config/slice.yaml")
    preview = author_slice.preview(config_to_dict(cfg))

    rows = {name: int(info.get("rows") or 0) for name, info in tables.items()}
    readiness = {
        "slice": bool(cfg.entity_level and cfg.entity_id_short),
        "ingestion": bool(fetch_meta.get("fetched_works") or rows.get("works")),
        "flatten": rows.get("works", 0) > 0 and rows.get("authorships", 0) > 0,
        "indices": rows.get("indices", 0) > 0 and rows.get("ratings", 0) > 0,
        "analytics": rows.get("indices", 0) > 0 and rows.get("ratings", 0) > 0,
        "export": rows.get("ratings", 0) > 0,
    }
    stages = [
        {
            **stage,
            "status": "ready" if readiness[stage["id"]] else "pending",
            "ready": readiness[stage["id"]],
        }
        for stage in STAGE_DEFINITIONS
    ]
    active = next((stage for stage in stages if not stage["ready"]), stages[-1])
    quality_counts = quality.get("quality_counts") or {}
    return {
        "active_stage": active["id"],
        "stages": stages,
        "current_slice": preview["slice"],
        "request": preview["request"],
        "calculation": preview["calculation"],
        "source": fetch_meta.get("source_type") or preview["source"]["id"],
        "quality_summary": {
            "quality_flags": sum(int(value or 0) for value in quality_counts.values()),
            "authors": rows.get("indices", 0),
            "works": rows.get("works", 0),
            "authorships": rows.get("authorships", 0),
            "authors_indexed": rows.get("indices", 0),
        },
        "next_action": _next_action(active["id"]),
        "modes": {
            "strict_works": "Основной исследовательский контур: Works/Authorships и локальные индексы.",
        },
    }


def _next_action(stage_id: str) -> str:
    return {
        "slice": "Выберите тему OpenAlex и страну автора.",
        "ingestion": "Выберите уже скачанный локальный срез или запустите явную загрузку среза OpenAlex.",
        "flatten": "Постройте локальные таблицы из выбранного среза или импортируйте локальный JSONL.",
        "indices": "Пересчитайте индексы после локального импорта данных.",
        "analytics": "Пересчитайте аналитику и проверьте распределение.",
        "export": "Экспортируйте текущий рейтинг, паспорта и пакет отчета.",
    }.get(stage_id, "Рабочий процесс завершён.")
