from __future__ import annotations

import re
import sys
from typing import Any

from app.core.paths import ROOT, SRC

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_mvp.config import SliceConfig, load_config, replace_config  # noqa: E402
from openalex_mvp.openalex import build_filter, default_sort  # noqa: E402


SUBJECT_LEVELS = {"field", "subfield", "topic"}
FILTER_MODES = {"all", "primary_topic", "topics_any", "keyword", "search"}
WORKFLOW_MODES = {"strict_works"}
FRACTION_MODES = {"strict_authors_count", "renorm_valid_authors", "integer"}
WORK_TYPE_RE = re.compile(r"^[a-z0-9-]+$")
SOURCE_TYPE_RE = re.compile(r"^[a-z0-9-]+$")
LANGUAGE_RE = re.compile(r"^[a-z]{2,3}$")
SORT_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+:(asc|desc)$")
DEFAULT_SORT = default_sort()
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def config_from_payload(payload: dict[str, Any]) -> SliceConfig:
    cfg = load_config(ROOT / "config/slice.yaml")
    updates = _clean_updates(payload, base=cfg)
    return replace_config(cfg, **updates)


def preview(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = config_from_payload(payload)
    return {
        "source": {
            "id": "openalex_api",
            "label": "OpenAlex API",
            "description": "Разрешение ID и создание фиксированного OpenAlex Works JSONL-дампа; расчет индексов выполняется локально.",
        },
        "slice": {
            "subject_level": cfg.entity_level,
            "subject_id": cfg.entity_id_short,
            "subject_name": cfg.entity_display_name,
            "subject_openalex_id": cfg.entity_id_full,
            "country_code": cfg.country_code,
            "filter_mode": cfg.filter_mode,
            "keyword_id": cfg.keyword_id,
            "keyword_name": cfg.keyword_display_name,
            "text_search_query": cfg.text_search_query,
            "author_id": cfg.author_id,
            "author_name": cfg.author_display_name,
            "author_orcid": cfg.author_orcid,
            "institution_id": cfg.institution_id,
            "institution_name": cfg.institution_display_name,
            "institution_ror": cfg.institution_ror,
            "source_id": cfg.source_id,
            "source_name": cfg.source_display_name,
            "source_type": cfg.source_type,
            "language": cfg.language,
            "open_access_is_oa": cfg.open_access_is_oa,
            "has_abstract": cfg.has_abstract,
            "min_cited_by_count": cfg.min_cited_by_count,
            "doi": cfg.doi,
            "affiliation_mode": cfg.affiliation_mode,
        },
        "request": {
            "filter": build_filter(cfg),
            "sort": cfg.sort,
            "per_page": cfg.per_page,
            "select_fields": list(cfg.select_fields),
        },
        "calculation": {
            "fraction_modes": list(cfg.fraction_modes),
            "default_fraction_mode": cfg.fraction_mode_default,
            "core_indices": ["p", "c", "c_frac", "cpp", "h", "i10", "g", "m_local"],
            "experimental_indices": ["f5", "fm5", "iupv", "islv", "lrdi"],
            "iupv": {
                "formula": "100 * (pr(P) * pr(h) * pr(C_frac)) ** (1/3)",
                "percentile_scope": "current slice and fraction mode",
            },
            "islv": {
                "formula": "weighted geometric mean of pr(h), pr(C_frac), pr(g), pr(i10), pr(P) with top-1 concentration penalty",
                "status": "own_formula_mvp_v1",
            },
            "f5_fm5_status": "operational_definition_requires_primary_source_confirmation",
            "lrdi_p0": cfg.lrdi_p0,
            "lrdi_lambda": cfg.lrdi_lambda,
            "analysis_year": cfg.analysis_year,
        },
        "policy": {
            "author_metrics_from_works_only": True,
            "api_usage": "API используется для подсказок/ID, компактного дампа и точечного обогащения; рейтинги считаются из локального dump/import слоя.",
            "unsupported_filters": [
                {
                    "name": "Пол автора",
                    "reason": "OpenAlex не предоставляет это поле в стандартных данных.",
                },
                {
                    "name": "Возраст автора",
                    "reason": "OpenAlex не предоставляет это поле в стандартных данных.",
                },
            ],
        },
    }


def _clean_updates(payload: dict[str, Any], *, base: SliceConfig) -> dict[str, Any]:
    updates = {key: value for key, value in payload.items() if key not in {"api_key", "source_path"} and value is not None}

    workflow_mode = str(updates.get("workflow_mode") or base.workflow_mode or "strict_works").strip()
    if workflow_mode not in WORKFLOW_MODES:
        raise ValueError("workflow_mode must be strict_works")
    updates["workflow_mode"] = workflow_mode

    level = str(updates.get("entity_level") or base.entity_level).strip()
    subject_id = str(updates.get("entity_id_short") or base.entity_id_short).strip()
    subject_name = str(updates.get("entity_display_name") or base.entity_display_name).strip() or subject_id
    filter_mode = str(updates.get("filter_mode") or base.filter_mode or "primary_topic").strip()
    if filter_mode not in FILTER_MODES:
        raise ValueError("filter_mode must be one of: all, primary_topic, topics_any, keyword, search")
    updates["filter_mode"] = filter_mode
    if filter_mode == "all":
        level = ""
        subject_id = ""
        subject_name = ""
    else:
        if level not in SUBJECT_LEVELS:
            raise ValueError("entity_level must be one of: field, subfield, topic")
        _validate_subject_id(level, subject_id)

    updates["entity_level"] = level
    updates["entity_id_short"] = subject_id
    updates["entity_display_name"] = subject_name
    updates["entity_id_full"] = str(updates.get("entity_id_full") or _openalex_entity_url(level, subject_id)).strip()
    if filter_mode == "keyword" and not str(_update_value(updates, "keyword_id", base.keyword_id)).strip():
        raise ValueError("keyword_id is required for keyword mode")
    if filter_mode == "search" and not str(_update_value(updates, "text_search_query", base.text_search_query)).strip():
        raise ValueError("text_search_query is required for search mode")
    updates["keyword_id"] = str(_update_value(updates, "keyword_id", base.keyword_id)).strip()
    updates["keyword_display_name"] = str(_update_value(updates, "keyword_display_name", base.keyword_display_name)).strip()
    updates["text_search_query"] = str(_update_value(updates, "text_search_query", base.text_search_query)).strip()
    updates["raw_openalex_filter"] = str(_update_value(updates, "raw_openalex_filter", base.raw_openalex_filter)).strip()
    updates["author_id"] = _clean_openalex_id(str(_update_value(updates, "author_id", base.author_id)).strip(), prefix="A")
    updates["author_display_name"] = str(_update_value(updates, "author_display_name", base.author_display_name)).strip()
    updates["author_orcid"] = _clean_orcid(str(_update_value(updates, "author_orcid", base.author_orcid)).strip())

    country_code = str(updates.get("country_code") or "").strip().upper()
    if country_code and not COUNTRY_RE.match(country_code):
        raise ValueError("country_code must be an ISO-3166 two-letter code, for example RU or US")
    updates["country_code"] = country_code
    updates["institution_id"] = _clean_openalex_id(str(_update_value(updates, "institution_id", base.institution_id)).strip(), prefix="I")
    updates["institution_display_name"] = str(_update_value(updates, "institution_display_name", base.institution_display_name)).strip()
    updates["institution_ror"] = _clean_ror(str(_update_value(updates, "institution_ror", base.institution_ror)).strip())
    updates["source_id"] = _clean_openalex_id(str(_update_value(updates, "source_id", base.source_id)).strip(), prefix="S")
    updates["source_display_name"] = str(_update_value(updates, "source_display_name", base.source_display_name)).strip()
    updates["source_type"] = _clean_token(str(_update_value(updates, "source_type", base.source_type)).strip(), SOURCE_TYPE_RE, "source_type")
    updates["language"] = _clean_token(str(_update_value(updates, "language", base.language)).strip().lower(), LANGUAGE_RE, "language")
    updates["open_access_is_oa"] = _clean_optional_bool(str(_update_value(updates, "open_access_is_oa", base.open_access_is_oa)).strip())
    updates["has_abstract"] = _clean_optional_bool(str(_update_value(updates, "has_abstract", base.has_abstract)).strip())
    updates["min_cited_by_count"] = max(0, int(_update_value(updates, "min_cited_by_count", base.min_cited_by_count) or 0))
    updates["doi"] = str(_update_value(updates, "doi", base.doi)).strip()
    affiliation_mode = str(updates.get("affiliation_mode") or base.affiliation_mode or "historical").strip()
    if affiliation_mode not in {"current", "historical"}:
        raise ValueError("affiliation_mode must be current or historical")
    updates["affiliation_mode"] = affiliation_mode

    sort = str(updates.get("sort") or DEFAULT_SORT).strip()
    if not _is_openalex_sort(sort):
        raise ValueError("sort must use OpenAlex format field:asc or field:desc, comma-separated")
    updates["sort"] = sort

    updates["per_page"] = max(1, min(int(updates.get("per_page") or base.per_page or 100), 100))

    fraction_modes = _clean_fraction_modes(updates.get("fraction_modes") or base.fraction_modes)
    default_mode = str(updates.get("fraction_mode_default") or base.fraction_mode_default).strip()
    if default_mode not in fraction_modes:
        default_mode = fraction_modes[0]
    updates["fraction_modes"] = ",".join(fraction_modes)
    updates["fraction_mode_default"] = default_mode

    updates["from_publication_date"] = _clean_date(_update_value(updates, "from_publication_date", base.from_publication_date))
    updates["to_publication_date"] = _clean_date(_update_value(updates, "to_publication_date", base.to_publication_date))
    work_type = str(_update_value(updates, "work_type", base.work_type)).strip()
    requested_types = [part.strip() for part in work_type.split("|") if part.strip()]
    unsupported_types = [part for part in requested_types if not WORK_TYPE_RE.match(part)]
    if unsupported_types:
        raise ValueError("Типы публикаций должны быть OpenAlex type-токенами вида article, review или article|review")
    updates["work_type"] = work_type
    updates["slice_name"] = _safe_slice_name(
        str(updates.get("slice_name") or "").strip()
        or _default_slice_name(level, subject_id, country_code, updates["from_publication_date"], updates["to_publication_date"], filter_mode, work_type)
    )
    updates["exclude_retracted"] = True
    updates["exclude_paratext"] = True
    updates["include_xpac"] = False
    updates["lrdi_p0"] = float(updates.get("lrdi_p0") or base.lrdi_p0 or 5.0)
    updates["lrdi_lambda"] = float(updates.get("lrdi_lambda") or base.lrdi_lambda or 0.15)
    updates["analysis_year"] = int(updates.get("analysis_year") or base.analysis_year or 2026)

    return updates


def _clean_fraction_modes(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw = [part.strip() for part in value.split(",")]
    else:
        raw = [str(part).strip() for part in value]
    modes = tuple(mode for mode in raw if mode in FRACTION_MODES)
    if not modes:
        raise ValueError("At least one supported fraction mode is required")
    return modes


def _update_value(updates: dict[str, Any], key: str, fallback: Any) -> Any:
    return updates[key] if key in updates else fallback


def _is_openalex_sort(value: str) -> bool:
    parts = [part.strip() for part in str(value or "").split(",") if part.strip()]
    return bool(parts) and all(SORT_PART_RE.match(part) for part in parts)


def _validate_subject_id(level: str, subject_id: str) -> None:
    if not subject_id:
        raise ValueError("entity_id_short is required")
    if level == "topic" and not re.match(r"^T\d+$", subject_id):
        raise ValueError("OpenAlex topic IDs must look like T11572")
    if level in {"field", "subfield"} and not re.match(r"^\d+$", subject_id):
        raise ValueError(f"OpenAlex {level} IDs must be numeric")


def _openalex_entity_url(level: str, subject_id: str) -> str:
    if not level or not subject_id:
        return ""
    if level == "topic":
        return f"https://openalex.org/{subject_id}"
    return f"https://openalex.org/{level}s/{subject_id}"


def _clean_openalex_id(value: str, *, prefix: str | None = None) -> str:
    text = value.strip()
    if not text:
        return ""
    if "|" in text or "," in text:
        return _clean_openalex_id_list(text, prefix=prefix)
    if text.startswith("https://openalex.org/"):
        return text
    if re.match(r"^[A-Z]\d+$", text) and (prefix is None or text.startswith(prefix)):
        return f"https://openalex.org/{text}"
    return text


def _clean_openalex_id_list(value: str, *, prefix: str | None = None) -> str:
    parts = [part.strip() for part in value.replace(",", "|").split("|") if part.strip()]
    cleaned = [_clean_openalex_id(part, prefix=prefix) for part in parts]
    return "|".join(item for item in cleaned if item)


def _clean_orcid(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    return text.replace("https://orcid.org/", "").replace("http://orcid.org/", "")


def _clean_ror(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if text.startswith("https://ror.org/"):
        return text
    if re.match(r"^[0-9a-z]{9}$", text, re.IGNORECASE):
        return f"https://ror.org/{text}"
    return text


def _clean_token(value: str, pattern: re.Pattern[str], field_name: str) -> str:
    if not value:
        return ""
    if not pattern.match(value):
        raise ValueError(f"{field_name} has unsupported format")
    return value


def _clean_optional_bool(value: str) -> str:
    text = value.strip().lower()
    if not text:
        return ""
    if text not in {"true", "false"}:
        raise ValueError("Boolean OpenAlex filters must be true or false")
    return text


def _clean_date(value: Any) -> str:
    text = str(value or "").strip()
    if text and not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        raise ValueError("Dates must use YYYY-MM-DD format")
    return text


def _default_slice_name(level: str, subject_id: str, country_code: str, from_date: str, to_date: str, filter_mode: str, work_type: str) -> str:
    parts = [
        level,
        subject_id,
        country_code.lower() or "all",
        from_date[:4] or "all",
        to_date[:4] or "all",
        filter_mode,
        work_type.replace("|", "_"),
        "v1",
    ]
    return "_".join(part for part in parts if part)


def _safe_slice_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    text = re.sub(r"_+", "_", text).strip("._-")
    return text[:120] or "openalex_slice_v1"
