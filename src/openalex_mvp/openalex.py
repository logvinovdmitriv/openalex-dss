from __future__ import annotations

import json
import gzip
import os
import hashlib
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .config import SliceConfig
from .io_utils import ensure_dir, ensure_parent, sha256_file, write_json

API_BASE = "https://api.openalex.org/works"
AUTHORS_API_BASE = "https://api.openalex.org/authors"
_CACHE_STATS = {"hits": 0, "misses": 0}

AUTHOR_SELECT_FIELDS = (
    "id",
    "display_name",
    "orcid",
    "works_count",
    "cited_by_count",
    "summary_stats",
    "last_known_institutions",
    "affiliations",
    "topics",
    "topic_share",
    "counts_by_year",
    "works_api_url",
    "ids",
    "created_date",
    "updated_date",
)


def build_filter(cfg: SliceConfig) -> str:
    filters = []
    if cfg.filter_mode == "all":
        pass
    elif cfg.filter_mode == "primary_topic":
        if cfg.entity_level == "subfield":
            filters.append(f"primary_topic.subfield.id:{cfg.entity_id_short}")
        elif cfg.entity_level == "field":
            filters.append(f"primary_topic.field.id:{cfg.entity_id_short}")
        elif cfg.entity_level == "topic":
            filters.append(f"primary_topic.id:{cfg.entity_id_short}")
        else:
            raise ValueError(f"Unsupported entity_level: {cfg.entity_level}")
    elif cfg.filter_mode == "topics_any":
        if cfg.entity_level == "subfield":
            filters.append(f"topics.subfield.id:{cfg.entity_id_short}")
        elif cfg.entity_level == "field":
            filters.append(f"topics.field.id:{cfg.entity_id_short}")
        elif cfg.entity_level == "topic":
            filters.append(f"topics.id:{cfg.entity_id_short}")
        else:
            raise ValueError(f"Unsupported entity_level: {cfg.entity_level}")
    elif cfg.filter_mode == "keyword":
        keyword_id = _short_openalex_id(cfg.keyword_id)
        if not keyword_id:
            raise ValueError("keyword_id is required for filter_mode=keyword")
        filters.append(f"keywords.id:{keyword_id}")
    elif cfg.filter_mode == "search":
        if not cfg.text_search_query.strip():
            raise ValueError("text_search_query is required for filter_mode=search")
    else:
        raise ValueError(f"Unsupported filter_mode: {cfg.filter_mode}")

    if cfg.from_publication_date:
        filters.append(f"from_publication_date:{cfg.from_publication_date}")
    if cfg.to_publication_date:
        filters.append(f"to_publication_date:{cfg.to_publication_date}")
    if cfg.work_type:
        filters.append(f"type:{cfg.work_type}")
    if cfg.exclude_retracted:
        filters.append("is_retracted:false")
    if cfg.exclude_paratext:
        filters.append("is_paratext:false")
    if not cfg.include_xpac:
        filters.append("is_xpac:false")
    if cfg.country_code:
        filters.append(f"authorships.institutions.country_code:{cfg.country_code.upper()}")
    if cfg.author_id:
        filters.append(f"authorships.author.id:{_openalex_filter_ids(cfg.author_id)}")
    if cfg.institution_id:
        filters.append(f"authorships.institutions.id:{_openalex_filter_ids(cfg.institution_id)}")
    if cfg.source_id:
        filters.append(f"primary_location.source.id:{_openalex_filter_ids(cfg.source_id)}")
    if cfg.source_type:
        filters.append(f"primary_location.source.type:{cfg.source_type}")
    if cfg.language:
        filters.append(f"language:{cfg.language.lower()}")
    if cfg.open_access_is_oa in {"true", "false"}:
        filters.append(f"open_access.is_oa:{cfg.open_access_is_oa}")
    if cfg.has_abstract in {"true", "false"}:
        filters.append(f"has_abstract:{cfg.has_abstract}")
    if cfg.min_cited_by_count > 0:
        filters.append(f"cited_by_count:>{cfg.min_cited_by_count - 1}")
    if cfg.doi:
        filters.append(f"doi:{cfg.doi}")
    if cfg.raw_openalex_filter:
        filters.extend(_raw_filter_parts(cfg.raw_openalex_filter))
    return ",".join(filters)


def build_author_filter(cfg: SliceConfig) -> str:
    filters = []
    if cfg.author_id:
        filters.append(f"openalex:{_openalex_filter_ids(cfg.author_id)}")
    if cfg.entity_level != "topic":
        if cfg.author_id:
            return ",".join(filters)
        raise ValueError("Author-first OpenAlex loading supports topic slices through authors.topics.id")
    filters.append(f"topics.id:{cfg.entity_id_short}")
    if cfg.country_code:
        if cfg.affiliation_mode == "historical":
            filters.append(f"affiliations.institution.country_code:{cfg.country_code.upper()}")
        else:
            filters.append(f"last_known_institutions.country_code:{cfg.country_code.upper()}")
    if cfg.institution_id:
        inst_id = _short_openalex_id(cfg.institution_id)
        if cfg.affiliation_mode == "historical":
            filters.append(f"affiliations.institution.id:{inst_id}")
        else:
            filters.append(f"last_known_institutions.id:{inst_id}")
    return ",".join(filters)


def fetch_works(
    cfg: SliceConfig,
    out_path: str | Path = "data/raw/works_raw.jsonl",
    meta_path: str | Path = "data/passports/fetch_meta.json",
    max_works: int | None = None,
) -> dict[str, Any]:
    out = ensure_parent(_resolve_data_path(out_path))
    meta_out = ensure_parent(_resolve_data_path(meta_path))
    limit = max_works if max_works is not None else cfg.max_works
    per_page = max(1, min(cfg.per_page, 100))

    params = _works_params(cfg, per_page)
    api_key = os.environ.get(cfg.api_key_env)
    if api_key:
        params["api_key"] = api_key

    fetched = 0
    page_count = 0
    total_available = None
    cursors: list[dict[str, Any]] = []

    with out.open("w", encoding="utf-8", newline="\n") as f:
        cursor = "*"
        while fetched < limit:
            params["cursor"] = cursor
            payload = _get_json(API_BASE, params)
            page_count += 1
            meta = payload.get("meta") or {}
            if total_available is None:
                total_available = meta.get("count")
            results = payload.get("results") or []
            if not results:
                break

            remaining = limit - fetched
            selected = results[:remaining]
            for work in selected:
                f.write(json.dumps(work, ensure_ascii=False, sort_keys=True) + "\n")
            fetched += len(selected)

            next_cursor = meta.get("next_cursor")
            cursors.append(
                {
                    "page_no": page_count,
                    "n_results": len(results),
                    "n_written": len(selected),
                    "cursor_in": cursor,
                    "cursor_out": next_cursor,
                }
            )
            if not next_cursor or next_cursor == cursor or len(selected) < len(results):
                break
            cursor = str(next_cursor)

    meta_doc = {
        "api_base": API_BASE,
        "filter": params["filter"],
        "sort": cfg.sort,
        "select": params["select"],
        "search": params.get("search"),
        "per_page": per_page,
        "max_works": limit,
        "fetched_works": fetched,
        "total_available": total_available,
        "pages_count": page_count,
        "used_api_key": bool(api_key),
        "pages": cursors,
        "output_file": str(out),
    }
    write_json(meta_out, meta_doc)
    return meta_doc


def fetch_works_slice_dump(
    cfg: SliceConfig,
    out_dir: str | Path | None = None,
    *,
    max_records: int | None = None,
    max_bytes: int = 500 * 1024 * 1024,
    raw_filename: str = "works.jsonl.gz",
    passport_filename: str = "slice_passport.json",
    complete_slice_required: bool = True,
    allow_incomplete_preview: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Download a compact reproducible OpenAlex Works slice.

    This is intentionally not a full S3 snapshot downloader. It creates a small
    API-based raw JSONL dump plus a local passport with filters, select fields,
    safety limits and checksum. All downstream metrics should be computed from
    this fixed file.
    """

    dump_dir = ensure_dir(_resolve_data_path(out_dir) if out_dir else _data_root() / "raw/openalex_slices" / cfg.slice_name)
    raw_path = dump_dir / raw_filename
    passport_path = dump_dir / passport_filename
    limit = max_records if max_records is not None else cfg.max_works
    per_page = max(1, min(cfg.per_page, 100))
    params = _works_params(cfg, per_page)
    api_key = os.environ.get(cfg.api_key_env)
    if api_key:
        params["api_key"] = api_key

    fetched = 0
    bytes_written = 0
    page_count = 0
    total_available = None
    stop_reason = "api_exhausted"
    first_meta: dict[str, Any] | None = None
    cursors: list[dict[str, Any]] = []

    opener = gzip.open if raw_path.name.endswith(".gz") else open
    with opener(raw_path, "wt", encoding="utf-8", newline="\n") as handle:
        cursor = "*"
        while fetched < limit:
            params["cursor"] = cursor
            payload = _get_json(API_BASE, params)
            page_count += 1
            meta = payload.get("meta") or {}
            if first_meta is None:
                first_meta = meta
            if total_available is None:
                total_available = meta.get("count")
            results = payload.get("results") or []
            if not results:
                if fetched == 0:
                    stop_reason = "no_results"
                break

            written_this_page = 0
            for work in results:
                if fetched >= limit:
                    stop_reason = "max_records"
                    break
                line = json.dumps(work, ensure_ascii=False, sort_keys=True) + "\n"
                line_bytes = len(line.encode("utf-8"))
                if fetched > 0 and bytes_written + line_bytes > max_bytes:
                    stop_reason = "max_bytes"
                    break
                handle.write(line)
                fetched += 1
                written_this_page += 1
                bytes_written += line_bytes

            next_cursor = meta.get("next_cursor")
            cursors.append(
                {
                    "page_no": page_count,
                    "n_results": len(results),
                    "n_written": written_this_page,
                    "cursor_in": cursor,
                    "cursor_out": next_cursor,
                }
            )
            if progress_callback:
                target = min(int(total_available or limit or fetched or 1), int(limit or total_available or fetched or 1))
                percent = min(95, int((fetched / max(1, target)) * 100))
                progress_callback(
                    {
                        "fetched": fetched,
                        "bytes_written": bytes_written,
                        "page_count": page_count,
                        "total_available": total_available,
                        "target_records": target,
                        "percent": percent,
                        "stage": f"downloaded {fetched} works",
                    }
                )
            if stop_reason in {"max_records", "max_bytes"}:
                break
            if not next_cursor or next_cursor == cursor:
                break
            cursor = str(next_cursor)

    checksum = sha256_file(raw_path)
    public_params = {key: value for key, value in params.items() if key != "api_key"}
    incomplete_by_limit = stop_reason in {"max_records", "max_bytes"}
    scientific_completeness = "incomplete" if incomplete_by_limit else "complete"
    allowed_for_final_analysis = not incomplete_by_limit
    passport = {
        "slice_id": cfg.slice_name,
        "source_mode": "api_dump_first",
        "source": "OpenAlex API works",
        "base_url": API_BASE,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "openalex_request": {
            "filter": public_params.get("filter"),
            "search": public_params.get("search"),
            "sort": public_params.get("sort"),
            "select": public_params.get("select"),
            "per_page": per_page,
        },
        "filters": [part for part in str(public_params.get("filter") or "").split(",") if part],
        "select_fields": list(_works_select_fields(cfg)),
        "limits": {
            "max_records": limit,
            "max_bytes": max_bytes,
        },
        "records_downloaded": fetched,
        "no_data": fetched == 0,
        "bytes_written": raw_path.stat().st_size,
        "stop_reason": stop_reason,
        "scientific_completeness": scientific_completeness,
        "allowed_for_final_analysis": allowed_for_final_analysis,
        "complete_slice_required": complete_slice_required,
        "allow_incomplete_preview": allow_incomplete_preview,
        "execution_plan": {
            "strategy": "api_mini_slice",
            "estimate_count": total_available,
            "max_allowed_works": limit,
            "select_fields": list(_works_select_fields(cfg)),
            "pagination": "cursor",
            "per_page": per_page,
            "api_requests_actual": page_count,
            "cache_hits": _CACHE_STATS["hits"],
            "cache_misses": _CACHE_STATS["misses"],
        },
        "storage_plan": {
            "raw_size_mb": round(raw_path.stat().st_size / (1024 * 1024), 3),
            "raw_jsonl": str(raw_path),
            "materialized_tables_after_import": [
                "works_flat",
                "authorships_flat",
                "author_work_metrics",
                "author_indices",
            ],
        },
        "total_available_first_page": total_available,
        "raw_jsonl": str(raw_path),
        "raw_jsonl_sha256": checksum,
        "used_api_key": bool(api_key),
        "pages_count": page_count,
        "pages": cursors,
        "first_response_meta": first_meta or {},
        "snapshot_policy": {
            "this_file_is_full_openalex_snapshot": False,
            "full_snapshot_note": "Full OpenAlex snapshot is stored in S3 and is too large for the MVP notebook workflow; this artifact is a compact reproducible local slice.",
            "downstream_rule": "All scientometric indices must be recalculated locally from this fixed raw JSONL slice.",
        },
    }
    if incomplete_by_limit:
        passport["incomplete_warning"] = (
            "This is an incomplete technical preview and must not be used for final scientometric conclusions."
            if allow_incomplete_preview and not complete_slice_required
            else "Download stopped by a technical limit before the full slice was materialized."
        )
    write_json(passport_path, passport)
    return passport


def estimate_works(
    cfg: SliceConfig,
    *,
    max_dump_bytes: int | None = None,
    sample_size: int = 100,
    record_budget: int | None = None,
) -> dict[str, Any]:
    sample_page_size = max(1, min(sample_size, 100))
    count_params = _works_params(cfg, 1)
    count_params["cursor"] = "*"
    sample_params = _works_params(cfg, sample_page_size)
    sample_params.pop("cursor", None)
    sample_params["sample"] = str(sample_page_size)
    sample_params["seed"] = str(cfg.random_seed)
    api_key = os.environ.get(cfg.api_key_env)
    if api_key:
        count_params["api_key"] = api_key
        sample_params["api_key"] = api_key

    before = cache_stats()
    count_payload = _get_json(API_BASE, count_params)
    sample_payload = _get_json(API_BASE, sample_params)
    after = cache_stats()
    meta = count_payload.get("meta") or {}
    results = sample_payload.get("results") or count_payload.get("results") or []
    count = int(meta.get("count") or 0)
    record_sizes = [
        len((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
        for row in results
    ]
    sample_bytes = record_sizes[0] if record_sizes else 0
    estimated_record_bytes = max(_mean(record_sizes), 2048)
    p90_record_bytes = max(_quantile(record_sizes, 0.9), estimated_record_bytes)
    planned_records = min(count, int(record_budget)) if record_budget else count
    estimated_raw_bytes = count * estimated_record_bytes
    estimated_raw_bytes_p90 = count * p90_record_bytes
    estimated_raw_bytes_for_budget = planned_records * estimated_record_bytes
    max_bytes = max_dump_bytes or 500 * 1024 * 1024
    planned_pages = (planned_records + max(1, cfg.per_page) - 1) // max(1, cfg.per_page)
    public_params = {key: value for key, value in count_params.items() if key != "api_key"}
    public_sample_params = {key: value for key, value in sample_params.items() if key != "api_key"}
    return {
        "api_base": API_BASE,
        "estimate_count": count,
        "sample_record_bytes": sample_bytes,
        "sample_size": len(record_sizes),
        "estimated_record_bytes": estimated_record_bytes,
        "estimated_record_bytes_p90": p90_record_bytes,
        "planned_records": planned_records,
        "estimated_raw_bytes": estimated_raw_bytes,
        "estimated_raw_mb": round(estimated_raw_bytes / (1024 * 1024), 3),
        "estimated_raw_bytes_p90": estimated_raw_bytes_p90,
        "estimated_raw_mb_p90": round(estimated_raw_bytes_p90 / (1024 * 1024), 3),
        "estimated_raw_bytes_for_download_budget": estimated_raw_bytes_for_budget,
        "estimated_raw_mb_for_download_budget": round(estimated_raw_bytes_for_budget / (1024 * 1024), 3),
        "max_dump_bytes": max_bytes,
        "max_dump_mb": round(max_bytes / (1024 * 1024), 3),
        "api_requests_planned": planned_pages,
        "per_page": cfg.per_page,
        "openalex_request": public_params,
        "sample_request": public_sample_params,
        "cache": {
            "hits_delta": after["hits"] - before["hits"],
            "misses_delta": after["misses"] - before["misses"],
            "hits_total": after["hits"],
            "misses_total": after["misses"],
        },
    }


def fetch_authors(
    cfg: SliceConfig,
    out_path: str | Path = "data/raw/authors_raw.jsonl",
    meta_path: str | Path = "data/passports/fetch_meta.json",
    max_authors: int | None = None,
) -> dict[str, Any]:
    out = ensure_parent(_resolve_data_path(out_path))
    meta_out = ensure_parent(_resolve_data_path(meta_path))
    limit = max_authors if max_authors is not None else cfg.max_works
    per_page = max(1, min(cfg.per_page, 100))
    sort = _author_sort(cfg.sort)

    params = {
        "filter": build_author_filter(cfg),
        "sort": sort,
        "per-page": str(per_page),
        "cursor": "*",
        "select": ",".join(AUTHOR_SELECT_FIELDS),
    }
    api_key = os.environ.get(cfg.api_key_env)
    if api_key:
        params["api_key"] = api_key

    fetched = 0
    page_count = 0
    total_available = None
    cursors: list[dict[str, Any]] = []

    with out.open("w", encoding="utf-8", newline="\n") as f:
        cursor = "*"
        while fetched < limit:
            params["cursor"] = cursor
            payload = _get_json(AUTHORS_API_BASE, params)
            page_count += 1
            meta = payload.get("meta") or {}
            if total_available is None:
                total_available = meta.get("count")
            results = payload.get("results") or []
            if not results:
                break

            remaining = limit - fetched
            selected = results[:remaining]
            for author in selected:
                f.write(json.dumps(author, ensure_ascii=False, sort_keys=True) + "\n")
            fetched += len(selected)

            next_cursor = meta.get("next_cursor")
            cursors.append(
                {
                    "page_no": page_count,
                    "n_results": len(results),
                    "n_written": len(selected),
                    "cursor_in": cursor,
                    "cursor_out": next_cursor,
                }
            )
            if not next_cursor or next_cursor == cursor or len(selected) < len(results):
                break
            cursor = str(next_cursor)

    meta_doc = {
        "api_base": AUTHORS_API_BASE,
        "source_entity": "authors",
        "filter": params["filter"],
        "sort": sort,
        "select": params["select"],
        "per_page": per_page,
        "max_authors": limit,
        "fetched_authors": fetched,
        "total_available": total_available,
        "pages_count": page_count,
        "used_api_key": bool(api_key),
        "pages": cursors,
        "output_file": str(out),
    }
    write_json(meta_out, meta_doc)
    return meta_doc


def _author_sort(sort: str) -> str:
    if sort in {"works_count:desc", "cited_by_count:desc", "summary_stats.h_index:desc", "summary_stats.i10_index:desc"}:
        return sort
    return "cited_by_count:desc"


def _works_params(cfg: SliceConfig, per_page: int) -> dict[str, str]:
    select_fields = _works_select_fields(cfg)
    params = {
        "filter": build_filter(cfg),
        "sort": cfg.sort,
        "per-page": str(per_page),
        "cursor": "*",
        "select": ",".join(select_fields),
    }
    if cfg.filter_mode == "search" and cfg.text_search_query.strip():
        params["search"] = cfg.text_search_query.strip()
    return params


def _works_select_fields(cfg: SliceConfig) -> tuple[str, ...]:
    required = ("language", "open_access")
    return tuple(dict.fromkeys([*cfg.select_fields, *required]))


def _short_openalex_id(value: str) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def _openalex_filter_ids(value: str) -> str:
    ids = [_short_openalex_id(part) for part in str(value or "").replace(",", "|").split("|")]
    return "|".join(item for item in ids if item)


def _raw_filter_parts(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _get_json(url: str, params: dict[str, str]) -> dict[str, Any]:
    public_params = {key: value for key, value in params.items() if key != "api_key"}
    cache_path = _api_cache_path(url, public_params)
    if cache_path.exists() and os.environ.get("OPENALEX_DSS_DISABLE_API_CACHE") != "1":
        _CACHE_STATS["hits"] += 1
        return json.loads(cache_path.read_text(encoding="utf-8"))

    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": "openalex-mvp-indices/0.1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            _CACHE_STATS["misses"] += 1
            return payload
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAlex HTTP {exc.code}: {body}") from exc


def cache_stats() -> dict[str, int]:
    return dict(_CACHE_STATS)


def _mean(values: list[int]) -> int:
    if not values:
        return 0
    return int(sum(values) / len(values))


def _quantile(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * max(0.0, min(1.0, q))))
    return ordered[index]


def _api_cache_path(url: str, params: dict[str, str]) -> Path:
    canonical = json.dumps({"url": url, "params": params}, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return _data_root() / "cache/openalex_api" / f"{digest}.json"


def _data_root() -> Path:
    configured = os.environ.get("OPENALEX_DSS_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parents[2].parent / "openalex-dss-data").resolve()


def _resolve_data_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "data":
        return _data_root().joinpath(*path.parts[1:])
    return path
