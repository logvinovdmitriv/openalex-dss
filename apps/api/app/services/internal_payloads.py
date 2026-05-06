from __future__ import annotations

from pydantic import ConfigDict, Field, field_validator

from app.schemas.slice_payloads import SliceDefinitionPayload


class InternalPipelinePayload(SliceDefinitionPayload):
    model_config = ConfigDict(extra="ignore")

    slice_name: str | None = None
    workflow_mode: str | None = None
    sort: str | None = None
    per_page: int | None = Field(default=None, ge=1, le=100)
    raw_openalex_filter: str | None = None
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
    accepted_estimate_signature: str | None = None
    accepted_download_signature: str | None = None

    @field_validator("workflow_mode")
    @classmethod
    def validate_workflow_mode(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in {"strict_works"}:
            raise ValueError("workflow_mode must be strict_works")
        return value
