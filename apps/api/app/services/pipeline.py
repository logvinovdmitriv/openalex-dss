from __future__ import annotations

import gzip
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from app.core.paths import DATA, JSON_FILES, PARQUET_TABLE_FILES, ROOT, SRC, TABLE_FILES
from app.providers import openalex_cli_provider
from app.services import author_slice
from app.services.filesystem import file_profile, resolve_safe_path
from app.services import metadata_store, query_planner, reports

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_mvp.config import replace_config, write_config  # noqa: E402
from openalex_mvp.io_utils import write_json  # noqa: E402
from openalex_mvp.metrics import NATIVE_AUTHOR_METRICS, build_author_work_metrics, compute_author_profile_indices, compute_indices  # noqa: E402
from openalex_mvp.normalize import normalize_authors_raw, normalize_raw  # noqa: E402
from openalex_mvp.openalex import fetch_authors, fetch_works, fetch_works_slice_dump  # noqa: E402
from openalex_mvp.passports import build_passports  # noqa: E402
from openalex_mvp.ranking import build_ratings  # noqa: E402
from openalex_mvp.stats import analyze_stats  # noqa: E402
from openalex_mvp.theory import analyze_theory  # noqa: E402


GENERATED_FILES = [
    DATA / "raw/authors_raw.jsonl",
    DATA / "raw/works_raw.jsonl",
    *TABLE_FILES.values(),
    *PARQUET_TABLE_FILES.values(),
    *JSON_FILES.values(),
    DATA / "results/stats_summary.json",
    DATA / "results/theory_validation.json",
    DATA / "results/theory_top1_sensitivity.csv",
    DATA / "results/theory_fraction_mode_sensitivity.csv",
]


def recalculate(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(payload)
    _write_runtime_config(cfg)
    if cfg.fraction_mode_default == "openalex_native" and (DATA / "normalized/author_profiles_flat.csv").exists():
        _run_compute_author_profiles(cfg)
    else:
        _run_compute(cfg)
    _write_pipeline_summary("recalculate", cfg, payload)
    return {"status": "ok", "mode": "recalculate"}


def fetch_and_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Legacy direct API fetch kept for compatibility.

    The UI uses fetch_slice_dump -> import_local_file so dissertation runs stay
    dump-first and reproducible.
    """
    cfg = _cfg(payload)
    _write_runtime_config(cfg)
    api_key = str(payload.get("api_key") or "").strip()
    old = os.environ.get(cfg.api_key_env)
    try:
        if api_key:
            os.environ[cfg.api_key_env] = api_key
        fetch_works(cfg, DATA / "raw/works_raw.jsonl", DATA / "passports/fetch_meta.json", cfg.max_works)
    finally:
        if old is None:
            os.environ.pop(cfg.api_key_env, None)
        else:
            os.environ[cfg.api_key_env] = old
    for stale in (DATA / "raw/authors_raw.jsonl", DATA / "normalized/author_profiles_flat.csv"):
        if stale.exists():
            stale.unlink()
    normalize_raw(
        DATA / "raw/works_raw.jsonl",
        DATA / "normalized/works_flat.csv",
        DATA / "normalized/authorships_flat.csv",
        DATA / "passports/quality_report.json",
        DATA / "normalized/work_topics_flat.csv",
    )
    _run_compute(cfg)
    _write_pipeline_summary("fetch_and_run", cfg, payload)
    return {"status": "ok", "mode": "fetch_and_run", "deprecated": True, "preferred_flow": "fetch_slice_dump_then_import_file"}


def fetch_slice_dump(payload: dict[str, Any], progress_callback: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    cfg = _cfg({**payload, "workflow_mode": "strict_works"})
    _write_runtime_config(cfg)
    api_key = str(payload.get("api_key") or "").strip()
    download_policy = _download_policy(payload)
    max_dump_bytes = int(download_policy["max_raw_bytes"])
    plan = query_planner.plan_slice({**payload, "workflow_mode": "strict_works"})
    decision = plan.get("decision") or {}
    if decision.get("status") == "blocked":
        raise ValueError("Срез слишком тяжелый для локального запуска: " + "; ".join(decision.get("reasons") or []))
    if decision.get("status") == "no_data":
        _write_pipeline_summary("fetch_slice_dump", cfg, {**payload, "query_plan": plan, "dump": {"no_data": True}})
        return {"status": "ok", "mode": "fetch_slice_dump", "query_plan": plan, "dump": {"no_data": True, "records_downloaded": 0}}
    old = os.environ.get(cfg.api_key_env)
    try:
        if api_key:
            os.environ[cfg.api_key_env] = api_key
        if str(payload.get("source_strategy") or "") == "openalex_cli":
            passport = openalex_cli_provider.download_works_metadata(
                cfg,
                api_key=api_key,
                out_dir=DATA / "raw/openalex_cli" / cfg.slice_name,
                progress_callback=progress_callback,
            )
        else:
            passport = fetch_works_slice_dump(
                cfg,
                DATA / "raw/openalex_slices" / cfg.slice_name,
                max_records=int(download_policy["max_records_to_download"]),
                max_bytes=max_dump_bytes,
                complete_slice_required=bool(download_policy["complete_slice_required"]),
                allow_incomplete_preview=bool(download_policy["allow_incomplete_preview"]),
                progress_callback=progress_callback,
            )
        passport["query_plan"] = plan
        raw_jsonl = passport.get("raw_jsonl")
        if raw_jsonl:
            write_json(Path(str(raw_jsonl)).with_name("slice_passport.json"), passport)
        metadata_store.record_slice_dump(passport)
    finally:
        if old is None:
            os.environ.pop(cfg.api_key_env, None)
        else:
            os.environ[cfg.api_key_env] = old
    raw_jsonl = passport.get("raw_jsonl")
    summary_payload = {**payload, "dump": passport, "query_plan": plan}
    if raw_jsonl:
        summary_payload["source_file"] = file_profile(raw_jsonl)
    _write_pipeline_summary("fetch_slice_dump", cfg, summary_payload)
    return {"status": "ok", "mode": "fetch_slice_dump", "query_plan": plan, "dump": passport}


def fetch_author_preview(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg({**payload, "workflow_mode": "author_preview", "filter_mode": "primary_topic"})
    if cfg.entity_level != "topic":
        raise ValueError("Быстрая витрина Authors API поддерживает только выбранную тему OpenAlex, например topic T13674")
    api_key = str(payload.get("api_key") or "").strip()
    old = os.environ.get(cfg.api_key_env)
    try:
        if api_key:
            os.environ[cfg.api_key_env] = api_key
        meta = fetch_authors(cfg, DATA / "raw/authors_raw.jsonl", DATA / "passports/author_preview_meta.json", cfg.max_works)
    finally:
        if old is None:
            os.environ.pop(cfg.api_key_env, None)
        else:
            os.environ[cfg.api_key_env] = old
    quality = normalize_authors_raw(
        DATA / "raw/authors_raw.jsonl",
        DATA / "normalized/author_profiles_flat.csv",
        DATA / "passports/author_preview_quality.json",
    )
    write_json(
        JSON_FILES["author_preview_meta"],
        {
            **meta,
            "source_role": "fast_author_preview",
            "slice": author_slice.preview(config_to_payload(cfg))["slice"],
            "usage_policy": "Только предварительный отбор и просмотр; математические выводы строятся по локальным works-based индексам.",
        },
    )
    return {"status": "ok", "mode": "fetch_author_preview", "meta": meta, "quality": quality}


def import_local_file(payload: dict[str, Any]) -> dict[str, Any]:
    source_path = str(payload.get("source_path") or "").strip()
    if not source_path:
        raise ValueError("source_path is required")
    source = resolve_safe_path(source_path)
    if not (source.name.endswith(".jsonl") or source.name.endswith(".jsonl.gz")):
        raise ValueError("Only OpenAlex JSONL or JSONL.GZ dumps are importable in this pipeline")

    cfg = _cfg(payload)
    _write_runtime_config(cfg)
    profile = file_profile(source)
    if int(profile.get("bytes") or 0) == 0:
        raise ValueError(
            "Локальный дамп пуст: OpenAlex вернул 0 работ для выбранных фильтров. "
            "Расширьте период, уберите организацию или выберите более широкую предметную область."
        )
    if _looks_like_author_dump(source):
        quality = normalize_authors_raw(source, DATA / "normalized/author_profiles_flat.csv", DATA / "passports/quality_report.json")
        write_json(
            DATA / "passports/fetch_meta.json",
            {
                "source_type": "local_file",
                "source_entity": "authors",
                "source_file": profile,
                "fetched_authors": quality.get("raw_authors"),
                "total_available": quality.get("raw_authors"),
                "filter": "локальный импорт дампа OpenAlex Authors",
                "used_api_key": False,
            },
        )
        _run_compute_author_profiles(cfg)
    else:
        quality = normalize_raw(
            source,
            DATA / "normalized/works_flat.csv",
            DATA / "normalized/authorships_flat.csv",
            DATA / "passports/quality_report.json",
            DATA / "normalized/work_topics_flat.csv",
        )
        write_json(
            DATA / "passports/fetch_meta.json",
            {
                "source_type": "local_file",
                "source_entity": "works",
                "source_file": profile,
                "fetched_works": quality.get("raw_works"),
                "total_available": quality.get("raw_works"),
                "filter": "локальный импорт дампа OpenAlex Works",
                "used_api_key": False,
            },
        )
        _run_compute(cfg)
    _write_pipeline_summary("import_local_file", cfg, {**payload, "source_file": profile})
    return {"status": "ok", "mode": "import_local_file", "source": profile}


def preview(payload: dict[str, Any]) -> dict[str, Any]:
    return author_slice.preview(payload)


def clear_generated_data() -> dict[str, Any]:
    removed: list[str] = []
    for path in GENERATED_FILES:
        if path.exists() and path.is_file():
            path.unlink()
            removed.append(_display_path(path))
    for base in (DATA / "checksums", DATA / "curated", DATA / "reports"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                path.unlink()
                removed.append(_display_path(path))
    for fig in (DATA / "results/figures").glob("*"):
        if fig.is_file():
            fig.unlink()
            removed.append(_display_path(fig))
    return {"status": "ok", "mode": "clear_generated_data", "removed": removed}


def _run_compute(cfg: Any) -> None:
    build_author_work_metrics(DATA / "normalized/works_flat.csv", DATA / "normalized/authorships_flat.csv", DATA / "marts/author_work_metrics.csv", cfg.fraction_modes)
    compute_indices(
        DATA / "marts/author_work_metrics.csv",
        DATA / "results/author_indices.csv",
        cfg.iupv_n0,
        cfg.iupv_lambda,
        cfg.lrdi_p0,
        cfg.lrdi_lambda,
        cfg.analysis_year,
    )
    build_ratings(DATA / "results/author_indices.csv", DATA / "results/rating_positions.csv")
    analyze_stats(DATA / "results/author_indices.csv", DATA / "results/rating_positions.csv", DATA / "results/figures", DATA / "results/stats_summary.json")
    analyze_theory(
        DATA / "marts/author_work_metrics.csv",
        DATA / "results/author_indices.csv",
        DATA / "results/theory_validation.json",
        DATA / "results",
        cfg.iupv_n0,
        cfg.iupv_lambda,
        cfg.lrdi_p0,
        cfg.lrdi_lambda,
        cfg.analysis_year,
        cfg.fraction_mode_default,
    )
    build_passports(cfg, ROOT, DATA / "passports")
    reports.build_report_bundle(metric="islv", fraction_mode=cfg.fraction_mode_default, limit=100)


def _run_compute_author_profiles(cfg: Any) -> None:
    compute_author_profile_indices(DATA / "normalized/author_profiles_flat.csv", DATA / "results/author_indices.csv", cfg.fraction_mode_default)
    build_ratings(DATA / "results/author_indices.csv", DATA / "results/rating_positions.csv", NATIVE_AUTHOR_METRICS)
    analyze_stats(
        DATA / "results/author_indices.csv",
        DATA / "results/rating_positions.csv",
        DATA / "results/figures",
        DATA / "results/stats_summary.json",
        NATIVE_AUTHOR_METRICS,
    )
    write_json(
        DATA / "results/theory_validation.json",
        {
            "theory_version": "openalex_author_native",
            "metric_source": "OpenAlex Author object",
            "metrics": list(NATIVE_AUTHOR_METRICS),
            "interpretation_notes": [
                "Этот режим оставлен только для совместимости с локальными OpenAlex Authors dumps.",
                "Основной UI СППР использует Works/Authorships pipeline и фракционные авторские индексы.",
            ],
        },
    )
    build_passports(cfg, ROOT, DATA / "passports")


def _cfg(payload: dict[str, Any]) -> Any:
    return author_slice.config_from_payload(payload)


def _display_path(path: Any) -> str:
    resolved = path.resolve()
    if resolved == DATA.resolve() or DATA.resolve() in resolved.parents:
        return str(os.path.join("data", str(resolved.relative_to(DATA.resolve()))))
    if resolved == ROOT.resolve() or ROOT.resolve() in resolved.parents:
        return str(resolved.relative_to(ROOT.resolve()))
    return str(resolved)


def _write_pipeline_summary(mode: str, cfg: Any, payload: dict[str, Any]) -> None:
    doc = author_slice.preview(config_to_payload(cfg))
    doc["mode"] = mode
    doc["status"] = "ok"
    doc["api_key_used"] = bool(str(payload.get("api_key") or "").strip())
    if payload.get("source_file"):
        doc["source_file"] = payload["source_file"]
    if payload.get("dump"):
        doc["dump"] = payload["dump"]
    write_json(JSON_FILES["pipeline"], doc)


def config_to_payload(cfg: Any) -> dict[str, Any]:
    return {
        "entity_level": cfg.entity_level,
        "entity_id_short": cfg.entity_id_short,
        "entity_id_full": cfg.entity_id_full,
        "entity_display_name": cfg.entity_display_name,
        "workflow_mode": cfg.workflow_mode,
        "filter_mode": cfg.filter_mode,
        "keyword_id": cfg.keyword_id,
        "keyword_display_name": cfg.keyword_display_name,
        "text_search_query": cfg.text_search_query,
        "raw_openalex_filter": cfg.raw_openalex_filter,
        "author_id": cfg.author_id,
        "author_display_name": cfg.author_display_name,
        "author_orcid": cfg.author_orcid,
        "institution_id": cfg.institution_id,
        "institution_display_name": cfg.institution_display_name,
        "institution_ror": cfg.institution_ror,
        "source_id": cfg.source_id,
        "source_display_name": cfg.source_display_name,
        "source_type": cfg.source_type,
        "language": cfg.language,
        "open_access_is_oa": cfg.open_access_is_oa,
        "has_abstract": cfg.has_abstract,
        "min_cited_by_count": cfg.min_cited_by_count,
        "doi": cfg.doi,
        "affiliation_mode": cfg.affiliation_mode,
        "country_code": cfg.country_code,
        "from_publication_date": cfg.from_publication_date,
        "to_publication_date": cfg.to_publication_date,
        "work_type": cfg.work_type,
        "exclude_retracted": cfg.exclude_retracted,
        "exclude_paratext": cfg.exclude_paratext,
        "include_xpac": cfg.include_xpac,
        "sort": cfg.sort,
        "max_works": cfg.max_works,
        "per_page": cfg.per_page,
        "fraction_modes": list(cfg.fraction_modes),
        "fraction_mode_default": cfg.fraction_mode_default,
        "iupv_n0": cfg.iupv_n0,
        "iupv_lambda": cfg.iupv_lambda,
        "lrdi_p0": cfg.lrdi_p0,
        "lrdi_lambda": cfg.lrdi_lambda,
        "analysis_year": cfg.analysis_year,
    }


def _write_runtime_config(cfg: Any) -> None:
    write_config(cfg, DATA / "runtime/slice_config.yaml")


def _download_policy(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("download_policy") if isinstance(payload.get("download_policy"), dict) else {}
    max_records = raw.get("max_records_to_download", payload.get("max_records_to_download", payload.get("max_works", 50_000)))
    max_raw_bytes = raw.get("max_raw_bytes", payload.get("max_raw_bytes", payload.get("max_dump_bytes", 500 * 1024 * 1024)))
    return {
        "max_records_to_download": int(max_records or 50_000),
        "max_raw_bytes": int(max_raw_bytes or 500 * 1024 * 1024),
        "complete_slice_required": bool(raw.get("complete_slice_required", payload.get("complete_slice_required", True))),
        "allow_incomplete_preview": bool(raw.get("allow_incomplete_preview", payload.get("allow_incomplete_preview", False))),
    }


def _looks_like_author_dump(path: Any) -> bool:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                return False
            return "works_count" in obj and "summary_stats" in obj and "authorships" not in obj
    return False
