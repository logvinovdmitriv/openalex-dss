from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ScopeQuery(BaseModel):
    run_id: str = ""
    dump_id: str = ""


class AnalysisFilterQuery(BaseModel):
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
    min_cited_by_count: int = Field(default=0, ge=0)
    from_publication_date: str = ""
    to_publication_date: str = ""
    work_type: str = ""
    q: str = ""


class DataSelectionQuery(BaseModel):
    data_filters: str = ""
    data_search: str = ""
    data_sort: str = ""
    data_direction: Literal["asc", "desc"] = "desc"
    data_limit: int = Field(default=0, ge=0, le=500_000)


class ScientometricQuery(BaseModel):
    fraction_mode: str = "strict_authors_count"
    metrics: str = ""
    baseline_metric: str = "h"
    top_n: int = Field(default=100, ge=0, le=1000)
