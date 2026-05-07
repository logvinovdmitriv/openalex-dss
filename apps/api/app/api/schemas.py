from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.slice_payloads import SliceDefinitionPayload


class SliceDefinitionRequest(SliceDefinitionPayload):
    pass


class AnalysisRunRequest(BaseModel):
    dump_id: str = Field(min_length=1)
    fraction_modes: list[str] | None = None
    fraction_mode_default: str | None = None
    lrdi_p0: float | None = None
    lrdi_lambda: float | None = None
    analysis_year: int | None = Field(default=None, ge=1900, le=2100)

    @field_validator("dump_id")
    @classmethod
    def validate_dump_id(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("dump_id is required for public recalculate runs")
        return text


class RunRequest(BaseModel):
    action: Literal["recalculate"] = "recalculate"
    payload: AnalysisRunRequest


class SliceCreateRequest(SliceDefinitionRequest):
    slice_id: str | None = None
    title: str | None = None


class SliceEstimateRequest(BaseModel):
    download_policy: "DownloadPolicy" = Field(default_factory=lambda: DownloadPolicy())


class DownloadPolicy(BaseModel):
    complete_slice_required: bool = True
    allow_incomplete_preview: bool = False


class MaterializationPlanRequest(BaseModel):
    storage_profile_id: str = "minimal_analytics"
    source_strategy: str = "openalex_cli"
    download_policy: DownloadPolicy = Field(default_factory=DownloadPolicy)
    profile_id: str | None = None
    download_dir: str | None = None


class MaterializationRunRequest(BaseModel):
    api_key: str | None = None
    download_dir: str | None = None


class AuthorCohortCreateRequest(BaseModel):
    slice_id: str | None = None
    run_id: str | None = None
    dump_id: str | None = None
    name: str = "Авторская когорта"
    source: Literal["top_n", "manual", "metric_filter"] = "top_n"
    metric: str = "h"
    fraction_mode: str = "strict_authors_count"
    top_n: int | None = Field(default=100, ge=1, le=1000)
    min_publications: int | None = Field(default=None, ge=0)
    min_h: int | None = Field(default=None, ge=0)
    min_metric_value: float | None = Field(default=None, ge=0)
    country_code: str | None = None
    institution_id: str | None = None
    subject_level: str | None = None
    subject_id: str | None = None
    filter_mode: str | None = None
    keyword_id: str | None = None
    keyword_display_name: str | None = None
    text_search_query: str | None = None
    author_id: str | None = None
    author_display_name: str | None = None
    author_orcid: str | None = None
    doi: str | None = None
    affiliation_mode: str | None = None
    source_id: str | None = None
    source_display_name: str | None = None
    source_type: str | None = None
    language: str | None = None
    open_access_is_oa: str | None = None
    has_abstract: str | None = None
    min_cited_by_count: int | None = Field(default=None, ge=0)
    from_publication_date: str | None = None
    to_publication_date: str | None = None
    work_type: str | None = None
    author_ids: list[str] = Field(default_factory=list)
