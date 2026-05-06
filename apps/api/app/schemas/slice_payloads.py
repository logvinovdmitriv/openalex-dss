from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SliceDefinitionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_level: str | None = None
    entity_id_short: str | None = None
    entity_id_full: str | None = None
    entity_display_name: str | None = None
    filter_mode: str | None = None
    keyword_id: str | None = None
    keyword_display_name: str | None = None
    text_search_query: str | None = None
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

    @field_validator("entity_level")
    @classmethod
    def validate_entity_level(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in {"", "field", "subfield", "topic"}:
            raise ValueError("entity_level must be one of: field, subfield, topic")
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
