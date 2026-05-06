from __future__ import annotations

from typing import Any


def build_analysis_filters(
    *,
    country_code: str = "",
    filter_mode: str = "",
    subject_level: str = "",
    subject_id: str = "",
    keyword_id: str = "",
    keyword_display_name: str = "",
    text_search_query: str = "",
    author_id: str = "",
    author_orcid: str = "",
    author_display_name: str = "",
    doi: str = "",
    affiliation_mode: str = "",
    institution_id: str = "",
    source_id: str = "",
    source_display_name: str = "",
    source_type: str = "",
    language: str = "",
    open_access_is_oa: str = "",
    has_abstract: str = "",
    min_cited_by_count: int = 0,
    from_publication_date: str = "",
    to_publication_date: str = "",
    work_type: str = "",
) -> dict[str, str]:
    return clean_analysis_filters(
        {
            "country_code": country_code.strip().upper(),
            "filter_mode": filter_mode.strip(),
            "subject_level": subject_level.strip(),
            "subject_id": subject_id.strip(),
            "keyword_id": keyword_id.strip(),
            "keyword_display_name": keyword_display_name.strip(),
            "text_search_query": text_search_query.strip(),
            "author_id": author_id.strip(),
            "author_orcid": author_orcid.strip(),
            "author_display_name": author_display_name.strip(),
            "doi": doi.strip(),
            "affiliation_mode": affiliation_mode.strip(),
            "institution_id": institution_id.strip(),
            "source_id": source_id.strip(),
            "source_display_name": source_display_name.strip(),
            "source_type": source_type.strip(),
            "language": language.strip(),
            "open_access_is_oa": open_access_is_oa.strip(),
            "has_abstract": has_abstract.strip(),
            "min_cited_by_count": str(min_cited_by_count) if min_cited_by_count else "",
            "from_publication_date": from_publication_date.strip(),
            "to_publication_date": to_publication_date.strip(),
            "work_type": work_type.strip(),
        }
    )


def clean_analysis_filters(filters: dict[str, Any]) -> dict[str, str]:
    return {key: str(value).strip() for key, value in sorted(filters.items()) if str(value or "").strip()}
