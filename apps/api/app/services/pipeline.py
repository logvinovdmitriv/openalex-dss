from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.core.paths import DATA, ROOT, SRC
from app.providers import openalex_api_provider, openalex_cli_provider, openalex_snapshot_provider
from app.services import artifact_context, author_slice
from app.services.filesystem import file_profile, resolve_safe_path
from app.services import dump_integrity, metadata_store, query_planner, reports

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_dss.config import replace_config, write_config  # noqa: E402
from openalex_dss.io_utils import sha256_file, write_json, write_parquet_dicts  # noqa: E402
from openalex_dss.metrics import build_author_work_metrics, compute_indices  # noqa: E402
from openalex_dss.normalize import normalize_raw  # noqa: E402
from openalex_dss.passports import build_passports  # noqa: E402
from openalex_dss.ranking import build_ratings  # noqa: E402

StageProgressCallback = Callable[[int | None, str, dict[str, Any] | None], None]

PRECOMPUTE_SCIENTOMETRIC_METRICS = ("p", "c", "c_frac", "h", "i10", "g")
PRECOMPUTE_CUSTOM_METRICS: tuple[dict[str, str], ...] = ()
PRECOMPUTE_RANK_TOP_N = 100


def recalculate(payload: dict[str, Any], progress_callback: StageProgressCallback | None = None) -> dict[str, Any]:
    cfg = _cfg(payload)
    _write_runtime_config(cfg)
    run_id = str(payload.get("run_id") or cfg.slice_name or "recalculate")
    dump_id = str(payload.get("dump_id") or _dump_id_from_payload(payload) or cfg.slice_name)
    _emit_progress(progress_callback, 48, "Проверка локальных таблиц среза", {"dump_id": dump_id})
    input_tables = resolve_dump_tables(dump_id, required=True)
    analysis_eligibility = _recover_analysis_eligibility(payload, dump_id=dump_id, run_id=run_id)
    compute = _run_compute(
        cfg,
        run_id=run_id,
        dump_id=dump_id,
        analysis_eligibility=analysis_eligibility,
        input_tables=input_tables,
        extra_primary_artifacts=_dump_provenance_primary_artifacts(dump_id),
        progress_callback=progress_callback,
        progress_base=52,
        progress_span=38,
    )
    _emit_progress(progress_callback, 91, "Обновление паспорта расчета", {"run_id": run_id, "dump_id": dump_id})
    _write_pipeline_summary("recalculate", cfg, {**payload, "run_id": run_id, "analysis_eligibility": analysis_eligibility, "input_dump_id": dump_id})
    archive = _archive_run_artifacts(cfg, {**payload, "run_id": run_id, "dump_id": dump_id, "analysis_eligibility": analysis_eligibility, "active_context_source": "recalculate", **compute})
    precomputed = _precompute_run_artifacts(cfg, run_id=run_id, dump_id=dump_id, progress_callback=progress_callback)
    report = precomputed["report"]
    _emit_progress(progress_callback, 98, "Расчет индексов завершен", {"run_id": run_id, "dump_id": dump_id})
    _prune_runs_for_dump(dump_id, keep=3)
    return {
        "status": "ok",
        "mode": "recalculate",
        "archive": archive,
        "report": report,
        "precomputed": precomputed["manifest"],
        "analysis_eligibility": analysis_eligibility,
        "input_tables": compute["input_tables"],
    }


def fetch_slice_dump(
    payload: dict[str, Any],
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    cancel_callback: Callable[[], bool] | None = None,
    *,
    require_accepted_signatures: bool = False,
) -> dict[str, Any]:
    if not require_accepted_signatures and not _allow_unchecked_download():
        require_accepted_signatures = True
    cfg = _cfg({**payload, "workflow_mode": "strict_works"})
    _write_runtime_config(cfg)
    api_key = _openalex_cli_api_key(payload, cfg)
    plan = _query_plan_from_payload(payload) or query_planner.plan_slice({**payload, "workflow_mode": "strict_works"})
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
        raise ValueError("; ".join(decision.get("reasons") or []) or "Срез нельзя скачать через текущий план загрузки OpenAlex.")
    old = os.environ.get(cfg.api_key_env)
    try:
        if api_key:
            os.environ[cfg.api_key_env] = api_key
        source_strategy = str(payload.get("source_strategy") or "openalex_cli")
        estimate_payload = {
            **estimate,
            "accepted_estimate_signature": accepted_signature or None,
            "accepted_download_signature": accepted_download_signature or None,
        }
        if source_strategy == "openalex_cli":
            passport = openalex_cli_provider.download_works_metadata(
                cfg,
                api_key=api_key,
                out_dir=_download_output_dir(payload, cfg),
                estimate=estimate_payload,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
                max_download_bytes=_max_download_bytes(payload),
            )
        elif source_strategy in {"openalex_api", "api_cursor_selected_fields"}:
            passport = openalex_api_provider.download_works_cursor(
                cfg,
                api_key=api_key,
                out_dir=_download_output_dir(payload, cfg, source_strategy=source_strategy),
                estimate=estimate_payload,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
                max_download_bytes=_max_download_bytes(payload),
            )
        elif source_strategy == "ids_then_hydrate":
            work_ids = _work_ids_from_payload(payload)
            if not work_ids:
                work_ids = openalex_api_provider.collect_work_ids_cursor(
                    cfg,
                    api_key=api_key,
                    progress_callback=progress_callback,
                    cancel_callback=cancel_callback,
                    max_ids=int(estimate.get("estimate_count") or 0),
                )
            passport = openalex_api_provider.hydrate_work_ids(
                cfg,
                work_ids=work_ids,
                api_key=api_key,
                out_dir=_download_output_dir(payload, cfg, source_strategy=source_strategy),
                estimate=estimate_payload,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
                max_download_bytes=_max_download_bytes(payload),
            )
        elif source_strategy in {"openalex_snapshot_jsonl", "snapshot_partition_scan"}:
            passport = openalex_snapshot_provider.scan_snapshot_partitions(
                cfg,
                snapshot_dir=_snapshot_dir_from_payload(payload),
                out_dir=_download_output_dir(payload, cfg, source_strategy=source_strategy),
                estimate=estimate_payload,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
                max_download_bytes=_max_download_bytes(payload),
            )
        else:
            raise ValueError(
                "Неизвестный способ загрузки среза. Доступны openalex_cli, openalex_api/api_cursor_selected_fields, ids_then_hydrate и openalex_snapshot_jsonl."
            )
        passport["query_plan"] = plan
        if not passport.get("dump_id"):
            checksum = str(passport.get("raw_jsonl_sha256") or "")
            passport["dump_id"] = f"dump_{checksum[:16]}" if checksum else f"dump_{cfg.slice_name}"
        raw_jsonl = passport.get("raw_jsonl")
        if raw_jsonl:
            write_json(Path(str(raw_jsonl)).with_name("dump_manifest.json"), passport)
        metadata_store.record_slice_dump(passport)
        query_planner.record_estimate_calibration(passport, estimate)
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


def import_local_file(
    payload: dict[str, Any],
    progress_callback: StageProgressCallback | None = None,
    *,
    compute_progress_base: int = 70,
) -> dict[str, Any]:
    source_path = str(payload.get("source_path") or "").strip()
    if not source_path:
        raise ValueError("source_path is required")
    source = resolve_safe_path(source_path)
    if not (source.name.endswith(".jsonl") or source.name.endswith(".jsonl.gz")):
        raise ValueError("Only OpenAlex JSONL or JSONL.GZ dumps are importable in this pipeline")

    dump_manifest = payload.get("dump_manifest") if isinstance(payload.get("dump_manifest"), dict) else {}
    if dump_manifest:
        dump_manifest = dump_integrity.manifest_with_integrity(
            {**dump_manifest, "raw_jsonl": str(source)},
            require_expected_count=str(dump_manifest.get("scientific_completeness") or "") in {"complete", "full"},
        )
    analysis_eligibility = payload.get("analysis_eligibility") if isinstance(payload.get("analysis_eligibility"), dict) else analysis_eligibility_from_dump(dump_manifest)
    if isinstance(dump_manifest.get("integrity_validation"), dict) and not dump_manifest["integrity_validation"].get("ok"):
        analysis_eligibility = analysis_eligibility_from_dump(dump_manifest)
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
    if dump_manifest:
        dump_manifest = {**dump_manifest, "dump_id": dump_id}
    dump_manifest_path = _write_dump_manifest_if_present(dump_id, dump_manifest)
    if not dump_manifest_path:
        _clear_stale_dump_manifest(dump_id)
    _emit_progress(progress_callback, max(0, compute_progress_base - 4), "Нормализация локального среза", {"source_path": str(source), "dump_id": dump_id})
    quality, dump_table_sources, quality_report = _normalize_dump_to_scope(source, dump_id)
    analysis_eligibility = _apply_quality_eligibility_guard(
        analysis_eligibility,
        quality,
        dump_manifest=dump_manifest,
    )
    if dump_manifest:
        dump_manifest = {
            **dump_manifest,
            "analysis_eligibility": analysis_eligibility,
            "allowed_for_final_analysis": bool(analysis_eligibility.get("allowed_for_final_analysis")),
            "quality_gate": analysis_eligibility.get("quality_gate") or {},
        }
        dump_manifest_path = _write_dump_manifest_if_present(dump_id, dump_manifest)
        metadata_store.record_slice_dump(dump_manifest)
    _emit_progress(progress_callback, max(0, compute_progress_base - 2), "Подготовка таблиц среза", {"dump_id": dump_id, "works": quality.get("raw_works")})
    input_tables = _materialize_dump_tables_from_sources(dump_id, dump_table_sources)
    _cleanup_dump_staging(dump_id)
    source_type = "openalex_cli_dump_import" if dump_manifest else "local_file"
    fetch_meta = {
        "source_type": source_type,
        "source_entity": "works",
        "source_file": profile,
        "dump_id": dump_id,
        "dump_manifest_path": str(dump_manifest_path) if dump_manifest_path else "",
        "raw_jsonl_sha256": dump_manifest.get("raw_jsonl_sha256") or profile.get("sha256"),
        "openalex_filter": ((dump_manifest.get("openalex_request") or {}).get("filter") if dump_manifest else "") or "",
        "accepted_estimate_signature": ((dump_manifest.get("signatures") or {}).get("accepted_estimate_signature") if dump_manifest else None),
        "accepted_download_signature": ((dump_manifest.get("signatures") or {}).get("accepted_download_signature") if dump_manifest else None),
        "analysis_eligibility": analysis_eligibility,
        "import_mode": import_mode,
        "fetched_works": quality.get("raw_works"),
        "total_available": quality.get("raw_works"),
        "filter": "импорт локального среза OpenAlex" if dump_manifest else "локальный импорт дампа OpenAlex Works",
        "used_api_key": bool(dump_manifest.get("used_api_key")) if dump_manifest else False,
    }
    fetch_meta_path = _write_dump_fetch_meta(dump_id, fetch_meta)
    run_id = str(payload.get("run_id") or "local_file")
    extra_primary_artifacts = {
        "dump/fetch_meta.json": fetch_meta_path,
        "dump/quality_report.json": quality_report,
    }
    if dump_manifest_path:
        extra_primary_artifacts["dump/dump_manifest.json"] = dump_manifest_path
    compute = _run_compute(
        cfg,
        run_id=run_id,
        dump_id=dump_id,
        analysis_eligibility=analysis_eligibility,
        input_tables=input_tables,
        extra_primary_artifacts=extra_primary_artifacts,
        progress_callback=progress_callback,
        progress_base=compute_progress_base,
        progress_span=max(1, 98 - compute_progress_base),
    )
    _emit_progress(progress_callback, 98, "Срез и индексы готовы", {"run_id": run_id, "dump_id": dump_id})
    _write_pipeline_summary("import_local_file", cfg, {**payload, "run_id": run_id, "source_file": profile, "analysis_eligibility": analysis_eligibility, "input_dump_id": dump_id})
    archive = _archive_run_artifacts(
        cfg,
        {
            **payload,
            "dump_manifest": dump_manifest,
            "run_id": run_id,
            "source_file": profile,
            "dump_id": dump_id,
            "fetch_meta": str(fetch_meta_path),
            "quality_report": str(quality_report),
            "analysis_eligibility": analysis_eligibility,
            "active_context_source": str(payload.get("active_context_source") or "import_local_file"),
            **compute,
        },
    )
    precomputed = _precompute_run_artifacts(cfg, run_id=run_id, dump_id=dump_id, progress_callback=progress_callback)
    report = precomputed["report"]
    _prune_runs_for_dump(dump_id, keep=3)
    return {
        "status": "ok",
        "mode": "import_local_file",
        "source": profile,
        "archive": archive,
        "report": report,
        "precomputed": precomputed["manifest"],
        "analysis_eligibility": analysis_eligibility,
        "fetch_meta": str(fetch_meta_path),
        "quality_report": str(quality_report),
        "input_tables": compute["input_tables"],
    }


def preview(payload: dict[str, Any]) -> dict[str, Any]:
    return author_slice.preview(payload)


def resolve_dump_tables(dump_id: str, *, required: bool = True) -> dict[str, Path]:
    safe_dump_id = _safe_id(_resolve_dump_id(str(dump_id or "")))
    base = DATA / "tables" / safe_dump_id
    tables = {
        "works": base / "works.parquet",
        "authorships": base / "authorships.parquet",
        "work_topics": base / "work_topics.parquet",
        "author_institutions": base / "author_institutions.parquet",
        "author_countries": base / "author_countries.parquet",
    }
    required_tables = {"works", "authorships", "work_topics"}
    missing = [name for name, path in tables.items() if name in required_tables and not path.is_file()]
    if required and missing:
        missing_text = ", ".join(f"{name}={tables[name]}" for name in missing)
        raise FileNotFoundError(f"Локальные таблицы для dump_id={dump_id} не найдены: {missing_text}. Сначала импортируйте или пересоберите дамп.")
    return {name: path for name, path in tables.items() if path.is_file()}


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
        normalized_dir / "author_institutions_flat.csv",
        normalized_dir / "author_countries_flat.csv",
    )
    return quality, _dump_scoped_parquet_sources(safe_dump_id), quality_report


def _dump_scoped_parquet_sources(dump_id: str) -> dict[str, Path]:
    base = DATA / "dumps" / _safe_id(_resolve_dump_id(str(dump_id or ""))) / "parquet"
    return {
        "works": base / "works_flat.parquet",
        "authorships": base / "authorships_flat.parquet",
        "work_topics": base / "work_topics_flat.parquet",
        "author_institutions": base / "author_institutions_flat.parquet",
        "author_countries": base / "author_countries_flat.parquet",
    }


def _write_dump_fetch_meta(dump_id: str, fetch_meta: dict[str, Any]) -> Path:
    dump_dir = DATA / "dumps" / _safe_id(str(dump_id or ""))
    dump_dir.mkdir(parents=True, exist_ok=True)
    path = dump_dir / "fetch_meta.json"
    write_json(path, fetch_meta)
    return path


def _write_dump_manifest_if_present(dump_id: str, dump_manifest: dict[str, Any]) -> Path | None:
    if not dump_manifest:
        return None
    dump_dir = DATA / "dumps" / _safe_id(str(dump_id or ""))
    dump_dir.mkdir(parents=True, exist_ok=True)
    path = dump_dir / "dump_manifest.json"
    write_json(path, {**dump_manifest, "dump_id": dump_id})
    return path


def _clear_stale_dump_manifest(dump_id: str) -> None:
    raw_dump_id = _resolve_dump_id(str(dump_id or "").strip())
    if not raw_dump_id:
        return
    path = DATA / "dumps" / _safe_id(raw_dump_id) / "dump_manifest.json"
    if path.is_file():
        path.unlink()


def _dump_provenance_primary_artifacts(dump_id: str) -> dict[str, Path]:
    raw_dump_id = _resolve_dump_id(str(dump_id or "").strip())
    if not raw_dump_id:
        return {}
    dump_dir = DATA / "dumps" / _safe_id(raw_dump_id)
    candidates = {
        "dump/fetch_meta.json": dump_dir / "fetch_meta.json",
        "dump/quality_report.json": dump_dir / "quality_report.json",
        "dump/dump_manifest.json": dump_dir / "dump_manifest.json",
    }
    return {label: path for label, path in candidates.items() if path.is_file()}


def _materialize_dump_tables_from_sources(dump_id: str, sources: dict[str, Path]) -> dict[str, Path]:
    safe_dump_id = _safe_id(str(dump_id or ""))
    target_dir = DATA / "tables" / safe_dump_id
    target_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        "works": "works.parquet",
        "authorships": "authorships.parquet",
        "work_topics": "work_topics.parquet",
        "author_institutions": "author_institutions.parquet",
        "author_countries": "author_countries.parquet",
    }
    for name, filename in mapping.items():
        source = sources.get(name)
        if not source or not Path(source).is_file():
            raise FileNotFoundError(f"Не удалось материализовать dump_id={dump_id}: отсутствует dump-scoped parquet-таблица {name}.")
        shutil.copy2(Path(source), target_dir / filename)
    return resolve_dump_tables(safe_dump_id, required=True)


def _cleanup_dump_staging(dump_id: str) -> list[str]:
    safe_dump_id = _safe_id(_resolve_dump_id(str(dump_id or "")))
    if not safe_dump_id:
        return []
    dump_dir = DATA / "dumps" / safe_dump_id
    removed: list[str] = []
    for name in ("normalized", "parquet"):
        path = dump_dir / name
        if not path.exists():
            continue
        shutil.rmtree(path)
        removed.append(str(path))
    return removed


def _run_compute(
    cfg: Any,
    *,
    run_id: str = "base",
    dump_id: str = "",
    analysis_eligibility: dict[str, Any] | None = None,
    input_tables: dict[str, Path] | None = None,
    extra_primary_artifacts: dict[str, Any] | None = None,
    progress_callback: StageProgressCallback | None = None,
    progress_base: int = 50,
    progress_span: int = 45,
) -> dict[str, Any]:
    def step(relative: float, stage: str, extra: dict[str, Any] | None = None) -> None:
        percent = progress_base + int(max(0.0, min(1.0, relative)) * max(1, progress_span))
        _emit_progress(progress_callback, percent, stage, {"run_id": run_id, "dump_id": dump_id, **(extra or {})})

    input_tables = input_tables or resolve_dump_tables(dump_id, required=True)
    step(0.02, "Проверка контрольных сумм входных таблиц")
    input_table_checksums = _table_checksums(input_tables)
    run_dir = DATA / "runs" / _safe_id(run_id)
    run_tables = run_dir / "tables"
    run_passports = run_dir / "passports"
    run_tables.mkdir(parents=True, exist_ok=True)

    author_work_csv = run_tables / "author_work.csv"
    author_work_parquet = author_work_csv.with_suffix(".parquet")
    indices_csv = run_tables / "indices.csv"
    indices_parquet = indices_csv.with_suffix(".parquet")
    ratings_csv = run_tables / "ratings.csv"

    step(0.18, "Формирование авторского уровня данных")
    input_counts = _table_counts(input_tables)
    build_author_work_metrics(
        input_tables["works"],
        input_tables["authorships"],
        author_work_csv,
        cfg.fraction_modes,
        run_id=run_id,
        return_rows=False,
        exclude_retracted=bool(getattr(cfg, "exclude_retracted", True)),
        exclude_paratext=bool(getattr(cfg, "exclude_paratext", True)),
        include_xpac=bool(getattr(cfg, "include_xpac", False)),
        work_types=tuple(part.strip() for part in str(getattr(cfg, "work_type", "") or "").split("|") if part.strip()),
        from_publication_date=str(getattr(cfg, "from_publication_date", "") or ""),
        to_publication_date=str(getattr(cfg, "to_publication_date", "") or ""),
    )
    author_work_count = _table_row_count(author_work_parquet if author_work_parquet.exists() else author_work_csv)
    if _positive_count(input_counts.get("works")) and _positive_count(input_counts.get("authorships")) and author_work_count == 0:
        raise ValueError(
            "Расчет авторского уровня дал 0 строк при непустых works/authorships. "
            "Проверьте, что параметры среза в run совпадают с dump_manifest и локальными фильтрами."
        )
    step(0.48, "Расчет наукометрических показателей")
    compute_indices(
        author_work_parquet if author_work_parquet.exists() else author_work_csv,
        indices_csv,
        cfg.lrdi_p0,
        cfg.lrdi_lambda,
        cfg.analysis_year,
        return_rows=False,
    )
    indices_count = _table_row_count(indices_parquet if indices_parquet.exists() else indices_csv)
    if author_work_count and indices_count == 0:
        raise ValueError("Расчет индексов дал 0 строк при непустом author_work.")
    step(0.72, "Построение рейтингов")
    build_ratings(indices_parquet if indices_parquet.exists() else indices_csv, ratings_csv, return_rows=False)
    ratings_count = _table_row_count(ratings_csv)
    if indices_count and ratings_count == 0:
        raise ValueError("Построение рейтингов дало 0 строк при непустой таблице indices.")
    run_table_outputs = {
        "author_work": author_work_csv,
        "indices": indices_csv,
        "ratings": ratings_csv,
    }
    input_table_manifest = _table_manifest(input_tables, input_table_checksums)
    primary_artifacts = {
        "dump/tables/works.parquet": input_table_manifest.get("works"),
        "dump/tables/authorships.parquet": input_table_manifest.get("authorships"),
        "dump/tables/work_topics.parquet": input_table_manifest.get("work_topics"),
        "dump/tables/author_institutions.parquet": input_table_manifest.get("author_institutions"),
        "dump/tables/author_countries.parquet": input_table_manifest.get("author_countries"),
        "run/tables/author_work.csv": author_work_csv,
        "run/tables/indices.csv": indices_csv,
        "run/tables/ratings.csv": ratings_csv,
    }
    primary_artifacts.update(extra_primary_artifacts or {})
    step(0.88, "Запись паспортов и контрольных сумм")
    build_passports(
        cfg,
        ROOT,
        run_id=run_id,
        dump_id=dump_id,
        analysis_eligibility=analysis_eligibility,
        input_tables=input_table_manifest,
        primary_artifacts=primary_artifacts,
    )
    step(0.98, "Расчетные таблицы готовы")
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
        "passport_outputs": passport_outputs,
    }


def _precompute_run_artifacts(
    cfg: Any,
    *,
    run_id: str,
    dump_id: str,
    progress_callback: StageProgressCallback | None = None,
) -> dict[str, Any]:
    _emit_progress(progress_callback, 96, "Подготовка аналитики и отчета", {"run_id": run_id, "dump_id": dump_id})
    report = reports.build_report_bundle(
        metric="h",
        fraction_mode=cfg.fraction_mode_default,
        limit=100,
        run_id=run_id,
        dump_id=dump_id,
        scientometric_metrics=PRECOMPUTE_SCIENTOMETRIC_METRICS,
        baseline_metric="h",
        rank_top_n=PRECOMPUTE_RANK_TOP_N,
        data_limit=0,
        custom_metric_defs=list(PRECOMPUTE_CUSTOM_METRICS),
    )
    precompute_tables = _write_precompute_tables(run_id=run_id, report=report)
    manifest_path = _write_precompute_manifest(run_id=run_id, dump_id=dump_id, report=report)
    return {"report": report, "manifest": str(manifest_path), "tables": precompute_tables}


def _write_precompute_manifest(*, run_id: str, dump_id: str, report: dict[str, Any]) -> Path:
    run_dir = DATA / "runs" / _safe_id(run_id)
    analytics_dir = run_dir / "analytics"
    analytics_dir.mkdir(parents=True, exist_ok=True)
    scope = report.get("report_scope") if isinstance(report.get("report_scope"), dict) else {}
    scope_hash = str(scope.get("report_scope_hash") or "")
    manifest = {
        "schema": "run_precompute_manifest",
        "run_id": run_id,
        "dump_id": dump_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scientometric_metrics": list(PRECOMPUTE_SCIENTOMETRIC_METRICS),
        "custom_metrics": list(PRECOMPUTE_CUSTOM_METRICS),
        "baseline_metric": "h",
        "rank_top_n": PRECOMPUTE_RANK_TOP_N,
        "data_limit": 0,
        "report_scope_hash": scope_hash,
        "report_bundle": str(DATA / "runs" / _safe_id(run_id) / "reports" / f"report_{_safe_id(scope_hash)}.json") if scope_hash else "",
        "precompute_tables": {
            "metric_rank_summary": str(analytics_dir / "precompute" / "metric_rank_summary.parquet"),
            "chart_readiness": str(analytics_dir / "precompute" / "chart_readiness.parquet"),
            "metric_pair_correlations": str(analytics_dir / "precompute" / "metric_pair_correlations.parquet"),
            "topn_overlap_summary": str(analytics_dir / "precompute" / "topn_overlap_summary.parquet"),
            "rank_delta_summary": str(analytics_dir / "precompute" / "rank_delta_summary.parquet"),
        },
        "retention": {
            "report_bundles_per_run": reports.report_bundle_keep(),
            "scientometric_cache_files_per_run": reports.scientometrics.ANALYSIS_CACHE_KEEP,
            "runs_per_dump": 3,
            "transient_dump_staging": ["normalized", "parquet"],
        },
    }
    path = analytics_dir / "precompute_manifest.json"
    write_json(path, manifest)
    return path


def _write_precompute_tables(*, run_id: str, report: dict[str, Any]) -> dict[str, str]:
    analytics = report.get("scientometric_analysis") if isinstance(report.get("scientometric_analysis"), dict) else {}
    target_dir = DATA / "runs" / _safe_id(run_id) / "analytics" / "precompute"
    target_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "metric_rank_summary": _metric_rank_rows(analytics),
        "chart_readiness": _chart_readiness_rows(analytics),
        "metric_pair_correlations": _correlation_rows(analytics),
        "topn_overlap_summary": _top_overlap_rows(analytics),
        "rank_delta_summary": _rank_delta_rows(analytics),
    }
    paths: dict[str, str] = {}
    for name, rows in tables.items():
        json_path = target_dir / f"{name}.json"
        parquet_path = target_dir / f"{name}.parquet"
        write_json(json_path, {"schema": f"{name}_precompute_v1", "rows": rows})
        fields = sorted({field for row in rows for field in row}) or ["empty"]
        write_parquet_dicts(parquet_path, rows or [{"empty": ""}], fields)
        paths[name] = str(parquet_path)
    return paths


def _metric_rank_rows(analytics: dict[str, Any]) -> list[dict[str, Any]]:
    summary = analytics.get("metric_rank_summary") if isinstance(analytics.get("metric_rank_summary"), dict) else {}
    return [{**_flat_scalars(payload), "metric": metric} for metric, payload in sorted(summary.items()) if isinstance(payload, dict)]


def _chart_readiness_rows(analytics: dict[str, Any]) -> list[dict[str, Any]]:
    readiness = analytics.get("chart_readiness") if isinstance(analytics.get("chart_readiness"), dict) else {}
    rows: list[dict[str, Any]] = []
    for metric, charts in sorted(readiness.items()):
        if not isinstance(charts, dict):
            continue
        for chart_type, payload in sorted(charts.items()):
            if isinstance(payload, dict):
                rows.append({**_flat_scalars(payload), "metric": metric, "chart_type": chart_type})
    return rows


def _correlation_rows(analytics: dict[str, Any]) -> list[dict[str, Any]]:
    correlations = analytics.get("correlations") if isinstance(analytics.get("correlations"), dict) else {}
    rows: list[dict[str, Any]] = []
    for method, matrix_payload in sorted(correlations.items()):
        matrix = matrix_payload.get("matrix") if isinstance(matrix_payload, dict) and "matrix" in matrix_payload else matrix_payload
        if not isinstance(matrix, dict):
            continue
        for metric_a, cols in sorted(matrix.items()):
            if not isinstance(cols, dict):
                continue
            for metric_b, value in sorted(cols.items()):
                rows.append({"method": method, "metric_a": metric_a, "metric_b": metric_b, "value": value})
    return rows


def _top_overlap_rows(analytics: dict[str, Any]) -> list[dict[str, Any]]:
    top_overlap = analytics.get("top_overlap") if isinstance(analytics.get("top_overlap"), dict) else {}
    matrix = top_overlap.get("matrix") if isinstance(top_overlap.get("matrix"), dict) else {}
    rows: list[dict[str, Any]] = []
    for metric_a, cols in sorted(matrix.items()):
        if not isinstance(cols, dict):
            continue
        for metric_b, cuts in sorted(cols.items()):
            if not isinstance(cuts, dict):
                continue
            for cut, payload in sorted(cuts.items()):
                if isinstance(payload, dict):
                    rows.append({**_flat_scalars(payload), "metric_a": metric_a, "metric_b": metric_b, "top_n": cut})
    return rows


def _rank_delta_rows(analytics: dict[str, Any]) -> list[dict[str, Any]]:
    comparisons = analytics.get("rank_comparisons") if isinstance(analytics.get("rank_comparisons"), dict) else {}
    rows: list[dict[str, Any]] = []
    for metric, payload in sorted(comparisons.items()):
        if isinstance(payload, dict):
            row = {**_flat_scalars({key: value for key, value in payload.items() if key != "largest_shifts"}), "metric": metric}
            rows.append(row)
    return rows


def _flat_scalars(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value is None or isinstance(value, (str, int, float, bool))
    }


def _prune_runs_for_dump(dump_id: str, *, keep: int = 3) -> list[str]:
    safe_dump_id = _safe_id(_resolve_dump_id(str(dump_id or "")))
    if not safe_dump_id or keep < 1:
        return []
    candidates: list[tuple[float, Path]] = []
    for metric_run in (DATA / "runs").glob("run_*/metric_run.json"):
        manifest = _read_artifact_json(metric_run)
        manifest_dump_id = _safe_id(str(manifest.get("dump_id") or manifest.get("input_dump_id") or ""))
        if manifest_dump_id != safe_dump_id:
            continue
        try:
            mtime = metric_run.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((mtime, metric_run.parent))
    candidates.sort(key=lambda item: item[0], reverse=True)
    removed: list[str] = []
    for _, run_dir in candidates[keep:]:
        shutil.rmtree(run_dir, ignore_errors=True)
        removed.append(run_dir.name)
    return removed


def _table_checksums(paths: dict[str, Path]) -> dict[str, str]:
    return {name: sha256_file(path) for name, path in paths.items() if path.is_file()}


def _table_counts(paths: dict[str, Path]) -> dict[str, int | None]:
    return {name: _table_row_count(path) for name, path in paths.items() if path.is_file()}


def _table_row_count(path: str | Path) -> int | None:
    target = Path(path)
    if not target.is_file():
        return None
    try:
        import duckdb

        escaped = str(target).replace("'", "''")
        reader = "read_parquet" if target.suffix == ".parquet" else "read_csv_auto"
        with duckdb.connect(":memory:") as conn:
            return int(conn.execute(f"SELECT count(*) FROM {reader}('{escaped}')").fetchone()[0])
    except Exception:
        return None


def _positive_count(value: int | None) -> bool:
    return value is not None and value > 0


def _table_manifest(paths: dict[str, Path], checksums: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "path": str(path),
            "sha256": checksums.get(name, ""),
            "bytes": path.stat().st_size if path.is_file() else 0,
        }
        for name, path in paths.items()
    }


def _emit_progress(
    progress_callback: StageProgressCallback | None,
    percent: int | None,
    stage: str,
    extra: dict[str, Any] | None = None,
) -> None:
    if progress_callback:
        # Pipeline stages have predictable order but not a reliable duration or
        # row-level denominator, so they are reported as named stages without a
        # synthetic percentage.
        progress_callback(None, stage, extra)


def _cfg(payload: dict[str, Any]) -> Any:
    return author_slice.config_from_payload(payload)


def _openalex_cli_api_key(payload: dict[str, Any], cfg: Any) -> str:
    return str(payload.get("api_key") or os.environ.get(cfg.api_key_env) or "").strip()


def _query_plan_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    plan = payload.get("query_plan") if isinstance(payload.get("query_plan"), dict) else {}
    if not plan:
        return None
    estimate = plan.get("estimate") if isinstance(plan.get("estimate"), dict) else {}
    decision = plan.get("decision") if isinstance(plan.get("decision"), dict) else {}
    if not estimate or not decision:
        return None
    corpus = estimate.get("corpus_request") if isinstance(estimate.get("corpus_request"), dict) else {}
    return {
        "decision": decision,
        "estimate": estimate,
        "openalex_filter": plan.get("openalex_filter") or corpus.get("filter") or "",
        "filter_classes": plan.get("filter_classes") or {},
        "download_policy": plan.get("download_policy") or payload.get("download_policy") or {},
        "limits": plan.get("execution_limits") or plan.get("limits") or {},
    }


def _download_output_dir(payload: dict[str, Any], cfg: Any, *, source_strategy: str = "openalex_cli") -> Path:
    raw_folder_id = str(payload.get("materialization_id") or payload.get("run_id") or "").strip()
    folder_id = _safe_id(raw_folder_id) if raw_folder_id else ""
    raw = str(payload.get("download_dir") or "").strip()
    if not raw:
        source_root = {
            "openalex_api": "openalex_api",
            "api_cursor_selected_fields": "openalex_api",
            "ids_then_hydrate": "openalex_ids",
            "openalex_snapshot_jsonl": "openalex_snapshot",
            "snapshot_partition_scan": "openalex_snapshot",
        }.get(str(source_strategy or "openalex_cli"), "openalex_cli")
        base = DATA / "raw" / source_root / _safe_id(str(cfg.slice_name or "slice"))
        return base / folder_id if folder_id else base
    base = Path(raw).expanduser()
    if not base.is_absolute():
        if base.parts and base.parts[0] == "data":
            base = DATA.joinpath(*base.parts[1:])
        else:
            base = DATA / base
    resolved = base.resolve()
    data_root = DATA.resolve()
    try:
        resolved.relative_to(data_root)
    except ValueError as exc:
        raise ValueError(f"Папка загрузки должна находиться внутри хранилища данных DSS: {DATA}") from exc
    safe_slice = _safe_id(str(cfg.slice_name or "slice"))
    base = resolved if resolved.name == safe_slice else resolved / safe_slice
    return base / folder_id if folder_id else base


def _work_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    raw_ids = payload.get("work_ids")
    ids: list[str] = []
    if isinstance(raw_ids, list):
        ids.extend(str(item).strip() for item in raw_ids if str(item).strip())
    elif isinstance(raw_ids, str):
        ids.extend(part.strip() for part in raw_ids.replace("\n", ",").split(",") if part.strip())
    ids_file = str(payload.get("work_ids_file") or "").strip()
    if ids_file:
        path = resolve_safe_path(ids_file)
        ids.extend(part.strip() for part in path.read_text(encoding="utf-8").replace("\n", ",").split(",") if part.strip())
    return ids


def _snapshot_dir_from_payload(payload: dict[str, Any]) -> Path:
    raw = str(payload.get("snapshot_dir") or payload.get("source_dir") or payload.get("snapshot_path") or "").strip()
    if not raw:
        raise ValueError("Для режима snapshot/partition scan укажите snapshot_dir с локальными JSONL/JSONL.GZ файлами OpenAlex.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (DATA / path).resolve()
    if not path.exists() or not path.is_dir():
        raise ValueError(f"Папка snapshot не найдена: {path}")
    return path


def _max_download_bytes(payload: dict[str, Any]) -> int:
    raw = payload.get("max_download_bytes")
    if raw in (None, ""):
        mb = payload.get("max_download_mb")
        raw = int(float(mb) * 1024 * 1024) if mb not in (None, "") else 0
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


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
    run_id = str(payload.get("run_id") or "").strip()
    if run_id:
        write_json(DATA / "runs" / _safe_id(run_id) / "passports" / "pipeline_summary.json", doc)


def _archive_run_artifacts(cfg: Any, payload: dict[str, Any]) -> dict[str, Any]:
    raw_run_id = str(payload.get("run_id") or "").strip()
    if not raw_run_id:
        raise ValueError("run_id is required to archive scoped run artifacts")
    run_id = _safe_id(raw_run_id)
    dump_id = _safe_id(str(payload.get("dump_id") or _dump_id_from_payload(payload) or cfg.slice_name))
    run_dir = DATA / "runs" / run_id
    dump_dir = DATA / "dumps" / dump_id
    tables_dir = DATA / "tables" / dump_id
    input_tables = payload.get("input_tables") if isinstance(payload.get("input_tables"), dict) else {}
    run_table_outputs = payload.get("run_table_outputs") if isinstance(payload.get("run_table_outputs"), dict) else {}
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
        "passport_outputs": passport_outputs,
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

    fetch_meta = _artifact_path(payload.get("fetch_meta")) or _artifact_path(dump_dir / "fetch_meta.json")
    if fetch_meta:
        _copy_or_record_artifact(fetch_meta, run_dir / "passports" / "fetch_meta.json", copied, "passports/fetch_meta.json")

    for name in ("works", "authorships", "work_topics", "author_institutions", "author_countries"):
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
    integrity = dump.get("integrity_validation") if isinstance(dump.get("integrity_validation"), dict) else {}
    allowed = bool(dump.get("allowed_for_final_analysis"))
    if integrity and not integrity.get("ok"):
        allowed = False
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
        "integrity_validation": integrity,
        "signature_checks": {
            "estimate_signature_verified": bool(signatures.get("estimate_signature_verified")),
            "accepted_estimate_signature_verified": bool(signatures.get("accepted_estimate_signature_verified")),
            "download_signature_verified": bool(signatures.get("download_signature_verified")),
            "compatible": bool(signatures.get("compatible")),
        },
        "warning": "" if allowed else "This analysis is not eligible for final dissertation-grade conclusions.",
    }


def _apply_quality_eligibility_guard(
    eligibility: dict[str, Any],
    quality: dict[str, Any],
    *,
    dump_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply post-normalization quality gates that are unknowable at download time."""
    counts = quality.get("quality_counts") if isinstance(quality.get("quality_counts"), dict) else {}
    truncated_works = int(counts.get("works_with_truncated_authorships") or 0)
    backfill_status = str((dump_manifest or {}).get("backfill_status") or "").strip().lower()
    if truncated_works <= 0 or backfill_status in {"complete", "completed", "not_required"}:
        return eligibility
    blockers = list(eligibility.get("quality_blockers") or [])
    blockers.append(
        {
            "code": "truncated_authorships_require_backfill",
            "message": (
                "В срезе есть работы с обрезанным списком авторов. "
                "Для финального анализа требуется восстановить authorships по singleton work records "
                "или явно исключить такие работы политикой анализа."
            ),
            "works": truncated_works,
            "required_action": "Запустите восстановление среза и повторите расчет индексов.",
        }
    )
    return {
        **eligibility,
        "status": "blocked_backfill_required",
        "allowed_for_final_analysis": False,
        "warning": (
            "Финальный анализ запрещен: обнаружены работы с обрезанным списком авторов, "
            "а восстановление authorships не завершено."
        ),
        "quality_gate": {
            "status": "blocked",
            "reason": "truncated_authorships_require_backfill",
            "works_with_truncated_authorships": truncated_works,
            "backfill_status": backfill_status or "missing",
        },
        "quality_blockers": blockers,
    }


def _recover_analysis_eligibility(payload: dict[str, Any], *, dump_id: str = "", run_id: str = "") -> dict[str, Any]:
    if isinstance(payload.get("analysis_eligibility"), dict):
        return payload["analysis_eligibility"]
    dump_id = _resolve_dump_id(dump_id)
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


def _resolve_dump_id(dump_id: str) -> str:
    raw = str(dump_id or "").strip()
    if not raw:
        return ""
    safe = _safe_id(raw)
    if (DATA / "tables" / safe).exists() or (DATA / "dumps" / safe).exists():
        return raw
    if not safe.startswith("dump_"):
        candidate = f"dump_{safe}"
        if (DATA / "tables" / candidate).exists() or (DATA / "dumps" / candidate).exists():
            return candidate
    return raw


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
        "lrdi_p0": cfg.lrdi_p0,
        "lrdi_lambda": cfg.lrdi_lambda,
        "analysis_year": cfg.analysis_year,
    }


def _write_runtime_config(cfg: Any) -> None:
    write_config(cfg, DATA / "runtime/slice_config.yaml")
