from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from app.core.paths import ROOT, SRC
from app.services import author_slice

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_mvp.openalex import build_filter, estimate_works  # noqa: E402


CONFIG_PATH = ROOT / "configs/execution_limits.yaml"


def plan_slice(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = author_slice.config_from_payload({**payload, "workflow_mode": "strict_works"})
    limits = load_execution_limits()
    download_policy = _download_policy(payload, limits)

    api_key = str(payload.get("api_key") or "").strip()
    old_api_key = os.environ.get(cfg.api_key_env)
    try:
        if api_key:
            os.environ[cfg.api_key_env] = api_key
        estimate = estimate_works(cfg)
    finally:
        if old_api_key is None:
            os.environ.pop(cfg.api_key_env, None)
        else:
            os.environ[cfg.api_key_env] = old_api_key

    decision = choose_strategy(
        estimate_count=int(estimate["estimate_count"]),
        planned_api_requests=int(estimate["api_requests_planned"]),
        estimated_raw_bytes=int(estimate["estimated_raw_bytes"]),
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
        "planner_version": "mvp_query_planner_v1",
        "slice_id": cfg.slice_name,
        "workflow_mode": "strict_works",
        "user_visible_request": {
            "subject": cfg.entity_display_name,
            "subject_level": cfg.entity_level,
            "country_code": cfg.country_code,
            "institution": cfg.institution_display_name,
            "period": f"{cfg.from_publication_date} - {cfg.to_publication_date}",
            "work_type": cfg.work_type,
        },
        "openalex_filter": build_filter(cfg),
        "estimate": estimate,
        "decision": decision,
        "download_policy": download_policy,
        "limits": limits,
        "filter_classes": classify_filters(cfg),
    }


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
            "reasons": ["OpenAlex returned zero works for this filter."],
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
        warnings.append("Estimated corpus is very large. The user should decide whether to download it or narrow the filters.")
    elif estimate_count > medium:
        status = "large_slice"
        strategy = "openalex_cli_large_slice"
        warnings.append("Estimated corpus is large. Review disk space, API budget and expected runtime before downloading.")
    elif estimate_count > small:
        status = "medium_slice"
        warnings.append("Estimated corpus is medium-sized. Download is allowed; review the forecast before proceeding.")

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
        "notebook_policy": "No local hard cap is applied by the planner. The user decides after seeing the forecast. Download uses OpenAlex CLI by default.",
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
