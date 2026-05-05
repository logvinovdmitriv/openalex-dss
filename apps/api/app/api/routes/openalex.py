from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.services import openalex_catalog


router = APIRouter(tags=["openalex"])


@router.get("/openalex/subjects")
def search_subjects(q: str = Query("", min_length=0), limit: int = Query(8, ge=1, le=12)) -> dict[str, Any]:
    return openalex_catalog.search_subjects(q, limit=limit)


@router.get("/openalex/catalog/status")
def catalog_status() -> dict[str, Any]:
    return openalex_catalog.catalog_status()


@router.post("/openalex/catalog/sync-subjects")
def sync_subjects(include_topics: bool = True, max_topics: int = Query(50_000, ge=0, le=250_000)) -> dict[str, Any]:
    return openalex_catalog.sync_subject_catalog(include_topics=include_topics, max_topics=max_topics)


@router.post("/openalex/catalog/sync-supported-values")
def sync_supported_values() -> dict[str, Any]:
    return openalex_catalog.sync_group_catalogs()


@router.get("/openalex/keywords")
def search_keywords(q: str = Query("", min_length=0), limit: int = Query(8, ge=1, le=12)) -> dict[str, Any]:
    return openalex_catalog.search_keywords(q, limit=limit)


@router.get("/openalex/institutions")
def search_institutions(q: str = Query("", min_length=0), limit: int = Query(8, ge=1, le=12)) -> dict[str, Any]:
    return openalex_catalog.search_institutions(q, limit=limit)


@router.get("/openalex/authors")
def search_authors(q: str = Query("", min_length=0), limit: int = Query(8, ge=1, le=12)) -> dict[str, Any]:
    return openalex_catalog.search_authors(q, limit=limit)


@router.get("/openalex/works")
def search_works(q: str = Query("", min_length=0), limit: int = Query(8, ge=1, le=12)) -> dict[str, Any]:
    return openalex_catalog.search_works(q, limit=limit)


@router.get("/openalex/sources")
def search_sources(q: str = Query("", min_length=0), limit: int = Query(8, ge=1, le=12)) -> dict[str, Any]:
    return openalex_catalog.search_sources(q, limit=limit)


@router.get("/openalex/countries")
def search_countries(q: str = Query("", min_length=0), limit: int = Query(12, ge=1, le=50)) -> dict[str, Any]:
    return openalex_catalog.search_countries(q, limit=limit)


@router.get("/openalex/work-types")
def work_types(limit: int = Query(50, ge=1, le=50)) -> dict[str, Any]:
    return openalex_catalog.work_types(limit=limit)


@router.get("/openalex/languages")
def languages(q: str = Query("", min_length=0), limit: int = Query(30, ge=1, le=50)) -> dict[str, Any]:
    return openalex_catalog.languages(q, limit=limit)


@router.get("/openalex/source-types")
def source_types(limit: int = Query(30, ge=1, le=50)) -> dict[str, Any]:
    return openalex_catalog.source_types(limit=limit)
