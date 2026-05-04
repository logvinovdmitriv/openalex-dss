from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PipelineRequest(BaseModel):
    slice_name: str | None = None
    workflow_mode: str | None = None
    entity_level: str | None = None
    entity_id_short: str | None = None
    entity_id_full: str | None = None
    entity_display_name: str | None = None
    filter_mode: str | None = None
    keyword_id: str | None = None
    keyword_display_name: str | None = None
    text_search_query: str | None = None
    raw_openalex_filter: str | None = None
    author_id: str | None = None
    author_display_name: str | None = None
    author_orcid: str | None = None
    institution_id: str | None = None
    institution_display_name: str | None = None
    institution_ror: str | None = None
    source_id: str | None = None
    source_display_name: str | None = None
    source_type: str | None = None
    language: str | None = None
    open_access_is_oa: str | None = None
    has_abstract: str | None = None
    min_cited_by_count: int | None = Field(default=None, ge=0)
    doi: str | None = None
    affiliation_mode: str | None = None
    from_publication_date: str | None = None
    to_publication_date: str | None = None
    work_type: str | None = None
    include_xpac: bool | None = None
    exclude_retracted: bool | None = None
    exclude_paratext: bool | None = None
    country_code: str | None = None
    sort: str | None = None
    max_works: int | None = Field(default=None, ge=1, le=100_000)
    max_dump_bytes: int | None = Field(default=None, ge=1024, le=5 * 1024 * 1024 * 1024)
    per_page: int | None = Field(default=None, ge=1, le=100)
    fraction_modes: list[str] | None = None
    fraction_mode_default: str | None = None
    iupv_n0: float | None = None
    iupv_lambda: float | None = None
    lrdi_p0: float | None = None
    lrdi_lambda: float | None = None
    analysis_year: int | None = Field(default=None, ge=1900, le=2100)
    api_key: str | None = None
    source_path: str | None = None
    source_strategy: str | None = None

    @field_validator("entity_level")
    @classmethod
    def validate_entity_level(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in {"", "field", "subfield", "topic"}:
            raise ValueError("entity_level must be one of: field, subfield, topic")
        return value

    @field_validator("workflow_mode")
    @classmethod
    def validate_workflow_mode(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in {"strict_works", "author_preview"}:
            raise ValueError("workflow_mode must be strict_works or author_preview")
        return value

    @field_validator("filter_mode")
    @classmethod
    def validate_filter_mode(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in {"all", "primary_topic", "topics_any", "keyword", "search"}:
            raise ValueError("filter_mode must be all, primary_topic, topics_any, keyword, or search")
        return value

    @field_validator("affiliation_mode")
    @classmethod
    def validate_affiliation_mode(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in {"current", "historical"}:
            raise ValueError("affiliation_mode must be current or historical")
        return value

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str | None) -> str | None:
        if value is None:
            return value
        text = value.strip().upper()
        if text and len(text) != 2:
            raise ValueError("country_code must be a two-letter ISO code")
        return text


class RunRequest(BaseModel):
    action: Literal[
        "plan",
        "fetch_slice_dump",
        "build_from_openalex",
        "import_file",
        "recalculate",
        "author_preview",
    ] = "build_from_openalex"
    payload: PipelineRequest = Field(default_factory=PipelineRequest)


class SliceCreateRequest(PipelineRequest):
    slice_id: str | None = None
    title: str | None = None


class SliceEstimateRequest(BaseModel):
    download_policy: "DownloadPolicy" = Field(default_factory=lambda: DownloadPolicy())
    max_dump_bytes: int | None = Field(default=None, ge=1024, le=5 * 1024 * 1024 * 1024)


class DownloadPolicy(BaseModel):
    max_records_to_download: int | None = Field(default=None, ge=1, le=500_000)
    max_raw_bytes: int | None = Field(default=None, ge=1024, le=5 * 1024 * 1024 * 1024)
    complete_slice_required: bool = True
    allow_incomplete_preview: bool = False


class MaterializationPlanRequest(BaseModel):
    storage_profile_id: str = "minimal_analytics"
    source_strategy: str = "openalex_api"
    download_policy: DownloadPolicy = Field(default_factory=DownloadPolicy)
    profile_id: str | None = None
    max_dump_bytes: int | None = Field(default=None, ge=1024, le=5 * 1024 * 1024 * 1024)


class MaterializationRunRequest(BaseModel):
    api_key: str | None = None


class AuthorCohortCreateRequest(BaseModel):
    slice_id: str | None = None
    name: str = "Авторская когорта"
    source: Literal["top_n", "manual", "metric_filter"] = "top_n"
    metric: str = "h"
    fraction_mode: str = "strict_authors_count"
    top_n: int | None = Field(default=100, ge=1, le=1000)
    min_publications: int | None = Field(default=None, ge=0)
    min_h: int | None = Field(default=None, ge=0)
    country_code: str | None = None
    institution_id: str | None = None
    subject_level: str | None = None
    subject_id: str | None = None
    filter_mode: str | None = None
    author_ids: list[str] = Field(default_factory=list)
