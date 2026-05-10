from __future__ import annotations

import math
import os
import sys
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any
from datetime import datetime, timedelta, timezone

import yaml

from app.core.paths import DATA, ROOT, SRC
from app.services import author_slice
from app.services.work_type_labels import format_work_types

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_dss.openalex import build_filter, cli_download_signature, corpus_signature, download_consistency, download_signature_for_strategy, estimate_works  # noqa: E402


CONFIG_PATH = ROOT / "configs/execution_limits.yaml"


def plan_slice(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = author_slice.config_from_payload({**payload, "workflow_mode": "strict_works"})
    source_strategy = str(payload.get("source_strategy") or payload.get("data_source_id") or "openalex_cli")
    limits = load_execution_limits()
    download_policy = _download_policy(payload, limits)
    refresh_requested = bool(payload.get("refresh_estimate"))
    estimate, estimate_cache = _cached_estimate(cfg, limits, refresh=refresh_requested, api_key=str(payload.get("api_key") or "").strip())
    estimate = _estimate_for_source_strategy(estimate, cfg, source_strategy)

    storage_estimate = storage_estimate_from_openalex_estimate(estimate, download_dir=str(payload.get("download_dir") or ""))
    storage_estimate = apply_estimate_calibration(storage_estimate, estimate)
    decision = choose_strategy(
        estimate_count=int(estimate["estimate_count"]),
        planned_api_requests=int(estimate["api_requests_planned"]),
        estimated_raw_bytes=int(storage_estimate.get("recommended_free_space_bytes") or estimate.get("estimated_cli_metadata_bytes") or estimate["estimated_raw_bytes"]),
        limits=limits,
    )
    if source_strategy in {"openalex_api", "api_cursor_selected_fields"}:
        decision = {**decision, "strategy": "api_cursor_selected_fields", "notebook_policy": "Срез будет скачан через OpenAlex API cursor с select-проекцией. Для очень крупных срезов предпочтительнее локальный snapshot/CLI или уже скачанный dump."}
    elif source_strategy == "ids_then_hydrate":
        decision = {**decision, "strategy": "ids_then_hydrate", "notebook_policy": "Система скачает singleton Works по заранее заданному списку OpenAlex work IDs."}
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
        "source_strategy": source_strategy,
        "estimate": estimate,
        "storage_estimate": storage_estimate,
        "estimate_cache": estimate_cache,
        "decision": decision,
        "download_policy": download_policy,
        "limits": limits,
        "filter_classes": classify_filters(cfg),
    }


def _estimate_for_source_strategy(estimate: dict[str, Any], cfg: Any, source_strategy: str) -> dict[str, Any]:
    source_strategy = str(source_strategy or "openalex_cli")
    signature = download_signature_for_strategy(cfg, source_strategy)
    consistency = download_consistency(cfg, source_strategy)
    signatures = {
        "openalex_cli": cli_download_signature(cfg),
        "openalex_api": download_signature_for_strategy(cfg, "openalex_api"),
        "api_cursor_selected_fields": download_signature_for_strategy(cfg, "api_cursor_selected_fields"),
        "ids_then_hydrate": download_signature_for_strategy(cfg, "ids_then_hydrate"),
    }
    return {
        **estimate,
        "download_signature": signature,
        "download_signatures": signatures,
        "download_consistency": consistency,
        "source_strategy": source_strategy,
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
    _prune_estimate_cache(limits)
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


def _prune_estimate_cache(limits: dict[str, Any]) -> None:
    root = DATA / "cache" / "estimates"
    if not root.is_dir():
        return
    policy = limits.get("storage_policy") if isinstance(limits.get("storage_policy"), dict) else {}
    try:
        limit = max(1, int(policy.get("max_estimate_cache_entries") or 200))
    except (TypeError, ValueError):
        limit = 200
    entries = sorted(root.glob("*.json"), key=lambda path: path.stat().st_mtime if path.exists() else 0)
    if len(entries) <= limit:
        return
    for path in entries[: len(entries) - limit]:
        try:
            path.unlink()
        except OSError:
            pass


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
        "estimated_disk_peak_mb": round(estimated_raw_bytes / (1024 * 1024), 3),
        "complete_slice_required": True,
        "allow_incomplete_preview": False,
        "can_execute": status != "no_data",
        "user_decides_after_estimate": status != "no_data",
        "reasons": reasons,
        "warnings": warnings,
        "notebook_policy": "Планировщик не ставит скрытый локальный лимит. Пользователь принимает решение после прогноза. Уже скачанные локальные срезы используются без API; новая загрузка среза OpenAlex может требовать ключ OpenAlex.",
    }


def storage_estimate_from_openalex_estimate(estimate: dict[str, Any], *, download_dir: str = "") -> dict[str, Any]:
    byte_estimate = estimate.get("byte_estimate") if isinstance(estimate.get("byte_estimate"), dict) else {}
    recommended = byte_estimate.get("recommended_free_space") if isinstance(byte_estimate.get("recommended_free_space"), dict) else {}
    cli_peak = byte_estimate.get("cli_temp_files_peak") if isinstance(byte_estimate.get("cli_temp_files_peak"), dict) else {}
    final_raw = byte_estimate.get("final_raw_jsonl_gz") if isinstance(byte_estimate.get("final_raw_jsonl_gz"), dict) else {}
    parquet = byte_estimate.get("parquet_tables") if isinstance(byte_estimate.get("parquet_tables"), dict) else {}
    recommended_bytes = int(recommended.get("bytes") or estimate.get("estimated_cli_metadata_bytes") or estimate.get("estimated_raw_bytes") or 0)
    base_dir = Path(download_dir).expanduser() if download_dir else DATA
    try:
        usage = shutil.disk_usage(base_dir if base_dir.exists() else base_dir.parent)
        free_bytes = int(usage.free)
    except OSError:
        free_bytes = 0
    enough = bool(free_bytes <= 0 or free_bytes >= recommended_bytes)
    return {
        "schema": "storage_estimate_v1",
        "download_dir": str(base_dir),
        "recommended_free_space_bytes": recommended_bytes,
        "recommended_free_space_mb": round(recommended_bytes / (1024 * 1024), 3),
        "free_space_bytes": free_bytes,
        "free_space_mb": round(free_bytes / (1024 * 1024), 3) if free_bytes else None,
        "free_space_status": "ok" if enough else "insufficient",
        "cli_temp_files_peak_bytes": int(cli_peak.get("p90_bytes") or 0),
        "final_raw_jsonl_gz_bytes": int(final_raw.get("p90_bytes") or 0),
        "parquet_tables_bytes": int(parquet.get("p90_bytes") or 0),
        "confidence": str(byte_estimate.get("confidence") or "low"),
        "message": (
            "Свободного места достаточно для рекомендованного пикового объема."
            if enough
            else "Свободного места меньше рекомендованного пикового объема. Сузьте срез, выберите другой диск или задайте лимит загрузки."
        ),
    }


def apply_estimate_calibration(storage_estimate: dict[str, Any], estimate: dict[str, Any]) -> dict[str, Any]:
    calibration = _calibration_summary()
    multiplier = float(calibration.get("recommended_multiplier") or 1.0)
    if multiplier <= 1.0:
        return {**storage_estimate, "calibration": calibration}
    adjusted = dict(storage_estimate)
    for field in ("recommended_free_space_bytes", "cli_temp_files_peak_bytes", "final_raw_jsonl_gz_bytes", "parquet_tables_bytes"):
        adjusted[field] = int(float(adjusted.get(field) or 0) * multiplier)
    adjusted["recommended_free_space_mb"] = round(int(adjusted.get("recommended_free_space_bytes") or 0) / (1024 * 1024), 3)
    free = int(adjusted.get("free_space_bytes") or 0)
    required = int(adjusted.get("recommended_free_space_bytes") or 0)
    if free > 0 and required > 0:
        adjusted["free_space_status"] = "ok" if free >= required else "insufficient"
    adjusted["calibration"] = calibration
    adjusted["message"] = (
        f"{adjusted.get('message', '')} Применена историческая поправка прогноза x{multiplier:.2f} "
        f"по {int(calibration.get('samples') or 0)} завершенным загрузкам."
    ).strip()
    return adjusted


def record_estimate_calibration(dump_manifest: dict[str, Any], estimate: dict[str, Any]) -> None:
    actual = int(dump_manifest.get("bytes_written") or 0)
    estimated = int(dump_manifest.get("estimated_raw_bytes") or estimate.get("estimated_cli_metadata_bytes") or estimate.get("estimated_raw_bytes") or 0)
    if actual <= 0 or estimated <= 0:
        return
    record = {
        "schema": "download_estimate_calibration_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "slice_id": dump_manifest.get("slice_id"),
        "dump_id": dump_manifest.get("dump_id"),
        "source_mode": dump_manifest.get("source_mode"),
        "records_expected": dump_manifest.get("records_expected"),
        "records_downloaded": dump_manifest.get("records_downloaded"),
        "estimated_bytes": estimated,
        "actual_bytes": actual,
        "ratio": round(actual / estimated, 6),
        "estimate_signature": estimate.get("estimate_signature") or ((dump_manifest.get("signatures") or {}).get("estimate_signature")),
        "download_signature": estimate.get("download_signature") or ((dump_manifest.get("signatures") or {}).get("download_signature")),
    }
    path = _calibration_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _calibration_summary() -> dict[str, Any]:
    path = _calibration_log_path()
    if not path.is_file():
        return {"status": "not_enough_history", "samples": 0, "recommended_multiplier": 1.0}
    ratios: list[float] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[-200:]:
            if not line.strip():
                continue
            record = json.loads(line)
            ratio = float(record.get("ratio") or 0.0)
            if ratio > 0:
                ratios.append(ratio)
    except (OSError, json.JSONDecodeError, ValueError):
        return {"status": "invalid_history", "samples": 0, "recommended_multiplier": 1.0}
    if len(ratios) < 2:
        return {"status": "not_enough_history", "samples": len(ratios), "recommended_multiplier": 1.0}
    ratios.sort()
    index = min(len(ratios) - 1, int(round((len(ratios) - 1) * 0.75)))
    multiplier = max(1.0, min(5.0, ratios[index] * 1.15))
    return {
        "status": "applied",
        "samples": len(ratios),
        "p75_actual_vs_estimated": ratios[index],
        "recommended_multiplier": round(multiplier, 4),
    }


def _calibration_log_path() -> Path:
    return DATA / "cache" / "estimate_calibration" / "download_estimate_calibration.jsonl"


def classify_filters(cfg: Any) -> dict[str, list[str]]:
    pushdown = ["subject", "publication_date", "work_type", "quality_flags"]
    risky_authorship_pushdown: list[str] = []
    if cfg.country_code:
        risky_authorship_pushdown.append("country")
    if cfg.institution_id:
        risky_authorship_pushdown.append("institution")
    if cfg.author_id:
        risky_authorship_pushdown.append("author")
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
        "fetch_pushdown_risky_authorship": risky_authorship_pushdown,
        "local_materialized_filter": [*risky_authorship_pushdown, "source_type", "country_code", "work_type", "publication_date"],
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
