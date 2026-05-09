from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.analysis_filters import build_analysis_filters


@dataclass(frozen=True)
class ScopeQuery:
    run_id: str = ""
    dump_id: str = ""
    cohort_id: str = ""

    @property
    def has_direct_scope(self) -> bool:
        return bool(self.run_id.strip() or self.dump_id.strip())


@dataclass(frozen=True)
class AnalysisFilterQuery:
    country_code: str = ""
    filter_mode: str = ""
    subject_level: str = ""
    subject_id: str = ""
    keyword_id: str = ""
    keyword_display_name: str = ""
    text_search_query: str = ""
    author_id: str = ""
    author_orcid: str = ""
    author_display_name: str = ""
    doi: str = ""
    affiliation_mode: str = ""
    institution_id: str = ""
    source_id: str = ""
    source_display_name: str = ""
    source_type: str = ""
    language: str = ""
    open_access_is_oa: str = ""
    has_abstract: str = ""
    min_cited_by_count: int = 0
    from_publication_date: str = ""
    to_publication_date: str = ""
    work_type: str = ""
    q: str = ""

    def to_filters(self) -> dict[str, str]:
        return build_analysis_filters(
            country_code=self.country_code,
            filter_mode=self.filter_mode,
            subject_level=self.subject_level,
            subject_id=self.subject_id,
            keyword_id=self.keyword_id,
            keyword_display_name=self.keyword_display_name,
            text_search_query=self.text_search_query,
            author_id=self.author_id,
            author_orcid=self.author_orcid,
            author_display_name=self.author_display_name,
            doi=self.doi,
            affiliation_mode=self.affiliation_mode,
            institution_id=self.institution_id,
            source_id=self.source_id,
            source_display_name=self.source_display_name,
            source_type=self.source_type,
            language=self.language,
            open_access_is_oa=self.open_access_is_oa,
            has_abstract=self.has_abstract,
            min_cited_by_count=self.min_cited_by_count,
            from_publication_date=self.from_publication_date,
            to_publication_date=self.to_publication_date,
            work_type=self.work_type,
            q=self.q,
        )


@dataclass(frozen=True)
class DataSelectionQuery:
    data_filters: dict[str, Any]
    data_search: str = ""
    data_sort: str = ""
    data_direction: str = "desc"
    data_limit: int = 0
    max_limit: int = 500_000

    def to_kwargs(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.data_filters:
            out["data_filters"] = self.data_filters
        if self.data_search.strip():
            out["data_search"] = self.data_search.strip()
        if self.data_sort.strip():
            out["data_sort"] = self.data_sort.strip()
            out["data_direction"] = "asc" if self.data_direction.strip().lower() == "asc" else "desc"
        limit = _int_value(self.data_limit, 0)
        if limit > 0:
            out["data_limit"] = max(1, min(limit, self.max_limit))
        return out


@dataclass(frozen=True)
class ScientometricQuery:
    fraction_mode: str = "strict_authors_count"
    metrics: list[str] | None = None
    baseline_metric: str = "h"
    top_n: int = 100


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

