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
    max_raw_bytes = int(download_policy["max_raw_bytes"])

    api_key = str(payload.get("api_key") or "").strip()
    old_api_key = os.environ.get(cfg.api_key_env)
    try:
        if api_key:
            os.environ[cfg.api_key_env] = api_key
        estimate = estimate_works(
            cfg,
            max_dump_bytes=max_raw_bytes,
            record_budget=download_policy["max_records_to_download"],
        )
    finally:
        if old_api_key is None:
            os.environ.pop(cfg.api_key_env, None)
        else:
            os.environ[cfg.api_key_env] = old_api_key

    decision = choose_strategy(
        estimate_count=int(estimate["estimate_count"]),
        max_records_to_download=int(download_policy["max_records_to_download"]),
        planned_api_requests=int(estimate["api_requests_planned"]),
        estimated_raw_bytes=int(estimate["estimated_raw_bytes"]),
        max_raw_bytes=max_raw_bytes,
        complete_slice_required=bool(download_policy["complete_slice_required"]),
        allow_incomplete_preview=bool(download_policy["allow_incomplete_preview"]),
        limits=limits,
    )
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
    max_records_to_download: int,
    planned_api_requests: int,
    estimated_raw_bytes: int,
    max_raw_bytes: int,
    complete_slice_required: bool = True,
    allow_incomplete_preview: bool = False,
    limits: dict[str, Any],
) -> dict[str, Any]:
    execution = limits.get("execution_limits", {})
    thresholds = limits.get("planner_thresholds", {})
    small = int(thresholds.get("small_slice_works", 50_000))
    medium = int(thresholds.get("medium_slice_works", 300_000))
    hard_stop = int(thresholds.get("hard_stop_works", 1_000_000))
    max_requests = int(execution.get("max_api_requests_per_job", 2_000))
    hard_works = int(execution.get("max_works_per_slice_hard", 300_000))

    reasons: list[str] = []
    warnings: list[str] = []
    status = "can_fetch"
    strategy = "api_mini_slice"

    if estimate_count <= 0:
        return {
            "status": "no_data",
            "strategy": "do_not_fetch",
            "reasons": ["OpenAlex returned zero works for this filter."],
            "warnings": [],
        }
    if estimate_count > hard_stop and max_records_to_download > small:
        status = "blocked"
        strategy = "refine_slice"
        reasons.append("Estimated corpus is above the hard stop threshold.")
    elif estimate_count > medium:
        status = "should_narrow"
        strategy = "limited_api_mini_slice" if max_records_to_download <= small else "refine_slice"
        warnings.append("Estimated corpus is large; narrow period, subject or work types for a dissertation-grade local run.")
    elif estimate_count > small:
        status = "can_fetch_with_warning"
        strategy = "limited_api_mini_slice"
        warnings.append("Estimated corpus is medium-sized; check the technical download budget before creating a local package.")

    if max_records_to_download > hard_works:
        status = "blocked"
        strategy = "refine_slice"
        reasons.append("Requested technical download cap exceeds local hard limit.")
    if planned_api_requests > max_requests:
        status = "blocked"
        strategy = "refine_slice"
        reasons.append("Planned API request count exceeds per-job limit.")
    if complete_slice_required and estimate_count > max_records_to_download:
        status = "blocked"
        strategy = "refine_slice"
        reasons.append("Complete slice requires more records than the technical download cap allows.")
    elif estimate_count > max_records_to_download:
        status = "preview_only"
        strategy = "incomplete_preview"
        warnings.append("This will be an incomplete technical preview and cannot be used for final conclusions.")
    if estimated_raw_bytes > max_raw_bytes:
        if complete_slice_required:
            status = "blocked"
            strategy = "refine_slice"
            reasons.append("Estimated raw size exceeds the selected local storage budget. Narrow the slice or raise the technical budget.")
        elif allow_incomplete_preview:
            status = "preview_only"
            strategy = "incomplete_preview"
            warnings.append("Download can stop by max_raw_bytes; the result is not a complete scientific slice.")
        else:
            status = "blocked"
            strategy = "refine_slice"
            reasons.append("Estimated raw size exceeds the selected local storage budget.")

    return {
        "status": status,
        "strategy": strategy,
        "records_to_fetch": estimate_count if complete_slice_required else min(estimate_count, max_records_to_download),
        "api_requests_planned": planned_api_requests,
        "estimated_raw_mb": round(estimated_raw_bytes / (1024 * 1024), 3),
        "max_raw_mb": round(max_raw_bytes / (1024 * 1024), 3),
        "max_dump_mb": round(max_raw_bytes / (1024 * 1024), 3),
        "complete_slice_required": complete_slice_required,
        "allow_incomplete_preview": allow_incomplete_preview,
        "can_execute": status not in {"blocked", "no_data"},
        "reasons": reasons,
        "warnings": warnings,
        "notebook_policy": "API mini-slice first; full snapshot is a future server/S3 mode.",
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
                "max_works_per_slice_default": 50_000,
                "max_works_per_slice_hard": 300_000,
                "max_raw_download_mb_default": 300,
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
    execution = limits.get("execution_limits", {})
    raw_policy = payload.get("download_policy") if isinstance(payload.get("download_policy"), dict) else {}
    default_records = int(execution.get("max_works_per_slice_default", 50_000))
    default_raw_bytes = int(execution.get("max_raw_download_mb_default", 300)) * 1024 * 1024
    max_records = raw_policy.get("max_records_to_download", payload.get("max_records_to_download", payload.get("max_works", default_records)))
    max_raw_bytes = raw_policy.get("max_raw_bytes", payload.get("max_raw_bytes", payload.get("max_dump_bytes", default_raw_bytes)))
    return {
        "max_records_to_download": int(max_records or default_records),
        "max_raw_bytes": int(max_raw_bytes or default_raw_bytes),
        "complete_slice_required": bool(raw_policy.get("complete_slice_required", payload.get("complete_slice_required", True))),
        "allow_incomplete_preview": bool(raw_policy.get("allow_incomplete_preview", payload.get("allow_incomplete_preview", False))),
    }
