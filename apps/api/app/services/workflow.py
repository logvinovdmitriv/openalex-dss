from __future__ import annotations


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
        "description": "JSON приведен к плоским таблицам работ и авторств.",
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

