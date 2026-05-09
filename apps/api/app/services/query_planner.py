from __future__ import annotations

import math
import os
import sys
import hashlib
import json
from pathlib import Path
from typing import Any
from datetime import datetime, timedelta, timezone

import yaml

from app.core.paths import DATA, ROOT, SRC
from app.services import author_slice
from app.services.work_type_labels import format_work_types

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_dss.openalex import build_filter, cli_download_signature, corpus_signature, estimate_works  # noqa: E402


CONFIG_PATH = ROOT / "configs/execution_limits.yaml"


def plan_slice(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = author_slice.config_from_payload({**payload, "workflow_mode": "strict_works"})
    limits = load_execution_limits()
    download_policy = _download_policy(payload, limits)
    refresh_requested = bool(payload.get("refresh_estimate"))
    estimate, estimate_cache = _cached_estimate(cfg, limits, refresh=refresh_requested, api_key=str(payload.get("api_key") or "").strip())

    decision = choose_strategy(
        estimate_count=int(estimate["estimate_count"]),
        planned_api_requests=int(estimate["api_requests_planned"]),
        estimated_raw_bytes=int(estimate.get("estimated_cli_metadata_bytes") or estimate["estimated_raw_bytes"]),
        limits=limits,
    )
    consistency = estimate.get("download_consistency") or {}
    if consistency.get("compatible") is False:
        reasons = [str(item) for item in consistency.get("reasons") or [] if str(item).strip()]
        decision = {
            **decision,
            "status": "unsupported_cli_filter",
            "strategy": "refine_slice",
            "can_execute": False,
            "user_decides_after_estimate": False,
            "reasons": [*(decision.get("reasons") or []), *reasons],
        }
    return {
        "status": "ok",
        "planner_schema": "query_planner",
        "slice_id": cfg.slice_name,
        "workflow_mode": "strict_works",
        "user_visible_request": {
            "subject": cfg.entity_display_name,
            "subject_level": cfg.entity_level,
            "country_code": cfg.country_code,
            "institution": cfg.institution_display_name,
            "period": f"{cfg.from_publication_date} - {cfg.to_publication_date}",
            "work_type": format_work_types(cfg.work_type),
        },
        "openalex_filter": build_filter(cfg),
        "estimate": estimate,
        "estimate_cache": estimate_cache,
        "decision": decision,
        "download_policy": download_policy,
        "limits": limits,
        "filter_classes": classify_filters(cfg),
    }


def _cached_estimate(cfg: Any, limits: dict[str, Any], *, refresh: bool = False, api_key: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
    key = _estimate_cache_key(cfg)
    path = _estimate_cache_path(key)
    ttl_hours = _estimate_cache_ttl_hours(limits)
    if not refresh and path.is_file():
        cached = _read_json(path)
        created = _parse_dt(str(cached.get("created_at") or ""))
        estimate = cached.get("estimate") if isinstance(cached.get("estimate"), dict) else None
        if estimate and created and datetime.now(timezone.utc) - created <= timedelta(hours=ttl_hours):
            return estimate, {"status": "hit", "key": key, "ttl_hours": ttl_hours, "created_at": cached.get("created_at")}

    estimate = _fetch_estimate(cfg, api_key=api_key)
    doc = {"schema": "openalex_estimate_cache", "key": key, "created_at": datetime.now(timezone.utc).isoformat(), "estimate": estimate}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return estimate, {"status": "refresh" if refresh else "miss", "key": key, "ttl_hours": ttl_hours, "created_at": doc["created_at"]}


def _fetch_estimate(cfg: Any, *, api_key: str = "") -> dict[str, Any]:
    old_api_key = os.environ.get(cfg.api_key_env)
    try:
        if api_key:
            os.environ[cfg.api_key_env] = api_key
        return estimate_works(cfg)
    finally:
        if old_api_key is None:
            os.environ.pop(cfg.api_key_env, None)
        else:
            os.environ[cfg.api_key_env] = old_api_key


def _estimate_cache_key(cfg: Any) -> str:
    payload = {
        "corpus_signature": corpus_signature(cfg),
        "download_signature": cli_download_signature(cfg),
        "filter": build_filter(cfg),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def _estimate_cache_path(key: str) -> Path:
    return DATA / "cache" / "estimates" / f"{key}.json"


def _estimate_cache_ttl_hours(limits: dict[str, Any]) -> int:
    policy = limits.get("storage_policy") if isinstance(limits.get("storage_policy"), dict) else {}
    try:
        return max(1, int(policy.get("estimate_cache_ttl_hours") or 24))
    except (TypeError, ValueError):
        return 24


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def choose_strategy(
    *,
    estimate_count: int,
    planned_api_requests: int,
    estimated_raw_bytes: int,
    limits: dict[str, Any],
) -> dict[str, Any]:
    thresholds = limits.get("planner_thresholds", {})
    small = int(thresholds.get("small_slice_works", 50_000))
    medium = int(thresholds.get("medium_slice_works", 300_000))
    hard_stop = int(thresholds.get("hard_stop_works", 1_000_000))

    reasons: list[str] = []
    warnings: list[str] = []
    status = "can_fetch"
    strategy = "openalex_cli_slice"

    if estimate_count <= 0:
        return {
            "status": "no_data",
            "strategy": "do_not_fetch",
            "reasons": ["OpenAlex вернул 0 работ для выбранных фильтров."],
            "warnings": [],
            "records_to_fetch": 0,
            "api_requests_planned": planned_api_requests,
            "estimated_raw_mb": 0,
            "complete_slice_required": True,
            "allow_incomplete_preview": False,
            "can_execute": False,
            "user_decides_after_estimate": False,
        }
    if estimate_count > hard_stop:
        status = "very_large_slice"
        strategy = "openalex_cli_large_slice"
        warnings.append("Срез очень большой. Перед скачиванием стоит сузить фильтры или отдельно подтвердить место на диске и время выполнения.")
    elif estimate_count > medium:
        status = "large_slice"
        strategy = "openalex_cli_large_slice"
        warnings.append("Срез большой. Перед скачиванием проверьте место на диске и ожидаемое время выполнения.")
    elif estimate_count > small:
        status = "medium_slice"
        warnings.append("Срез среднего размера. Скачивание разрешено, но перед запуском проверьте прогноз объема.")

    return {
        "status": status,
        "strategy": strategy,
        "records_to_fetch": estimate_count,
        "api_requests_planned": planned_api_requests,
        "estimated_raw_mb": round(estimated_raw_bytes / (1024 * 1024), 3),
        "complete_slice_required": True,
        "allow_incomplete_preview": False,
        "can_execute": status != "no_data",
        "user_decides_after_estimate": status != "no_data",
        "reasons": reasons,
        "warnings": warnings,
        "notebook_policy": "Планировщик не ставит скрытый локальный лимит. Пользователь принимает решение после прогноза. Уже скачанные локальные срезы используются без API; новая загрузка среза OpenAlex может требовать ключ OpenAlex.",
    }


def classify_filters(cfg: Any) -> dict[str, list[str]]:
    pushdown = ["subject", "publication_date", "work_type", "quality_flags"]
    if cfg.country_code:
        pushdown.append("country")
    if cfg.institution_id:
        pushdown.append("institution")
    if cfg.author_id:
        pushdown.append("author")
    if cfg.source_id:
        pushdown.append("source")
    if cfg.language:
        pushdown.append("language")
    if cfg.open_access_is_oa:
        pushdown.append("open_access")
    if cfg.min_cited_by_count:
        pushdown.append("min_work_citations")
    return {
        "openalex_pushdown": pushdown,
        "local_pushdown": ["source_type", "country_code", "work_type", "publication_date"],
        "derived_after_metrics": ["min_author_publications", "min_local_h", "rank_by_metric"],
        "ui_only_presets": ["domain_presets", "organization_presets"],
        "unsupported_not_exposed": ["city", "gender", "age"],
    }


def load_execution_limits() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {
            "execution_limits": {
                "max_api_requests_per_job": 2_000,
            },
            "planner_thresholds": {
                "small_slice_works": 50_000,
                "medium_slice_works": 300_000,
                "hard_stop_works": 1_000_000,
            },
        }
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def planned_pages(records: int, per_page: int) -> int:
    return math.ceil(max(0, records) / max(1, per_page))


def _download_policy(payload: dict[str, Any], limits: dict[str, Any]) -> dict[str, Any]:
    raw_policy = payload.get("download_policy") if isinstance(payload.get("download_policy"), dict) else {}
    allowed = {key: value for key, value in raw_policy.items() if key in {"complete_slice_required", "allow_incomplete_preview"}}
    return {
        "complete_slice_required": True,
        "allow_incomplete_preview": False,
        "user_controls_download_after_estimate": True,
        **allowed,
    }
