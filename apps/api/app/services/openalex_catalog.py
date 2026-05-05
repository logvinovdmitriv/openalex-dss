from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from typing import Any

from app.services import metadata_store, registry


OPENALEX_BASE = "https://api.openalex.org"


def catalog_status() -> dict[str, Any]:
    status = metadata_store.catalog_status()
    return {
        "metadata_db": status,
        "subjects": _entity_status(status, "subject"),
        "keywords": _entity_status(status, "keyword"),
        "institutions": _entity_status(status, "institution"),
        "authors": _entity_status(status, "author"),
        "works": _entity_status(status, "work"),
        "sources": _entity_status(status, "source"),
        "work_types": _entity_status(status, "work_type"),
        "countries": _entity_status(status, "country"),
        "languages": _entity_status(status, "language"),
        "source_types": _entity_status(status, "source_type"),
    }


def search_subjects(q: str, *, limit: int = 8) -> dict[str, Any]:
    query = q.strip()
    limit = _limit(limit)
    results: list[dict[str, Any]] = []
    errors: list[str] = []

    if len(query) < 2:
        _add_unique(results, [_subject_alias_result(item) for item in registry.registry().get("domain_presets", [])[:limit]], limit)
        _add_unique(results, _subject_db_results(metadata_store.list_entities("subject", limit=limit)), limit)
        return {"results": results[:limit], "cache": catalog_status()["subjects"]}
    _add_unique(results, [_subject_alias_result(item) for item in registry.find_domain_aliases(query, limit)], limit)

    _add_unique(results, _subject_db_results(metadata_store.search_entities("subject", query, limit=limit)), limit)
    if len(results) >= limit:
        return {"results": results[:limit], "cache": catalog_status()["subjects"]}

    for level, entity in (("field", "fields"), ("subfield", "subfields"), ("topic", "topics")):
        try:
            direct = _lookup_subject_by_id(query, level, entity)
            if direct:
                metadata_store.upsert_entities("subject", [direct], source="openalex_lookup")
                _add_unique(results, [_subject_result(direct)], limit)
        except RuntimeError as exc:
            errors.append(str(exc))
        if len(results) >= limit:
            break
        try:
            payload = _get_cached(entity, query, limit)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        api_items = [_subject_catalog_item(item, level) for item in payload.get("results", [])]
        metadata_store.upsert_entities("subject", api_items, source="openalex_search")
        _add_unique(results, [_subject_result(item) for item in api_items], limit)
        if len(results) >= limit:
            break
    return {"results": results[:limit], "errors": errors, "cache": catalog_status()["subjects"]}


def sync_subject_catalog(*, include_topics: bool = True, max_topics: int = 50_000) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    items.extend(_download_subject_entity("fields", "field", "id,display_name,works_count"))
    items.extend(_download_subject_entity("subfields", "subfield", "id,display_name,field,works_count"))
    if include_topics:
        items.extend(_download_subject_entity("topics", "topic", "id,display_name,subfield,field,works_count", max_records=max_topics))
    inserted = metadata_store.upsert_entities("subject", items, source="openalex_bulk_sync")
    counts = {
        "all": len(items),
        "fields": sum(1 for item in items if item["level"] == "field"),
        "subfields": sum(1 for item in items if item["level"] == "subfield"),
        "topics": sum(1 for item in items if item["level"] == "topic"),
    }
    return {"status": "ok", "inserted": inserted, "subjects": catalog_status()["subjects"], "counts": counts}


def search_keywords(q: str, *, limit: int = 8) -> dict[str, Any]:
    return _search_named_entity("keywords", q, limit=limit, entity_type="keyword", level_label="Ключевое слово")


def search_institutions(q: str, *, limit: int = 8) -> dict[str, Any]:
    query = q.strip()
    limit = _limit(limit)
    if len(query) < 2:
        return {"results": _generic_results(metadata_store.list_entities("institution", limit=limit))}

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    direct = [*_lookup_institution_by_ror(query), *_lookup_single_by_openalex_id("institutions", "I", query, level="institution", level_label="Организация")]
    if direct:
        metadata_store.upsert_entities("institution", direct, source="openalex_lookup")
        _add_unique(results, direct, limit)
    _add_unique(results, [_organization_alias_result(item) for item in registry.find_organization_aliases(query, limit)], limit)
    _add_unique(results, _generic_results(metadata_store.search_entities("institution", query, limit=limit)), limit)

    if len(results) < limit:
        try:
            payload = _get_cached("institutions", query, limit)
        except RuntimeError as exc:
            errors.append(str(exc))
        else:
            api_items = [_institution_result(item) for item in payload.get("results", [])]
            metadata_store.upsert_entities("institution", api_items, source="openalex_search")
            _add_unique(results, api_items, limit)
    return {"results": results[:limit], "errors": errors, "cache": catalog_status()["institutions"]}


def search_authors(q: str, *, limit: int = 8) -> dict[str, Any]:
    query = q.strip()
    limit = _limit(limit)
    if len(query) < 2:
        return {"results": _generic_results(metadata_store.list_entities("author", limit=limit))}

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    direct = [*_lookup_author_by_orcid(query), *_lookup_single_by_openalex_id("authors", "A", query, level="author", level_label="Автор")]
    if direct:
        metadata_store.upsert_entities("author", direct, source="openalex_lookup")
        _add_unique(results, direct, limit)
    _add_unique(results, _generic_results(metadata_store.search_entities("author", query, limit=limit)), limit)

    if len(results) < limit:
        try:
            payload = _get_cached("authors", query, limit)
        except RuntimeError as exc:
            errors.append(str(exc))
        else:
            api_items = [_author_result(item) for item in payload.get("results", [])]
            metadata_store.upsert_entities("author", api_items, source="openalex_search")
            _add_unique(results, api_items, limit)
    return {"results": results[:limit], "errors": errors, "cache": catalog_status()["authors"]}


def search_works(q: str, *, limit: int = 8) -> dict[str, Any]:
    query = q.strip()
    limit = _limit(limit)
    if len(query) < 2:
        return {"results": _generic_results(metadata_store.list_entities("work", limit=limit))}

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    direct = [*_lookup_work_by_doi(query), *_lookup_single_by_openalex_id("works", "W", query, level="work", level_label="Работа")]
    if direct:
        metadata_store.upsert_entities("work", direct, source="openalex_lookup")
        _add_unique(results, direct, limit)
    _add_unique(results, _generic_results(metadata_store.search_entities("work", query, limit=limit)), limit)

    if len(results) < limit:
        try:
            payload = _get_cached("works", query, limit)
        except RuntimeError as exc:
            errors.append(str(exc))
        else:
            api_items = [_work_result(item) for item in payload.get("results", [])]
            metadata_store.upsert_entities("work", api_items, source="openalex_search")
            _add_unique(results, api_items, limit)
    return {"results": results[:limit], "errors": errors, "cache": catalog_status()["works"]}


def search_sources(q: str, *, limit: int = 8) -> dict[str, Any]:
    query = q.strip()
    limit = _limit(limit)
    if len(query) < 2:
        return {"results": _generic_results(metadata_store.list_entities("source", limit=limit))}

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    direct = _lookup_single_by_openalex_id("sources", "S", query, level="source", level_label="Источник")
    if direct:
        metadata_store.upsert_entities("source", direct, source="openalex_lookup")
        _add_unique(results, direct, limit)
    _add_unique(results, _generic_results(metadata_store.search_entities("source", query, limit=limit)), limit)

    if len(results) < limit:
        try:
            payload = _get_cached("sources", query, limit)
        except RuntimeError as exc:
            errors.append(str(exc))
        else:
            api_items = [_source_result(item) for item in payload.get("results", [])]
            metadata_store.upsert_entities("source", api_items, source="openalex_search")
            _add_unique(results, api_items, limit)
    return {"results": results[:limit], "errors": errors, "cache": catalog_status()["sources"]}


def search_countries(q: str = "", *, limit: int = 12) -> dict[str, Any]:
    _ensure_country_catalog()
    payload = _search_group_catalog("country", q, limit=limit)
    query = q.strip()
    if len(query) >= 2 and len(payload.get("results", [])) < _limit(limit):
        try:
            api_payload = _get("countries", {"search": query, "per_page": str(_limit(limit)), "select": "id,display_name,country_code,works_count"})
        except RuntimeError:
            return payload
        api_items = [_country_result(item) for item in api_payload.get("results", [])]
        metadata_store.upsert_entities("country", api_items, source="openalex_search")
        results = payload.get("results", [])
        _add_unique(results, api_items, _limit(limit))
        payload["results"] = results[:_limit(limit)]
        payload["cache"] = catalog_status()["countries"]
    return payload


def work_types(*, limit: int = 50) -> dict[str, Any]:
    _ensure_group_catalog("work_type", "type")
    return {"results": _generic_results(metadata_store.list_entities("work_type", limit=limit)), "cache": catalog_status()["work_types"]}


def languages(q: str = "", *, limit: int = 30) -> dict[str, Any]:
    _ensure_group_catalog("language", "language")
    return _search_group_catalog("language", q, limit=limit)


def source_types(*, limit: int = 30) -> dict[str, Any]:
    _ensure_group_catalog("source_type", "primary_location.source.type")
    return {"results": _generic_results(metadata_store.list_entities("source_type", limit=limit)), "cache": catalog_status()["source_types"]}


def sync_group_catalogs() -> dict[str, Any]:
    return {
        "status": "ok",
        "countries": _sync_country_catalog(),
        "work_types": _sync_group_catalog("work_type", "type"),
        "languages": _sync_group_catalog("language", "language"),
        "source_types": _sync_group_catalog("source_type", "primary_location.source.type"),
        "catalog": catalog_status(),
    }


def _search_named_entity(entity: str, q: str, *, limit: int, entity_type: str, level_label: str) -> dict[str, Any]:
    query = q.strip()
    limit = _limit(limit)
    if len(query) < 2:
        return {"results": _generic_results(metadata_store.list_entities(entity_type, limit=limit))}
    results = _generic_results(metadata_store.search_entities(entity_type, query, limit=limit))
    errors: list[str] = []
    if len(results) < limit:
        try:
            payload = _get_cached(entity, query, limit)
        except RuntimeError as exc:
            errors.append(str(exc))
        else:
            api_items = [_simple_entity_result(item, entity_type, level_label) for item in payload.get("results", [])]
            metadata_store.upsert_entities(entity_type, api_items, source="openalex_search")
            _add_unique(results, api_items, limit)
    return {"results": results[:limit], "errors": errors, "cache": catalog_status().get(f"{entity_type}s", {})}


def _search_group_catalog(entity_type: str, q: str, *, limit: int) -> dict[str, Any]:
    query = q.strip()
    rows = metadata_store.search_entities(entity_type, query, limit=limit) if query else metadata_store.list_entities(entity_type, limit=limit)
    return {"results": _generic_results(rows), "cache": catalog_status().get(f"{entity_type}s", {})}


def _ensure_group_catalog(entity_type: str, group_by: str) -> None:
    if not metadata_store.list_entities(entity_type, limit=1):
        _sync_group_catalog(entity_type, group_by)


def _ensure_country_catalog() -> None:
    if not metadata_store.list_entities("country", limit=1):
        _sync_country_catalog()


def _sync_country_catalog() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    page = 1
    try:
        while True:
            payload = _get(
                "countries",
                {
                    "page": str(page),
                    "per_page": "100",
                    "select": "id,display_name,country_code,works_count",
                    "sort": "works_count:desc",
                },
            )
            batch = payload.get("results", []) or []
            items.extend(_country_result(item) for item in batch)
            if len(batch) < 100 or page >= 10:
                break
            page += 1
    except RuntimeError:
        return _sync_group_catalog("country", "authorships.institutions.country_code")
    inserted = metadata_store.upsert_entities("country", items, source="openalex_countries")
    return {"inserted": inserted, "items": len(items)}


def _sync_group_catalog(entity_type: str, group_by: str) -> dict[str, Any]:
    payload = _get("works", {"group_by": group_by, "per_page": "100"})
    items = [_group_item(row, entity_type) for row in payload.get("group_by", [])]
    inserted = metadata_store.upsert_entities(entity_type, items, source=f"openalex_group_by:{group_by}")
    return {"inserted": inserted, "items": len(items)}


def _group_item(row: dict[str, Any], entity_type: str) -> dict[str, Any]:
    openalex_id = str(row.get("key") or "")
    name = str(row.get("key_display_name") or _short_openalex_id(openalex_id))
    short_id = urllib.parse.unquote(_short_openalex_id(openalex_id) or name)
    label = _group_label(entity_type, short_id, name)
    count = int(row.get("count") or 0)
    return {
        "id": short_id,
        "openalex_id": openalex_id,
        "name": label,
        "display_name": label,
        "level": entity_type,
        "level_label": _level_label(entity_type),
        "description": f"{name} · {count:,} записей OpenAlex".replace(",", " "),
        "works_count": count,
    }


def _group_label(entity_type: str, short_id: str, name: str) -> str:
    return name if name != short_id else short_id


def _subject_alias_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("subject_id") or item.get("value") or "",
        "openalex_id": item.get("openalex_id") or "",
        "name": item.get("label") or item.get("subject_name") or "",
        "level": item.get("subject_level") or "topic",
        "level_label": "Профиль",
        "description": item.get("description") or item.get("subject_name") or "",
        "preset_id": item.get("value") or "",
        "confidence": item.get("confidence") or "",
        "source": "preset",
    }


def _organization_alias_result(item: dict[str, Any]) -> dict[str, Any]:
    openalex_id = str(item.get("institution_id") or "")
    return {
        "id": _short_openalex_id(openalex_id),
        "openalex_id": openalex_id,
        "name": item.get("label") or item.get("institution_name") or "",
        "level": "institution",
        "level_label": "Организация",
        "description": item.get("description") or item.get("institution_name") or "",
        "country_code": item.get("country_code") or "",
        "ror": item.get("ror") or "",
        "preset_id": item.get("value") or "",
        "confidence": item.get("confidence") or "",
        "source": "preset",
    }


def _subject_db_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_subject_result(item) for item in items]


def _subject_result(item: dict[str, Any]) -> dict[str, Any]:
    level = str(item.get("level") or "topic")
    return {
        "id": str(item.get("id") or _short_openalex_id(str(item.get("openalex_id") or ""))),
        "openalex_id": str(item.get("openalex_id") or ""),
        "name": str(item.get("name") or item.get("display_name") or item.get("id") or ""),
        "level": level,
        "level_label": {"field": "Область", "subfield": "Подобласть", "topic": "Тема"}.get(level, "Тема"),
        "description": str(item.get("description") or ""),
        "works_count": item.get("works_count") or 0,
        "source": item.get("source") or "openalex",
    }


def _institution_result(item: dict[str, Any]) -> dict[str, Any]:
    full_id = _full_openalex_url(str(item.get("openalex_id") or item.get("id") or ""), "I")
    geo = item.get("geo") or {}
    context = ", ".join(part for part in [item.get("display_name"), geo.get("country"), item.get("country_code")] if part)
    return {
        "id": _short_openalex_id(full_id),
        "openalex_id": full_id,
        "name": item.get("display_name") or item.get("name") or _short_openalex_id(full_id),
        "level": "institution",
        "level_label": "Организация",
        "description": context,
        "country_code": item.get("country_code"),
        "ror": item.get("ror"),
        "works_count": item.get("works_count") or 0,
    }


def _author_result(item: dict[str, Any]) -> dict[str, Any]:
    full_id = _full_openalex_url(str(item.get("openalex_id") or item.get("id") or ""), "A")
    institutions = item.get("last_known_institutions") or []
    inst_names = [inst.get("display_name") for inst in institutions if inst.get("display_name")]
    inst_countries = [inst.get("country_code") for inst in institutions if inst.get("country_code")]
    context = " · ".join(part for part in [", ".join(inst_names[:2]), ", ".join(sorted(set(inst_countries)))] if part)
    return {
        "id": _short_openalex_id(full_id),
        "openalex_id": full_id,
        "name": item.get("display_name") or item.get("name") or _short_openalex_id(full_id),
        "level": "author",
        "level_label": "Автор",
        "description": context or f"{item.get('works_count', 0)} работ · {item.get('cited_by_count', 0)} цитирований",
        "orcid": item.get("orcid") or "",
        "works_count": item.get("works_count") or 0,
        "cited_by_count": item.get("cited_by_count") or 0,
    }


def _source_result(item: dict[str, Any]) -> dict[str, Any]:
    full_id = _full_openalex_url(str(item.get("openalex_id") or item.get("id") or ""), "S")
    source_type = item.get("type") or item.get("source_type") or ""
    return {
        "id": _short_openalex_id(full_id),
        "openalex_id": full_id,
        "name": item.get("display_name") or item.get("name") or _short_openalex_id(full_id),
        "level": "source",
        "level_label": "Источник",
        "description": " · ".join(part for part in [source_type, f"{item.get('works_count', 0)} работ"] if part),
        "source_type": source_type,
        "works_count": item.get("works_count") or 0,
    }


def _work_result(item: dict[str, Any]) -> dict[str, Any]:
    full_id = _full_openalex_url(str(item.get("openalex_id") or item.get("id") or ""), "W")
    work_type = item.get("type") or item.get("work_type") or ""
    year = item.get("publication_year") or ""
    cited_by = item.get("cited_by_count") or 0
    doi = item.get("doi") or ""
    return {
        "id": _short_openalex_id(full_id),
        "openalex_id": full_id,
        "name": item.get("display_name") or item.get("title") or item.get("name") or _short_openalex_id(full_id),
        "level": "work",
        "level_label": "Работа",
        "description": " · ".join(str(part) for part in [year, work_type, f"{cited_by} цитирований"] if part != ""),
        "doi": doi,
        "work_type": work_type,
        "publication_year": year,
        "cited_by_count": cited_by,
    }


def _country_result(item: dict[str, Any]) -> dict[str, Any]:
    code = str(item.get("country_code") or _short_openalex_id(str(item.get("id") or ""))).upper()
    full_id = str(item.get("openalex_id") or item.get("id") or f"https://openalex.org/countries/{code}")
    name = item.get("display_name") or item.get("name") or code
    return {
        "id": code,
        "openalex_id": full_id,
        "name": f"{name} ({code})" if code and code not in str(name) else str(name),
        "level": "country",
        "level_label": "Страна",
        "description": full_id,
        "country_code": code,
        "works_count": item.get("works_count") or 0,
    }


def _simple_entity_result(item: dict[str, Any], level: str, level_label: str) -> dict[str, Any]:
    full_id = str(item.get("openalex_id") or item.get("id") or "")
    return {
        "id": _short_openalex_id(full_id),
        "openalex_id": full_id,
        "name": item.get("display_name") or item.get("name") or _short_openalex_id(full_id),
        "level": level,
        "level_label": level_label,
        "description": full_id,
        "works_count": item.get("works_count") or 0,
    }


def _generic_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in items:
        level = str(item.get("level") or "")
        if level == "institution":
            out.append(_institution_result(item))
        elif level == "author":
            out.append(_author_result(item))
        elif level == "source":
            out.append(_source_result(item))
        elif level == "work":
            out.append(_work_result(item))
        elif level == "country":
            out.append(_country_result(item))
        else:
            out.append(
                {
                    "id": str(item.get("id") or _short_openalex_id(str(item.get("openalex_id") or ""))),
                    "openalex_id": str(item.get("openalex_id") or ""),
                    "name": str(item.get("name") or item.get("display_name") or item.get("id") or ""),
                    "level": level,
                    "level_label": item.get("level_label") or _level_label(level),
                    "description": str(item.get("description") or ""),
                    "works_count": item.get("works_count") or 0,
                    "cited_by_count": item.get("cited_by_count") or 0,
                    "country_code": item.get("country_code") or "",
                    "ror": item.get("ror") or "",
                    "orcid": item.get("orcid") or "",
                    "source_type": item.get("source_type") or "",
                    "source": item.get("source") or "metadata_db",
                }
            )
    return out


@lru_cache(maxsize=512)
def _get_cached(entity: str, query: str, limit: int) -> dict[str, Any]:
    if entity == "topics":
        select = "id,display_name,subfield,field,works_count"
    elif entity == "subfields":
        select = "id,display_name,field,works_count"
    elif entity == "fields":
        select = "id,display_name,works_count"
    elif entity == "institutions":
        select = "id,display_name,country_code,ror,geo,works_count"
    elif entity == "authors":
        select = "id,display_name,orcid,last_known_institutions,works_count,cited_by_count"
    elif entity == "sources":
        select = "id,display_name,type,works_count"
    elif entity == "works":
        select = "id,doi,display_name,publication_year,type,cited_by_count"
    else:
        select = "id,display_name,works_count"
    return _get(entity, {"search": query, "per_page": str(limit), "select": select})


def _lookup_subject_by_id(query: str, level: str, entity: str) -> dict[str, Any] | None:
    short = _subject_short_id(query, level)
    if not short:
        return None
    if entity == "topics":
        select = "id,display_name,subfield,field,works_count"
    elif entity == "subfields":
        select = "id,display_name,field,works_count"
    else:
        select = "id,display_name,works_count"
    item = _get_single(f"{entity}/{short}", {"select": select})
    return _subject_catalog_item(item, level)


def _lookup_institution_by_ror(query: str) -> list[dict[str, Any]]:
    ror = _ror_id(query)
    if not ror:
        return []
    try:
        item = _get_single(f"institutions/ror:{ror}", {"select": "id,display_name,country_code,ror,geo,works_count"})
    except RuntimeError:
        return []
    return [_institution_result(item)]


def _lookup_author_by_orcid(query: str) -> list[dict[str, Any]]:
    orcid = _orcid_id(query)
    if not orcid:
        return []
    try:
        item = _get_single(
            f"authors/orcid:{orcid}",
            {"select": "id,display_name,orcid,last_known_institutions,works_count,cited_by_count"},
        )
    except RuntimeError:
        return []
    return [_author_result(item)]


def _lookup_work_by_doi(query: str) -> list[dict[str, Any]]:
    doi = _doi_id(query)
    if not doi:
        return []
    try:
        item = _get_single(
            f"works/{urllib.parse.quote(f'doi:{doi}', safe=':')}",
            {"select": "id,doi,display_name,publication_year,type,cited_by_count"},
        )
    except RuntimeError:
        return []
    return [_work_result(item)]


def _lookup_single_by_openalex_id(entity: str, prefix: str, query: str, *, level: str, level_label: str) -> list[dict[str, Any]]:
    short = _prefixed_openalex_id(query, prefix)
    if not short:
        return []
    select = {
        "institutions": "id,display_name,country_code,ror,geo,works_count",
        "authors": "id,display_name,orcid,last_known_institutions,works_count,cited_by_count",
        "sources": "id,display_name,type,works_count",
        "works": "id,doi,display_name,publication_year,type,cited_by_count",
    }.get(entity, "id,display_name,works_count")
    try:
        item = _get_single(f"{entity}/{short}", {"select": select})
    except RuntimeError:
        return []
    if level == "institution":
        return [_institution_result(item)]
    if level == "author":
        return [_author_result(item)]
    if level == "source":
        return [_source_result(item)]
    if level == "work":
        return [_work_result(item)]
    return [_simple_entity_result(item, level, level_label)]


def _download_subject_entity(entity: str, level: str, select: str, *, max_records: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = "*"
    while True:
        payload = _get(entity, {"cursor": cursor, "per_page": "100", "select": select, "sort": "works_count:desc"})
        for item in payload.get("results") or []:
            rows.append(_subject_catalog_item(item, level))
            if max_records is not None and len(rows) >= max_records:
                return rows
        next_cursor = (payload.get("meta") or {}).get("next_cursor")
        if not next_cursor or next_cursor == cursor:
            return rows
        cursor = str(next_cursor)


def _subject_catalog_item(item: dict[str, Any], level: str) -> dict[str, Any]:
    full_id = str(item.get("id") or "")
    short_id = _short_openalex_id(full_id)
    field = item.get("field") or {}
    subfield = item.get("subfield") or {}
    field_name = field.get("display_name") or ""
    subfield_name = subfield.get("display_name") or ""
    description = " / ".join(part for part in [field_name, subfield_name] if part)
    return {
        "id": short_id,
        "openalex_id": full_id,
        "name": item.get("display_name") or short_id,
        "level": level,
        "field_name": field_name,
        "subfield_name": subfield_name,
        "description": description,
        "works_count": item.get("works_count") or 0,
    }


def _add_unique(target: list[dict[str, Any]], items: list[dict[str, Any]], limit: int) -> None:
    seen = {_dedupe_key(item) for item in target}
    for item in items:
        key = _dedupe_key(item)
        if not key or key in seen:
            continue
        seen.add(key)
        target.append(item)
        if len(target) >= limit:
            return


def _dedupe_key(item: dict[str, Any]) -> str:
    return str(item.get("openalex_id") or f"{item.get('level')}:{item.get('id')}" or item.get("name") or "")


def _get(entity: str, params: dict[str, str]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{OPENALEX_BASE}/{entity}?{query}",
        headers={"User-Agent": "openalex-dss/0.3.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAlex {entity} HTTP {exc.code}: {body[:240]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAlex {entity} is unavailable: {exc}") from exc


def _get_single(path: str, params: dict[str, str]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{OPENALEX_BASE}/{path}?{query}",
        headers={"User-Agent": "openalex-dss/0.3.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAlex {path} HTTP {exc.code}: {body[:240]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAlex {path} is unavailable: {exc}") from exc


def _entity_status(status: dict[str, Any], entity_type: str) -> dict[str, Any]:
    return {
        "db_path": status.get("db_path"),
        "exists": status.get("exists"),
        "items": (status.get("entities") or {}).get(entity_type, 0),
    }


def _level_label(level: str) -> str:
    return {
        "keyword": "Ключевое слово",
        "institution": "Организация",
        "author": "Автор",
        "source": "Источник",
        "country": "Страна",
        "language": "Язык",
        "work_type": "Тип публикации",
        "source_type": "Тип источника",
    }.get(level, level or "Значение")


def _limit(limit: int) -> int:
    return max(1, min(int(limit), 50))


def _short_openalex_id(value: str) -> str:
    return str(value or "").strip().rstrip("/").rsplit("/", 1)[-1]


def _full_openalex_url(value: str, prefix: str) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    if text.startswith("https://openalex.org/"):
        return text
    short = text.rsplit("/", 1)[-1]
    if re.match(rf"^{prefix}\d+$", short):
        return f"https://openalex.org/{short}"
    return text


def _prefixed_openalex_id(value: str, prefix: str) -> str:
    text = str(value or "").strip().rstrip("/")
    text = text.rsplit("/", 1)[-1]
    return text if re.match(rf"^{prefix}\d+$", text) else ""


def _subject_short_id(query: str, level: str) -> str:
    text = str(query or "").strip().rstrip("/")
    text = text.rsplit("/", 1)[-1]
    if level == "topic":
        return text if re.match(r"^T\d+$", text) else ""
    return text if re.match(r"^\d+$", text) else ""


def _ror_id(value: str) -> str:
    text = value.strip()
    text = text.replace("https://ror.org/", "").replace("http://ror.org/", "").replace("ror:", "")
    return text if re.match(r"^[0-9a-z]{9}$", text, re.IGNORECASE) else ""


def _orcid_id(value: str) -> str:
    text = value.strip()
    text = text.replace("https://orcid.org/", "").replace("http://orcid.org/", "").replace("orcid:", "")
    return text if re.match(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$", text, re.IGNORECASE) else ""


def _doi_id(value: str) -> str:
    text = value.strip()
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^doi:", "", text, flags=re.IGNORECASE)
    return text if re.match(r"^10\.\S+/\S+$", text, re.IGNORECASE) else ""
