from __future__ import annotations

import json
import os
import hashlib
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .config import SliceConfig

API_BASE = "https://api.openalex.org/works"
_CACHE_STATS = {"hits": 0, "misses": 0}
_LAST_RATE_LIMIT: dict[str, Any] = {}


def build_filter(cfg: SliceConfig) -> str:
    filters = []
    if cfg.filter_mode == "all":
        pass
    elif cfg.filter_mode == "primary_topic":
        filters.append(f"{_subject_level_field('subject_primary_topic', cfg.entity_level)}:{cfg.entity_id_short}")
    elif cfg.filter_mode == "topics_any":
        filters.append(f"{_subject_level_field('subject_topics_any', cfg.entity_level)}:{cfg.entity_id_short}")
    elif cfg.filter_mode == "keyword":
        keyword_id = _short_openalex_id(cfg.keyword_id)
        if not keyword_id:
            raise ValueError("keyword_id is required for filter_mode=keyword")
        filters.append(f"{_filter_field('keyword')}:{keyword_id}")
    elif cfg.filter_mode == "search":
        if not cfg.text_search_query.strip():
            raise ValueError("text_search_query is required for filter_mode=search")
    else:
        raise ValueError(f"Unsupported filter_mode: {cfg.filter_mode}")

    if cfg.from_publication_date:
        filters.append(f"{_filter_field('from_publication_date')}:{cfg.from_publication_date}")
    if cfg.to_publication_date:
        filters.append(f"{_filter_field('to_publication_date')}:{cfg.to_publication_date}")
    if cfg.work_type:
        filters.append(f"{_filter_field('work_type')}:{cfg.work_type}")
    if cfg.exclude_retracted:
        filters.append(f"{_filter_field('is_retracted')}:false")
    if cfg.exclude_paratext:
        filters.append(f"{_filter_field('is_paratext')}:false")
    if not cfg.include_xpac:
        filters.append(f"{_filter_field('is_xpac')}:false")
    if cfg.country_code:
        filters.append(f"{_filter_field('country')}:{cfg.country_code.upper()}")
    if cfg.author_id:
        filters.append(f"{_filter_field('author')}:{_openalex_filter_ids(cfg.author_id)}")
    if cfg.institution_id:
        filters.append(f"{_filter_field('institution')}:{_openalex_filter_ids(cfg.institution_id)}")
    if cfg.source_id:
        filters.append(f"{_filter_field('source')}:{_openalex_filter_ids(cfg.source_id)}")
    if cfg.source_type:
        filters.append(f"{_filter_field('source_type')}:{cfg.source_type}")
    if cfg.language:
        filters.append(f"{_filter_field('language')}:{cfg.language.lower()}")
    if cfg.open_access_is_oa in {"true", "false"}:
        filters.append(f"{_filter_field('open_access')}:{cfg.open_access_is_oa}")
    if cfg.has_abstract in {"true", "false"}:
        filters.append(f"{_filter_field('has_abstract')}:{cfg.has_abstract}")
    if cfg.min_cited_by_count > 0:
        filters.append(f"{_filter_field('min_citations')}:>{cfg.min_cited_by_count - 1}")
    if cfg.doi:
        filters.append(f"{_filter_field('doi')}:{cfg.doi}")
    if cfg.raw_openalex_filter:
        filters.extend(_raw_filter_parts(cfg.raw_openalex_filter))
    return ",".join(filters)


def estimate_works(
    cfg: SliceConfig,
    *,
    sample_size: int = 100,
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
    facet_payloads = _estimate_facets(cfg, count_params, api_key)
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
    planned_records = count
    estimated_raw_bytes = count * estimated_record_bytes
    estimated_raw_bytes_p90 = count * p90_record_bytes
    estimated_raw_bytes_for_budget = planned_records * estimated_record_bytes
    planned_pages = (planned_records + max(1, cfg.per_page) - 1) // max(1, cfg.per_page)
    public_params = {key: value for key, value in count_params.items() if key != "api_key"}
    public_sample_params = {key: value for key, value in sample_params.items() if key != "api_key"}
    corpus = corpus_request(cfg)
    consistency = download_consistency(cfg)
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
        "estimated_raw_bytes_for_download": estimated_raw_bytes_for_budget,
        "estimated_raw_mb_for_download": round(estimated_raw_bytes_for_budget / (1024 * 1024), 3),
        "api_requests_planned": planned_pages,
        "per_page": cfg.per_page,
        "estimated_memory_mb": round((planned_records * 260) / (1024 * 1024), 3),
        "estimated_parquet_mb": round((planned_records * max(512, estimated_record_bytes * 0.32)) / (1024 * 1024), 3),
        "corpus_request": corpus,
        "estimate_signature": corpus_signature(cfg),
        "download_signature": cli_download_signature(cfg),
        "download_consistency": consistency,
        "openalex_request": public_params,
        "sample_request": public_sample_params,
        "facets": facet_payloads,
        "rate_limit": rate_limit_status(),
        "estimated_cost_usd": _payload_cost(count_payload) + _payload_cost(sample_payload) + _facets_cost(facet_payloads),
        "cache": {
            "hits_delta": after["hits"] - before["hits"],
            "misses_delta": after["misses"] - before["misses"],
            "hits_total": after["hits"],
            "misses_total": after["misses"],
        },
    }


def corpus_request(cfg: SliceConfig) -> dict[str, str]:
    request = {"filter": build_filter(cfg)}
    if cfg.filter_mode == "search" and cfg.text_search_query.strip():
        request["search"] = cfg.text_search_query.strip()
    return request


def corpus_signature(cfg: SliceConfig) -> str:
    canonical = json.dumps(corpus_request(cfg), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cli_download_signature(cfg: SliceConfig) -> str:
    canonical = json.dumps({"filter": build_filter(cfg), "tool": "openalex_cli"}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def download_consistency(cfg: SliceConfig) -> dict[str, Any]:
    reasons: list[str] = []
    if cfg.filter_mode == "search" and cfg.text_search_query.strip():
        reasons.append("Installed OpenAlex CLI supports --filter but not the API search parameter; use OpenAlex entity filters or a future ID-based search download mode.")
    compatible = not reasons
    return {
        "compatible": compatible,
        "estimate_signature": corpus_signature(cfg),
        "download_signature": cli_download_signature(cfg),
        "tool": "openalex_cli",
        "reasons": reasons,
    }


def _estimate_facets(cfg: SliceConfig, count_params: dict[str, str], api_key: str | None) -> dict[str, Any]:
    base = {
        key: value
        for key, value in count_params.items()
        if key in {"filter", "search"} and value
    }
    if api_key:
        base["api_key"] = api_key
    facets: dict[str, Any] = {}
    facets_cfg = _filter_registry().get("facets") or {}
    for name, spec in facets_cfg.items():
        group_by = str((spec or {}).get("group_by") or "").strip()
        if not group_by:
            continue
        params = {**base, "group_by": group_by, "per_page": "20"}
        try:
            payload = _get_json(API_BASE, params)
        except RuntimeError as exc:
            facets[name] = {"group_by": group_by, "rows": [], "error": str(exc)}
            continue
        rows = [
            {
                "key": row.get("key"),
                "label": row.get("key_display_name") or row.get("key") or "",
                "count": int(row.get("count") or 0),
            }
            for row in payload.get("group_by", [])
        ]
        facets[name] = {"group_by": group_by, "rows": rows, "cost_usd": _payload_cost(payload)}
    return facets


def _works_params(cfg: SliceConfig, per_page: int) -> dict[str, str]:
    select_fields = _works_select_fields(cfg)
    params = {
        "filter": build_filter(cfg),
        "sort": cfg.sort,
        "per_page": str(per_page),
        "cursor": "*",
        "select": ",".join(select_fields),
    }
    if cfg.filter_mode == "search" and cfg.text_search_query.strip():
        params["search"] = cfg.text_search_query.strip()
    return params


def _works_select_fields(cfg: SliceConfig) -> tuple[str, ...]:
    required = ("language", "open_access", "has_abstract")
    return tuple(dict.fromkeys([*cfg.select_fields, *required]))


def default_sort() -> str:
    return str(_filter_registry().get("sort", {}).get("default") or "publication_date:asc,openalex:asc")


def rate_limit_status() -> dict[str, Any]:
    return dict(_LAST_RATE_LIMIT)


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
            _capture_rate_limit_headers(response.headers)
            payload = json.loads(response.read().decode("utf-8"))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            _CACHE_STATS["misses"] += 1
            return payload
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAlex HTTP {exc.code}: {body}") from exc


def _capture_rate_limit_headers(headers: Any) -> None:
    mapping = {
        "X-RateLimit-Limit": "limit",
        "X-RateLimit-Remaining": "remaining",
        "X-RateLimit-Credits-Used": "credits_used",
        "X-RateLimit-Reset": "reset_seconds",
    }
    values: dict[str, Any] = {}
    for header, key in mapping.items():
        raw = headers.get(header)
        if raw is None:
            continue
        try:
            values[key] = float(raw) if "." in str(raw) else int(raw)
        except ValueError:
            values[key] = raw
    if values:
        _LAST_RATE_LIMIT.clear()
        _LAST_RATE_LIMIT.update(values)


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


def _subject_level_field(filter_key: str, level: str) -> str:
    base = _filter_field(filter_key)
    if level == "topic":
        return f"{base}.id"
    if level in {"field", "subfield"}:
        return f"{base}.{level}.id"
    raise ValueError(f"Unsupported entity_level: {level}")


def _filter_field(filter_key: str) -> str:
    filters = _filter_registry().get("filters") or {}
    field = (((filters.get(filter_key) or {}).get("works_filter") or {}).get("field") or "").strip()
    if not field:
        raise ValueError(f"OpenAlex field is not configured for filter: {filter_key}")
    return field


@lru_cache(maxsize=1)
def _filter_registry() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "configs" / "openalex_filter_registry.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return payload if isinstance(payload, dict) else {}


def _payload_cost(payload: dict[str, Any]) -> float:
    meta = payload.get("meta") or {}
    try:
        return float(meta.get("cost_usd") or 0)
    except (TypeError, ValueError):
        return 0.0


def _facets_cost(facets: dict[str, Any]) -> float:
    total = 0.0
    for value in facets.values():
        if isinstance(value, dict):
            try:
                total += float(value.get("cost_usd") or 0)
            except (TypeError, ValueError):
                pass
    return total


def _data_root() -> Path:
    configured = os.environ.get("OPENALEX_DSS_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parents[2].parent / "openalex-dss-data").resolve()
