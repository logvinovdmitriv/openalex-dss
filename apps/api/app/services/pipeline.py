from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

from app.core.paths import DATA, JSON_FILES, PARQUET_TABLE_FILES, ROOT, SRC, TABLE_FILES
from app.providers import openalex_cli_provider
from app.services import artifact_context, author_slice
from app.services.filesystem import file_profile, resolve_safe_path
from app.services import metadata_store, query_planner, reports

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_mvp.config import replace_config, write_config  # noqa: E402
from openalex_mvp.io_utils import sha256_file, write_json  # noqa: E402
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
    input_tables = resolve_dump_tables(dump_id, required=True)
    analysis_eligibility = _recover_analysis_eligibility(payload, dump_id=dump_id, run_id=run_id)
    compute = _run_compute(cfg, run_id=run_id, dump_id=dump_id, analysis_eligibility=analysis_eligibility, input_tables=input_tables)
    _write_pipeline_summary("recalculate", cfg, {**payload, "run_id": run_id, "analysis_eligibility": analysis_eligibility, "input_dump_id": dump_id})
    archive = _archive_run_artifacts(cfg, {**payload, "run_id": run_id, "dump_id": dump_id, "analysis_eligibility": analysis_eligibility, "active_context_source": "recalculate", **compute})
    report = reports.build_report_bundle(metric="islv", fraction_mode=cfg.fraction_mode_default, limit=100, run_id=run_id, dump_id=dump_id)
    return {"status": "ok", "mode": "recalculate", "archive": archive, "report": report, "analysis_eligibility": analysis_eligibility, "input_tables": compute["input_tables"]}


def fetch_slice_dump(
    payload: dict[str, Any],
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    *,
    require_accepted_signatures: bool = False,
) -> dict[str, Any]:
    if not require_accepted_signatures and not _allow_unchecked_download():
        require_accepted_signatures = True
    cfg = _cfg({**payload, "workflow_mode": "strict_works"})
    _write_runtime_config(cfg)
    api_key = str(payload.get("api_key") or "").strip()
    plan = query_planner.plan_slice({**payload, "workflow_mode": "strict_works"})
    decision = plan.get("decision") or {}
    estimate = plan.get("estimate") or {}
    accepted_signature = str(payload.get("accepted_estimate_signature") or "").strip()
    current_signature = str((estimate.get("estimate_signature") or "")).strip()
    accepted_download_signature = str(payload.get("accepted_download_signature") or "").strip()
    current_download_signature = str((estimate.get("download_signature") or "")).strip()
    if require_accepted_signatures and not accepted_signature:
        raise ValueError("Сначала оцените срез и подтвердите подпись оценки перед скачиванием.")
    if require_accepted_signatures and not accepted_download_signature:
        raise ValueError("Сначала оцените срез и подтвердите подпись способа загрузки перед скачиванием.")
    if accepted_signature and current_signature and accepted_signature != current_signature:
        raise ValueError("Параметры среза изменились после оценки. Обновите оценку и подтвердите скачивание заново.")
    if accepted_download_signature and current_download_signature and accepted_download_signature != current_download_signature:
        raise ValueError("Способ загрузки среза изменился после оценки. Обновите оценку и подтвердите скачивание заново.")
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
            estimate={
                **estimate,
                "accepted_estimate_signature": accepted_signature or None,
                "accepted_download_signature": accepted_download_signature or None,
            },
            progress_callback=progress_callback,
        )
        passport["query_plan"] = plan
        if not passport.get("dump_id"):
            checksum = str(passport.get("raw_jsonl_sha256") or "")
            passport["dump_id"] = f"dump_{checksum[:16]}" if checksum else f"dump_{cfg.slice_name}"
        raw_jsonl = passport.get("raw_jsonl")
        if raw_jsonl:
            write_json(Path(str(raw_jsonl)).with_name("dump_manifest.json"), passport)
        metadata_store.record_slice_dump(passport)
    finally:
        if old is None:
            os.environ.pop(cfg.api_key_env, None)
        else:
            os.environ[cfg.api_key_env] = old
    raw_jsonl = passport.get("raw_jsonl")
    summary_payload = {**payload, "dump": passport, "query_plan": plan}
    summary_payload["analysis_eligibility"] = analysis_eligibility_from_dump(passport)
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

    dump_manifest = payload.get("dump_manifest") if isinstance(payload.get("dump_manifest"), dict) else {}
    analysis_eligibility = payload.get("analysis_eligibility") if isinstance(payload.get("analysis_eligibility"), dict) else analysis_eligibility_from_dump(dump_manifest)
    import_mode = str(payload.get("import_mode") or "exploratory")
    if import_mode == "final_reproducible" and not analysis_eligibility.get("allowed_for_final_analysis"):
        raise ValueError("Финальный импорт требует dump_manifest с allowed_for_final_analysis=true. Используйте exploratory import для чернового просмотра.")

    cfg = _cfg(payload)
    _write_runtime_config(cfg)
    profile = file_profile(source)
    dump_id = str(payload.get("dump_id") or _dump_id_from_payload({"source_file": profile}) or cfg.slice_name)
    if int(profile.get("bytes") or 0) == 0:
        raise ValueError(
            "Локальный дамп пуст: OpenAlex вернул 0 работ для выбранных фильтров. "
            "Расширьте период, уберите организацию или выберите более широкую предметную область."
        )
    quality, dump_table_sources, quality_report = _normalize_dump_to_scope(source, dump_id)
    input_tables = _materialize_dump_tables_from_sources(dump_id, dump_table_sources)
    source_type = "openalex_cli_dump_import" if dump_manifest else "local_file"
    write_json(
        DATA / "passports/fetch_meta.json",
        {
            "source_type": source_type,
            "source_entity": "works",
            "source_file": profile,
            "dump_id": payload.get("dump_id") or dump_manifest.get("dump_id"),
            "dump_manifest_path": str(Path(str(dump_manifest.get("raw_jsonl") or source)).with_name("dump_manifest.json")) if dump_manifest else "",
            "raw_jsonl_sha256": dump_manifest.get("raw_jsonl_sha256") or profile.get("sha256"),
            "openalex_filter": ((dump_manifest.get("openalex_request") or {}).get("filter") if dump_manifest else "") or "",
            "accepted_estimate_signature": ((dump_manifest.get("signatures") or {}).get("accepted_estimate_signature") if dump_manifest else None),
            "accepted_download_signature": ((dump_manifest.get("signatures") or {}).get("accepted_download_signature") if dump_manifest else None),
            "analysis_eligibility": analysis_eligibility,
            "import_mode": import_mode,
            "fetched_works": quality.get("raw_works"),
            "total_available": quality.get("raw_works"),
            "filter": "импорт OpenAlex CLI mini-dump" if dump_manifest else "локальный импорт дампа OpenAlex Works",
            "used_api_key": bool(dump_manifest.get("used_api_key")) if dump_manifest else False,
        },
    )
    run_id = str(payload.get("run_id") or "local_file")
    compute = _run_compute(cfg, run_id=run_id, dump_id=dump_id, analysis_eligibility=analysis_eligibility, input_tables=input_tables)
    _write_pipeline_summary("import_local_file", cfg, {**payload, "run_id": run_id, "source_file": profile, "analysis_eligibility": analysis_eligibility, "input_dump_id": dump_id})
    archive = _archive_run_artifacts(
        cfg,
        {
            **payload,
            "run_id": run_id,
            "source_file": profile,
            "dump_id": dump_id,
            "quality_report": str(quality_report),
            "analysis_eligibility": analysis_eligibility,
            "active_context_source": str(payload.get("active_context_source") or "import_local_file"),
            **compute,
        },
    )
    report = reports.build_report_bundle(metric="islv", fraction_mode=cfg.fraction_mode_default, limit=100, run_id=run_id, dump_id=dump_id)
    return {
        "status": "ok",
        "mode": "import_local_file",
        "source": profile,
        "archive": archive,
        "report": report,
        "analysis_eligibility": analysis_eligibility,
        "quality_report": str(quality_report),
        "input_tables": compute["input_tables"],
    }


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


def resolve_dump_tables(dump_id: str, *, required: bool = True) -> dict[str, Path]:
    safe_dump_id = _safe_id(str(dump_id or ""))
    base = DATA / "tables" / safe_dump_id
    tables = {
        "works": base / "works.parquet",
        "authorships": base / "authorships.parquet",
        "work_topics": base / "work_topics.parquet",
    }
    missing = [name for name, path in tables.items() if not path.is_file()]
    if required and missing:
        missing_text = ", ".join(f"{name}={tables[name]}" for name in missing)
        raise FileNotFoundError(f"Локальные таблицы для dump_id={dump_id} не найдены: {missing_text}. Сначала импортируйте или пересоберите дамп.")
    return {name: path for name, path in tables.items() if path.is_file()}


def _materialize_dump_tables(dump_id: str) -> dict[str, Path]:
    safe_dump_id = _safe_id(str(dump_id or ""))
    target_dir = DATA / "tables" / safe_dump_id
    target_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        "works": "works.parquet",
        "authorships": "authorships.parquet",
        "work_topics": "work_topics.parquet",
    }
    for name, filename in mapping.items():
        source = PARQUET_TABLE_FILES.get(name)
        if not source or not Path(source).is_file():
            raise FileNotFoundError(f"Не удалось материализовать dump_id={dump_id}: отсутствует parquet-таблица {name}.")
        shutil.copy2(Path(source), target_dir / filename)
    return resolve_dump_tables(safe_dump_id, required=True)


def _normalize_dump_to_scope(source: Path, dump_id: str) -> tuple[dict[str, Any], dict[str, Path], Path]:
    safe_dump_id = _safe_id(str(dump_id or ""))
    dump_dir = DATA / "dumps" / safe_dump_id
    normalized_dir = dump_dir / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    quality_report = dump_dir / "quality_report.json"
    quality = normalize_raw(
        source,
        normalized_dir / "works_flat.csv",
        normalized_dir / "authorships_flat.csv",
        quality_report,
        normalized_dir / "work_topics_flat.csv",
    )
    return quality, _dump_scoped_parquet_sources(safe_dump_id), quality_report


def _dump_scoped_parquet_sources(dump_id: str) -> dict[str, Path]:
    base = DATA / "dumps" / _safe_id(str(dump_id or "")) / "parquet"
    return {
        "works": base / "works_flat.parquet",
        "authorships": base / "authorships_flat.parquet",
        "work_topics": base / "work_topics_flat.parquet",
    }


def _materialize_dump_tables_from_sources(dump_id: str, sources: dict[str, Path]) -> dict[str, Path]:
    safe_dump_id = _safe_id(str(dump_id or ""))
    target_dir = DATA / "tables" / safe_dump_id
    target_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        "works": "works.parquet",
        "authorships": "authorships.parquet",
        "work_topics": "work_topics.parquet",
    }
    for name, filename in mapping.items():
        source = sources.get(name)
        if not source or not Path(source).is_file():
            raise FileNotFoundError(f"Не удалось материализовать dump_id={dump_id}: отсутствует dump-scoped parquet-таблица {name}.")
        shutil.copy2(Path(source), target_dir / filename)
    return resolve_dump_tables(safe_dump_id, required=True)


def _run_compute(
    cfg: Any,
    *,
    run_id: str = "base",
    dump_id: str = "",
    analysis_eligibility: dict[str, Any] | None = None,
    input_tables: dict[str, Path] | None = None,
) -> dict[str, Any]:
    input_tables = input_tables or resolve_dump_tables(dump_id, required=True)
    input_table_checksums = _table_checksums(input_tables)
    run_dir = DATA / "runs" / _safe_id(run_id)
    run_tables = run_dir / "tables"
    run_results = run_dir / "results"
    run_passports = run_dir / "passports"
    run_figures = run_results / "figures"
    run_tables.mkdir(parents=True, exist_ok=True)
    run_results.mkdir(parents=True, exist_ok=True)

    author_work_csv = run_tables / "author_work.csv"
    indices_csv = run_tables / "indices.csv"
    ratings_csv = run_tables / "ratings.csv"
    stats_json = run_results / "stats_summary.json"
    theory_json = run_results / "theory_validation.json"

    build_author_work_metrics(input_tables["works"], input_tables["authorships"], author_work_csv, cfg.fraction_modes, run_id=run_id)
    compute_indices(
        author_work_csv,
        indices_csv,
        cfg.iupv_n0,
        cfg.iupv_lambda,
        cfg.lrdi_p0,
        cfg.lrdi_lambda,
        cfg.analysis_year,
    )
    build_ratings(indices_csv, ratings_csv)
    analyze_stats(indices_csv, ratings_csv, run_figures, stats_json)
    analyze_theory(
        author_work_csv,
        indices_csv,
        theory_json,
        run_results,
        cfg.iupv_n0,
        cfg.iupv_lambda,
        cfg.lrdi_p0,
        cfg.lrdi_lambda,
        cfg.analysis_year,
        cfg.fraction_mode_default,
    )
    run_table_outputs = {
        "author_work": author_work_csv,
        "indices": indices_csv,
        "ratings": ratings_csv,
    }
    run_result_outputs = {
        "stats_summary": stats_json,
        "theory_validation": theory_json,
        "theory_top1_sensitivity": run_results / "theory_top1_sensitivity.csv",
        "theory_fraction_mode_sensitivity": run_results / "theory_fraction_mode_sensitivity.csv",
    }
    if _publish_latest_view_enabled():
        _publish_latest_view(input_tables, run_table_outputs, run_result_outputs)
    input_table_manifest = _table_manifest(input_tables, input_table_checksums)
    primary_artifacts = {
        "dump/tables/works.parquet": input_table_manifest.get("works"),
        "dump/tables/authorships.parquet": input_table_manifest.get("authorships"),
        "dump/tables/work_topics.parquet": input_table_manifest.get("work_topics"),
        "run/tables/author_work.csv": author_work_csv,
        "run/tables/indices.csv": indices_csv,
        "run/tables/ratings.csv": ratings_csv,
        "run/results/stats_summary.json": stats_json,
        "run/results/theory_validation.json": theory_json,
        "run/results/theory_top1_sensitivity.csv": run_results / "theory_top1_sensitivity.csv",
        "run/results/theory_fraction_mode_sensitivity.csv": run_results / "theory_fraction_mode_sensitivity.csv",
    }
    build_passports(
        cfg,
        ROOT,
        run_passports,
        run_id=run_id,
        dump_id=dump_id,
        analysis_eligibility=analysis_eligibility,
        input_tables=input_table_manifest,
        primary_artifacts=primary_artifacts,
    )
    passport_outputs = {
        "slice_passport": str(run_passports / "slice_passport.json"),
        "calculation_passport": str(run_passports / "calculation_passport.json"),
        "checksums": str(run_passports / "checksums.json"),
    }
    return {
        "input_dump_id": dump_id,
        "input_tables": input_table_manifest,
        "input_table_checksums": input_table_checksums,
        "run_table_outputs": {key: str(path) for key, path in run_table_outputs.items()},
        "run_result_outputs": {key: str(path) for key, path in run_result_outputs.items()},
        "passport_outputs": passport_outputs,
    }


def _publish_latest_view(input_tables: dict[str, Path], run_tables: dict[str, Path], run_results: dict[str, Path]) -> None:
    for name in ("works", "authorships", "work_topics"):
        target = PARQUET_TABLE_FILES.get(name)
        source = input_tables.get(name)
        if source and target:
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    table_pairs = {
        "author_work": "author_work",
        "indices": "indices",
        "ratings": "ratings",
    }
    for source_key, table_key in table_pairs.items():
        source_csv = run_tables[source_key]
        csv_target = TABLE_FILES.get(table_key)
        if csv_target:
            Path(csv_target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_csv, csv_target)
        source_parquet = source_csv.with_suffix(".parquet")
        parquet_target = PARQUET_TABLE_FILES.get(table_key)
        if source_parquet.is_file() and parquet_target:
            Path(parquet_target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_parquet, parquet_target)
        if table_key == "indices":
            local_metrics_target = TABLE_FILES.get("authors_local_metrics")
            local_metrics_parquet_target = PARQUET_TABLE_FILES.get("authors_local_metrics")
            if local_metrics_target:
                Path(local_metrics_target).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_csv, local_metrics_target)
            if source_parquet.is_file() and local_metrics_parquet_target:
                Path(local_metrics_parquet_target).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_parquet, local_metrics_parquet_target)

    for name, source in run_results.items():
        if not source.is_file():
            continue
        if name == "stats_summary":
            target = DATA / "results" / "stats_summary.json"
        elif name == "theory_validation":
            target = DATA / "results" / "theory_validation.json"
        elif name == "theory_top1_sensitivity":
            target = DATA / "results" / "theory_top1_sensitivity.csv"
        elif name == "theory_fraction_mode_sensitivity":
            target = DATA / "results" / "theory_fraction_mode_sensitivity.csv"
        else:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _publish_latest_view_enabled() -> bool:
    return os.environ.get("OPENALEX_DSS_PUBLISH_LATEST_VIEW") == "1"


def _table_checksums(paths: dict[str, Path]) -> dict[str, str]:
    return {name: sha256_file(path) for name, path in paths.items() if path.is_file()}


def _table_manifest(paths: dict[str, Path], checksums: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "path": str(path),
            "sha256": checksums.get(name, ""),
            "bytes": path.stat().st_size if path.is_file() else 0,
        }
        for name, path in paths.items()
    }


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
    if payload.get("analysis_eligibility"):
        doc["analysis_eligibility"] = payload["analysis_eligibility"]
    write_json(JSON_FILES["pipeline"], doc)
    run_id = str(payload.get("run_id") or "").strip()
    if run_id:
        write_json(DATA / "runs" / _safe_id(run_id) / "passports" / "pipeline_summary.json", doc)


def _archive_run_artifacts(cfg: Any, payload: dict[str, Any]) -> dict[str, Any]:
    run_id = _safe_id(str(payload.get("run_id") or "latest"))
    dump_id = _safe_id(str(payload.get("dump_id") or _dump_id_from_payload(payload) or cfg.slice_name))
    run_dir = DATA / "runs" / run_id
    dump_dir = DATA / "dumps" / dump_id
    tables_dir = DATA / "tables" / dump_id
    input_tables = payload.get("input_tables") if isinstance(payload.get("input_tables"), dict) else {}
    run_table_outputs = payload.get("run_table_outputs") if isinstance(payload.get("run_table_outputs"), dict) else {}
    run_result_outputs = payload.get("run_result_outputs") if isinstance(payload.get("run_result_outputs"), dict) else {}
    passport_outputs = payload.get("passport_outputs") if isinstance(payload.get("passport_outputs"), dict) else {}
    copied: dict[str, str] = {}

    for base in (run_dir, dump_dir, tables_dir):
        base.mkdir(parents=True, exist_ok=True)

    manifest = {
        "run_id": run_id,
        "dump_id": dump_id,
        "slice_id": cfg.slice_name,
        "source_file": payload.get("source_file"),
        "dump_manifest": payload.get("dump_manifest"),
        "analysis_eligibility": payload.get("analysis_eligibility"),
        "input_dump_id": payload.get("input_dump_id") or dump_id,
        "input_tables": input_tables,
        "input_table_checksums": payload.get("input_table_checksums") or {},
        "run_table_outputs": run_table_outputs,
        "run_result_outputs": run_result_outputs,
        "passport_outputs": passport_outputs,
        "latest_view_note": "Global normalized/results paths are only the UI latest-view; reproducible artifacts are archived under this run_id and dump_id.",
    }
    write_json(run_dir / "metric_run.json", manifest)
    if payload.get("dump_manifest"):
        write_json(dump_dir / "dump_manifest.json", payload["dump_manifest"])
    elif not (dump_dir / "dump_manifest.json").exists():
        write_json(dump_dir / "dump_manifest_recovered.json", manifest)

    for name in ("author_work", "indices", "ratings"):
        source = _artifact_path(run_table_outputs.get(name))
        if not source:
            continue
        suffix = source.suffix or ".csv"
        rel = f"tables/{name}{suffix}"
        _copy_or_record_artifact(source, run_dir / rel, copied, rel)

    run_result_filenames = {
        "stats_summary": "stats_summary.json",
        "theory_validation": "theory_validation.json",
        "theory_top1_sensitivity": "theory_top1_sensitivity.csv",
        "theory_fraction_mode_sensitivity": "theory_fraction_mode_sensitivity.csv",
    }
    for name, filename in run_result_filenames.items():
        source = _artifact_path(run_result_outputs.get(name))
        if source:
            rel = f"results/{filename}"
            _copy_or_record_artifact(source, run_dir / rel, copied, rel)

    run_passport_filenames = {
        "slice_passport": "slice_passport.json",
        "calculation_passport": "calculation_passport.json",
        "checksums": "checksums.json",
    }
    for name, filename in run_passport_filenames.items():
        source = _artifact_path(passport_outputs.get(name))
        if source:
            rel = f"passports/{filename}"
            _copy_or_record_artifact(source, run_dir / rel, copied, rel)

    quality_report = _artifact_path(payload.get("quality_report")) or _artifact_path(dump_dir / "quality_report.json")
    if quality_report:
        _copy_or_record_artifact(quality_report, run_dir / "passports" / "quality_report.json", copied, "passports/quality_report.json")

    passport_artifacts = {
        "passports/fetch_meta.json": JSON_FILES.get("fetch_meta"),
    }
    for rel, path in passport_artifacts.items():
        source = _artifact_path(path)
        if source:
            _copy_or_record_artifact(source, run_dir / rel, copied, rel)

    for name in ("works", "authorships", "work_topics"):
        source = _artifact_path(input_tables.get(name))
        if source:
            rel = f"{name}.parquet"
            _copy_or_record_artifact(source, tables_dir / rel, copied, f"tables_by_dump/{rel}")

    eligibility = payload.get("analysis_eligibility") if isinstance(payload.get("analysis_eligibility"), dict) else {}
    allowed_for_final_analysis = eligibility.get("allowed_for_final_analysis")
    active_context = artifact_context.write_active_context(
        run_id=run_id,
        dump_id=dump_id,
        source=str(payload.get("active_context_source") or "pipeline"),
        data_dir=DATA,
        extra={
            "run_dir": str(run_dir),
            "dump_dir": str(dump_dir),
            "tables_dir": str(tables_dir),
            "analysis_eligibility_status": eligibility.get("status"),
            "allowed_for_final_analysis": (
                allowed_for_final_analysis if isinstance(allowed_for_final_analysis, bool) else None
            ),
        },
    )

    return {
        "run_id": run_id,
        "dump_id": dump_id,
        "run_dir": str(run_dir),
        "dump_dir": str(dump_dir),
        "tables_dir": str(tables_dir),
        "active_context": active_context,
        "copied": copied,
    }


def _artifact_path(value: Any) -> Path | None:
    raw = value.get("path") if isinstance(value, dict) else value
    if not raw:
        return None
    path = Path(str(raw))
    return path if path.is_file() else None


def _copy_or_record_artifact(source: Path, target: Path, copied: dict[str, str], rel: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    copied[rel] = str(target)


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


def analysis_eligibility_from_dump(dump: dict[str, Any], *, dev_override: bool = False) -> dict[str, Any]:
    allowed = bool(dump.get("allowed_for_final_analysis"))
    signatures = dump.get("signatures") if isinstance(dump.get("signatures"), dict) else {}
    status = "final" if allowed else ("dev_only_not_for_final_analysis" if dev_override else "blocked_not_for_final_analysis")
    return {
        "status": status,
        "allowed_for_final_analysis": allowed,
        "dev_override": bool(dev_override),
        "dump_id": dump.get("dump_id"),
        "scientific_completeness": dump.get("scientific_completeness") or "",
        "stop_reason": dump.get("stop_reason") or "",
        "records_downloaded": int(dump.get("records_downloaded") or 0),
        "raw_jsonl_sha256": dump.get("raw_jsonl_sha256") or "",
        "signature_checks": {
            "estimate_signature_verified": bool(signatures.get("estimate_signature_verified")),
            "accepted_estimate_signature_verified": bool(signatures.get("accepted_estimate_signature_verified")),
            "download_signature_verified": bool(signatures.get("download_signature_verified")),
            "compatible": bool(signatures.get("compatible")),
        },
        "warning": "" if allowed else "This analysis is not eligible for final dissertation-grade conclusions.",
    }


def _recover_analysis_eligibility(payload: dict[str, Any], *, dump_id: str = "", run_id: str = "") -> dict[str, Any]:
    if isinstance(payload.get("analysis_eligibility"), dict):
        return payload["analysis_eligibility"]
    if dump_id:
        manifest = _read_artifact_json(DATA / "dumps" / _safe_id(dump_id) / "dump_manifest.json")
        recovered = _analysis_eligibility_from_manifest(manifest)
        if recovered:
            return recovered
        catalog_dump = metadata_store.get_slice_dump_by_dump_id(dump_id)
        if catalog_dump:
            return analysis_eligibility_from_dump(catalog_dump)
    if run_id:
        metric_run = _read_artifact_json(DATA / "runs" / _safe_id(run_id) / "metric_run.json")
        recovered = _analysis_eligibility_from_manifest(metric_run)
        if recovered:
            return recovered
    return {"status": "unknown", "allowed_for_final_analysis": False, "warning": "Analysis eligibility could not be recovered from payload, dump manifest, or run manifest."}


def _analysis_eligibility_from_manifest(manifest: dict[str, Any]) -> dict[str, Any] | None:
    if not manifest:
        return None
    if isinstance(manifest.get("analysis_eligibility"), dict):
        return manifest["analysis_eligibility"]
    if isinstance(manifest.get("dump_manifest"), dict):
        return analysis_eligibility_from_dump(manifest["dump_manifest"])
    if "allowed_for_final_analysis" in manifest:
        return analysis_eligibility_from_dump(manifest)
    return None


def _read_artifact_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _allow_unchecked_download() -> bool:
    return os.environ.get("OPENALEX_DSS_ALLOW_UNCHECKED_DOWNLOAD") == "1"


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
