from __future__ import annotations

import os
import shutil
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
from openalex_mvp.metrics import build_author_work_metrics, compute_indices  # noqa: E402
from openalex_mvp.normalize import normalize_raw  # noqa: E402
from openalex_mvp.passports import build_passports  # noqa: E402
from openalex_mvp.ranking import build_ratings  # noqa: E402
from openalex_mvp.stats import analyze_stats  # noqa: E402
from openalex_mvp.theory import analyze_theory  # noqa: E402


GENERATED_FILES = [
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
    run_id = str(payload.get("run_id") or cfg.slice_name or "recalculate")
    dump_id = str(payload.get("dump_id") or _dump_id_from_payload(payload) or cfg.slice_name)
    _run_compute(cfg, run_id=run_id, dump_id=dump_id)
    archive = _archive_run_artifacts(cfg, {**payload, "run_id": run_id, "dump_id": dump_id})
    _write_pipeline_summary("recalculate", cfg, payload)
    return {"status": "ok", "mode": "recalculate", "archive": archive}


def fetch_slice_dump(payload: dict[str, Any], progress_callback: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    cfg = _cfg({**payload, "workflow_mode": "strict_works"})
    _write_runtime_config(cfg)
    api_key = str(payload.get("api_key") or "").strip()
    plan = query_planner.plan_slice({**payload, "workflow_mode": "strict_works"})
    decision = plan.get("decision") or {}
    accepted_signature = str(payload.get("accepted_estimate_signature") or "").strip()
    current_signature = str(((plan.get("estimate") or {}).get("estimate_signature") or "")).strip()
    if accepted_signature and current_signature and accepted_signature != current_signature:
        raise ValueError("Параметры среза изменились после оценки. Обновите оценку и подтвердите скачивание заново.")
    if decision.get("status") == "no_data":
        _write_pipeline_summary("fetch_slice_dump", cfg, {**payload, "query_plan": plan, "dump": {"no_data": True}})
        return {"status": "ok", "mode": "fetch_slice_dump", "query_plan": plan, "dump": {"no_data": True, "records_downloaded": 0}}
    if decision.get("can_execute") is False:
        raise ValueError("; ".join(decision.get("reasons") or []) or "Срез нельзя скачать через текущий OpenAlex CLI plan.")
    old = os.environ.get(cfg.api_key_env)
    try:
        if api_key:
            os.environ[cfg.api_key_env] = api_key
        if str(payload.get("source_strategy") or "openalex_cli") != "openalex_cli":
            raise ValueError("Скачивание среза выполняется через установленный OpenAlex CLI. API используется только для оценки и справочников.")
        passport = openalex_cli_provider.download_works_metadata(
            cfg,
            api_key=api_key,
            out_dir=DATA / "raw/openalex_cli" / cfg.slice_name,
            estimate=plan.get("estimate") or {},
            progress_callback=progress_callback,
        )
        passport["query_plan"] = plan
        if not passport.get("dump_id"):
            checksum = str(passport.get("raw_jsonl_sha256") or "")
            passport["dump_id"] = f"dump_{checksum[:16]}" if checksum else f"dump_{cfg.slice_name}"
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
    dump_id = str(payload.get("dump_id") or _dump_id_from_payload({"source_file": profile}) or cfg.slice_name)
    if int(profile.get("bytes") or 0) == 0:
        raise ValueError(
            "Локальный дамп пуст: OpenAlex вернул 0 работ для выбранных фильтров. "
            "Расширьте период, уберите организацию или выберите более широкую предметную область."
        )
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
    _run_compute(cfg, run_id=str(payload.get("run_id") or "local_file"), dump_id=dump_id)
    archive = _archive_run_artifacts(cfg, {**payload, "source_file": profile, "dump_id": dump_id})
    _write_pipeline_summary("import_local_file", cfg, {**payload, "source_file": profile, "archive": archive})
    return {"status": "ok", "mode": "import_local_file", "source": profile, "archive": archive}


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


def _run_compute(cfg: Any, *, run_id: str = "base", dump_id: str = "") -> None:
    build_author_work_metrics(DATA / "normalized/works_flat.csv", DATA / "normalized/authorships_flat.csv", DATA / "marts/author_work_metrics.csv", cfg.fraction_modes, run_id=run_id)
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
    build_passports(cfg, ROOT, DATA / "passports", run_id=run_id, dump_id=dump_id)
    reports.build_report_bundle(metric="islv", fraction_mode=cfg.fraction_mode_default, limit=100)


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


def _archive_run_artifacts(cfg: Any, payload: dict[str, Any]) -> dict[str, Any]:
    run_id = _safe_id(str(payload.get("run_id") or "latest"))
    dump_id = _safe_id(str(payload.get("dump_id") or _dump_id_from_payload(payload) or cfg.slice_name))
    run_dir = DATA / "runs" / run_id
    dump_dir = DATA / "dumps" / dump_id
    tables_dir = DATA / "tables" / dump_id
    copied: dict[str, str] = {}

    for base in (run_dir, dump_dir, tables_dir):
        base.mkdir(parents=True, exist_ok=True)

    manifest = {
        "run_id": run_id,
        "dump_id": dump_id,
        "slice_id": cfg.slice_name,
        "source_file": payload.get("source_file"),
        "dump_manifest": payload.get("dump_manifest"),
        "latest_view_note": "Global normalized/results paths are only the UI latest-view; reproducible artifacts are archived under this run_id and dump_id.",
    }
    write_json(run_dir / "metric_run.json", manifest)
    write_json(dump_dir / "dump_manifest.json", payload.get("dump_manifest") or manifest)

    run_artifacts = {
        **{f"tables/{name}{Path(path).suffix}": path for name, path in TABLE_FILES.items()},
        **{f"tables/{name}{Path(path).suffix}": path for name, path in PARQUET_TABLE_FILES.items()},
        **{f"passports/{name}.json": path for name, path in JSON_FILES.items()},
        "passports/slice_passport.json": DATA / "passports/slice_passport.json",
        "passports/calculation_passport.json": DATA / "passports/calculation_passport.json",
        "passports/quality_report.json": DATA / "passports/quality_report.json",
    }
    for rel, path in run_artifacts.items():
        source = Path(path)
        if source.is_file():
            target = run_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied[rel] = str(target)

    dump_tables = {
        "works.parquet": PARQUET_TABLE_FILES.get("works"),
        "authorships.parquet": PARQUET_TABLE_FILES.get("authorships"),
        "work_topics.parquet": PARQUET_TABLE_FILES.get("work_topics"),
        "author_work.parquet": PARQUET_TABLE_FILES.get("author_work"),
    }
    for rel, path in dump_tables.items():
        source = Path(path) if path else None
        if source and source.is_file():
            target = tables_dir / rel
            shutil.copy2(source, target)
            copied[f"tables_by_dump/{rel}"] = str(target)

    return {
        "run_id": run_id,
        "dump_id": dump_id,
        "run_dir": str(run_dir),
        "dump_dir": str(dump_dir),
        "tables_dir": str(tables_dir),
        "copied": copied,
    }


def _dump_id_from_payload(payload: dict[str, Any]) -> str:
    manifest = payload.get("dump_manifest") if isinstance(payload.get("dump_manifest"), dict) else {}
    if manifest.get("dump_id"):
        return str(manifest["dump_id"])
    if manifest.get("raw_jsonl_sha256"):
        return f"dump_{str(manifest['raw_jsonl_sha256'])[:16]}"
    source = payload.get("source_file") if isinstance(payload.get("source_file"), dict) else {}
    if source.get("sha256"):
        return f"dump_{str(source['sha256'])[:16]}"
    return ""


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in value.strip())[:140] or "artifact"


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
