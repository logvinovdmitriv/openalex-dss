from __future__ import annotations

WORK_TYPE_LABELS = {
    "article": "Статья",
    "review": "Обзор",
    "conference-paper": "Материалы конференции",
    "book": "Книга",
    "book-chapter": "Глава книги",
    "book-section": "Раздел книги",
    "preprint": "Препринт",
    "dissertation": "Диссертация",
    "report": "Отчет",
    "report-component": "Раздел отчета",
    "dataset": "Набор данных",
    "database": "База данных",
    "software": "Программное обеспечение",
    "standard": "Стандарт",
    "editorial": "Редакционная статья",
    "erratum": "Исправление",
    "letter": "Письмо в редакцию",
    "peer-review": "Рецензия",
    "reference-entry": "Справочная статья",
    "retraction": "Сообщение об отзыве",
    "paratext": "Служебный текст",
    "other": "Другое",
    "libguides": "Библиотечный путеводитель",
    "supplementary-materials": "Дополнительные материалы",
    "grant": "Грант",
}


def work_type_label(value: str) -> str:
    code = str(value or "").strip()
    if not code:
        return ""
    return f"{WORK_TYPE_LABELS.get(code, _humanize_token(code))} ({code})"


def format_work_types(value: str) -> str:
    codes = [part.strip() for part in str(value or "").split("|") if part.strip()]
    if not codes:
        return "Все поддерживаемые типы"
    return ", ".join(work_type_label(code) for code in codes)


def _humanize_token(value: str) -> str:
    return " ".join(part[:1].upper() + part[1:] for part in value.replace("_", "-").split("-") if part)
