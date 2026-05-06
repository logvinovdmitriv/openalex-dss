from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from app.core.paths import DATA, JSON_FILES
from app.services import cohorts, warehouse
from app.services.analysis_filters import clean_analysis_filters


def build_report_bundle(
    metric: str = "islv",
    fraction_mode: str = "strict_authors_count",
    limit: int = 50,
    *,
    run_id: str = "",
    dump_id: str = "",
    filters: dict[str, Any] | None = None,
    cohort_id: str = "",
    cohort_filter_policy: str = "auto",
) -> dict[str, Any]:
    filters = _clean_filters(filters or {})
    cohort: dict[str, Any] = {}
    cohort_ctx: dict[str, Any] = {}
    cohort_author_ids: set[str] | None = None
    if cohort_id:
        cohort_ctx = cohorts.resolve_cohort_context(cohort_id, run_id=run_id, dump_id=dump_id, fraction_mode=fraction_mode, filters=filters, filter_policy=cohort_filter_policy)
        cohort = cohort_ctx["cohort"]
        cohort_author_ids = cohort_ctx["author_ids"]
        run_id = cohort_ctx["run_id"]
        dump_id = cohort_ctx["dump_id"]
        filters = cohort_ctx["filters"]
        cohort_filter_policy = str(cohort_ctx.get("filter_policy") or cohort_filter_policy or "auto")
    scope = warehouse.resolve_analysis_scope(run_id=run_id, dump_id=dump_id)
    run_id = scope["run_id"]
    dump_id = scope["dump_id"]
    if not run_id:
        report_scope = _report_scope(
            run_id=run_id,
            dump_id=dump_id,
            filters=filters,
            cohort_id=cohort_id,
            cohort_checksum=str(cohort.get("checksum") or ""),
            cohort_n_authors=int(cohort.get("n_authors") or 0),
            cohort_membership_filters=cohort_ctx.get("membership_filters") or cohort.get("filters") or {},
            cohort_filter_policy=cohort_filter_policy,
            metric=metric,
            fraction_mode=fraction_mode,
            limit=limit,
        )
        return _preview_report(report_scope)
    report_scope = _report_scope(
        run_id=run_id,
        dump_id=dump_id,
        filters=filters,
        cohort_id=cohort_id,
        cohort_checksum=str(cohort.get("checksum") or ""),
        cohort_n_authors=int(cohort.get("n_authors") or 0),
        cohort_membership_filters=cohort_ctx.get("membership_filters") or cohort.get("filters") or {},
        cohort_filter_policy=cohort_filter_policy,
        metric=metric,
        fraction_mode=fraction_mode,
        limit=limit,
    )
    scope_hash = report_scope["report_scope_hash"]
    docs = _run_report_artifacts(run_id)
    missing = [name for name, value in docs.items() if not value]
    if missing:
        report = _incomplete_run_report(run_id=run_id, dump_id=dump_id, missing=missing, report_scope=report_scope)
        _write_json(_report_bundle_path(run_id, scope_hash), report)
        return report
    state = docs["pipeline"]
    quality = docs["quality"]
    stats = docs["stats"]
    theory = docs["theory"]
    checksums = docs["checksums"]
    slice_passport = docs["slice_passport"]
    calculation_passport = docs["calculation_passport"]
    current_slice = state.get("slice") or state.get("current_slice") or {}
    request = state.get("request") or {}
    analysis_eligibility = calculation_passport.get("analysis_eligibility") or {"status": "unknown", "allowed_for_final_analysis": False}

    top = warehouse.metric_ranking(fraction_mode, metric, filters, limit=limit, max_limit=500, run_id=run_id, dump_id=dump_id, author_ids=cohort_author_ids)
    distribution = warehouse.metric_distribution(fraction_mode, metric, filters, run_id=run_id, dump_id=dump_id, author_ids=cohort_author_ids)
    resolved_dump_id = dump_id or str(top.get("dump_id") or calculation_passport.get("dump_id") or "")
    report_scope["dump_id"] = resolved_dump_id
    export_query = _query_params(
        {
            **filters,
            "fraction_mode": fraction_mode,
            "metric": metric,
            "limit": limit,
            "run_id": run_id,
            "dump_id": resolved_dump_id,
            "cohort_id": cohort_id,
            "cohort_filter_policy": cohort_filter_policy,
        }
    )
    bundle_query = _query_params(
        {
            **filters,
            "fraction_mode": fraction_mode,
            "metric": metric,
            "limit": limit,
            "run_id": run_id,
            "dump_id": resolved_dump_id,
            "cohort_id": cohort_id,
            "cohort_filter_policy": cohort_filter_policy,
        }
    )
    report = {
        "bundle_version": "report_bundle_v1",
        "status": "ok",
        "no_latest_fallback": bool(run_id),
        "run_id": run_id,
        "dump_id": resolved_dump_id,
        "report_scope": report_scope,
        "filters": filters,
        "cohort_id": cohort_id,
        "cohort": _cohort_summary(cohort),
        "cohort_context": cohorts.cohort_context_summary(cohort_ctx) if cohort_ctx else None,
        "interpretation_policy": {
            "strict_mode": "Математические выводы строятся только по локально пересчитанным works-based индексам.",
            "api_usage": "OpenAlex API используется для подсказок, ID, оценки, справочников лимитов и точечного обогащения; корпус Works скачивается через OpenAlex CLI.",
            "decision_boundary": "Метрики формируют пул кандидатов и объяснение, но не заменяют экспертное решение.",
        },
        "slice_passport": slice_passport,
        "calculation_passport": calculation_passport,
        "analysis_eligibility": analysis_eligibility,
        "current_slice": current_slice,
        "openalex_request": request,
        "quality_report": quality,
        "funnel": _quality_funnel(quality, run_id=run_id),
        "rank_table": top,
        "distribution": distribution,
        "statistics": stats,
        "stability_report": {
            "top1_sensitivity": theory.get("top1_sensitivity"),
            "fraction_mode_sensitivity": theory.get("fraction_mode_sensitivity"),
            "prefix_convergence": theory.get("prefix_convergence"),
        },
        "checksums": checksums,
        "exports": {
            "ranking_csv": f"/api/v1/analytics/ranking.csv?{export_query}",
            "cohort_author_metrics_csv": f"/api/v1/cohorts/{cohort_id}/author-metrics.csv?{export_query}" if cohort_id else None,
            "cohort_author_metrics_json": f"/api/v1/cohorts/{cohort_id}/author-metrics.json?{export_query}" if cohort_id else None,
            "cohort_statistics_json": f"/api/v1/cohorts/{cohort_id}/statistics?{export_query}" if cohort_id else None,
            "authors_local_metrics_csv": f"/api/v1/exports/authors_local_metrics.csv?run_id={run_id}" if run_id else "/api/v1/exports/authors_local_metrics.csv",
            "works_csv": f"/api/v1/exports/works.csv?run_id={run_id}" if run_id else "/api/v1/exports/works.csv",
            "authorships_csv": f"/api/v1/exports/authorships.csv?run_id={run_id}" if run_id else "/api/v1/exports/authorships.csv",
            "report_bundle_json": f"/api/v1/reports/bundle.json?{bundle_query}" if bundle_query else "/api/v1/reports/bundle.json",
            "sha256_manifest": checksums.get("sha256_manifest"),
        },
        "mvp_protocol": {
            "source_mode": "openalex_cli_filtered_metadata",
            "storage_rule": "raw immutable dump -> thin curated slice -> transient marts",
            "topic_mapping_rule": "ВАК-код не является OpenAlex-фильтром; mapping фиксируется отдельно как resolved entities / mapping file.",
            "iupv_formula": "100 * (pr(P) * pr(h) * pr(C_frac)) ** (1/3)",
            "islv_formula": "100 * weighted_geomean(pr(h), pr(C_frac), pr(g), pr(i10), pr(P)) * (1 - lambda * max(0, top1_share - tau))",
            "polyanin_status": "f5/fm5 are operational threshold metrics until a primary source definition is confirmed.",
        },
    }
    _write_json(_report_bundle_path(run_id, scope_hash), report)
    return report


def report_bundle_json(
    *,
    run_id: str = "",
    dump_id: str = "",
    metric: str = "islv",
    fraction_mode: str = "strict_authors_count",
    limit: int = 50,
    filters: dict[str, Any] | None = None,
    cohort_id: str = "",
    cohort_filter_policy: str = "auto",
) -> dict[str, Any]:
    filters = _clean_filters(filters or {})
    cohort: dict[str, Any] = {}
    cohort_ctx: dict[str, Any] = {}
    if cohort_id:
        cohort_ctx = cohorts.resolve_cohort_context(cohort_id, run_id=run_id, dump_id=dump_id, fraction_mode=fraction_mode, filters=filters, filter_policy=cohort_filter_policy)
        cohort = cohort_ctx["cohort"]
        run_id = cohort_ctx["run_id"]
        dump_id = cohort_ctx["dump_id"]
        filters = cohort_ctx["filters"]
        cohort_filter_policy = str(cohort_ctx.get("filter_policy") or cohort_filter_policy or "auto")
    scope = warehouse.resolve_analysis_scope(run_id=run_id, dump_id=dump_id)
    run_id = scope["run_id"]
    dump_id = scope["dump_id"]
    report_scope = _report_scope(
        run_id=run_id,
        dump_id=dump_id,
        filters=filters,
        cohort_id=cohort_id,
        cohort_checksum=str(cohort.get("checksum") or ""),
        cohort_n_authors=int(cohort.get("n_authors") or 0),
        cohort_membership_filters=cohort_ctx.get("membership_filters") or cohort.get("filters") or {},
        cohort_filter_policy=cohort_filter_policy,
        metric=metric,
        fraction_mode=fraction_mode,
        limit=limit,
    )
    if not run_id:
        return build_report_bundle(metric=metric, fraction_mode=fraction_mode, limit=limit, run_id=run_id, dump_id=dump_id, filters=filters, cohort_id=cohort_id, cohort_filter_policy=cohort_filter_policy)
    path = _report_bundle_path(run_id, report_scope["report_scope_hash"])
    if path.exists():
        cached = _read_json(path)
        cached_dump_id = str(cached.get("dump_id") or "").strip()
        if run_id and dump_id and cached_dump_id != dump_id:
            if cached_dump_id:
                raise ValueError(f"Cached report dump_id={cached_dump_id} is incompatible with requested dump_id={dump_id}")
            return build_report_bundle(metric=metric, fraction_mode=fraction_mode, limit=limit, run_id=run_id, dump_id=dump_id, filters=filters, cohort_id=cohort_id, cohort_filter_policy=cohort_filter_policy)
        if not run_id or cached.get("status") != "incomplete_run_artifacts":
            return cached
    legacy_path = _report_bundle_path(run_id)
    if legacy_path.exists():
        legacy = _read_json(legacy_path)
        cached_dump_id = str(legacy.get("dump_id") or "").strip()
        if run_id and dump_id and cached_dump_id and cached_dump_id != dump_id:
            raise ValueError(f"Cached report dump_id={cached_dump_id} is incompatible with requested dump_id={dump_id}")
    return build_report_bundle(metric=metric, fraction_mode=fraction_mode, limit=limit, run_id=run_id, dump_id=dump_id, filters=filters, cohort_id=cohort_id, cohort_filter_policy=cohort_filter_policy)


def _quality_funnel(quality: dict[str, Any], *, run_id: str = "") -> list[dict[str, Any]]:
    counts = quality.get("quality_counts") or {}
    raw_works = int(quality.get("raw_works") or 0)
    works_rows = int(quality.get("works_rows") or 0)
    authorships = int(quality.get("authorship_rows") or 0)
    null_authors = int(counts.get("authorships_null_author_id") or 0)
    deleted_authors = int(counts.get("authorships_deleted_author_id") or 0)
    return [
        {"stage": "Сырые работы", "count": raw_works},
        {"stage": "Работы после dedupe", "count": works_rows},
        {"stage": "Authorships", "count": authorships},
        {"stage": "Authorships без NULL/deleted", "count": max(0, authorships - null_authors - deleted_authors)},
        {"stage": "Авторы с локальными индексами", "count": warehouse.count_rows("indices", run_id=run_id)},
    ]


def _report_bundle_path(run_id: str = "", scope_hash: str = "") -> Path:
    if run_id:
        if scope_hash:
            return DATA / "runs" / _safe_id(run_id) / "reports" / f"report_{_safe_id(scope_hash)}.json"
        return DATA / "runs" / _safe_id(run_id) / "results" / "report_bundle.json"
    if scope_hash:
        return DATA / "results" / f"report_bundle_{_safe_id(scope_hash)}.json"
    return JSON_FILES["report_bundle"]


def _run_report_artifacts(run_id: str) -> dict[str, dict[str, Any]]:
    return {
        "pipeline": warehouse.read_json_doc("pipeline", run_id=run_id) or {},
        "quality": warehouse.read_json_doc("quality", run_id=run_id) or {},
        "stats": warehouse.read_json_doc("stats", run_id=run_id) or {},
        "theory": warehouse.read_json_doc("theory", run_id=run_id) or {},
        "checksums": warehouse.read_json_doc("checksums", run_id=run_id) or {},
        "slice_passport": _read_run_json(run_id, "slice_passport.json"),
        "calculation_passport": _read_run_json(run_id, "calculation_passport.json"),
    }


def _read_run_json(run_id: str, filename: str) -> dict[str, Any]:
    return _read_json(DATA / "runs" / _safe_id(run_id) / "passports" / filename)


def _incomplete_run_report(*, run_id: str, dump_id: str, missing: list[str], report_scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "bundle_version": "report_bundle_v1",
        "status": "incomplete_run_artifacts",
        "run_id": run_id,
        "dump_id": dump_id,
        "report_scope": report_scope,
        "missing_artifacts": missing,
        "no_latest_fallback": True,
        "message": "Run-scoped report was not built because one or more artifacts are missing for the selected run_id. Latest-view artifacts were intentionally not used.",
    }


def _clean_filters(filters: dict[str, Any]) -> dict[str, str]:
    return clean_analysis_filters(filters)


def _report_scope(
    *,
    run_id: str,
    dump_id: str,
    filters: dict[str, str],
    cohort_id: str,
    cohort_checksum: str,
    cohort_n_authors: int,
    metric: str,
    fraction_mode: str,
    limit: int,
    cohort_membership_filters: dict[str, Any] | None = None,
    cohort_filter_policy: str = "auto",
) -> dict[str, Any]:
    membership_filters = _clean_filters(cohort_membership_filters or {})
    canonical = {
        "version": "report_scope_v1",
        "run_id": run_id,
        "dump_id": dump_id,
        "filters": _clean_filters(filters),
        "cohort_id": str(cohort_id or "").strip(),
        "cohort_checksum": str(cohort_checksum or "").strip(),
        "cohort_n_authors": int(cohort_n_authors or 0),
        "cohort_membership_filters": membership_filters,
        "cohort_membership_filters_hash": _hash_dict(membership_filters),
        "cohort_filter_policy": str(cohort_filter_policy or "auto").strip().lower(),
        "metric": str(metric or "").strip(),
        "fraction_mode": str(fraction_mode or "").strip(),
        "limit": int(limit or 0),
    }
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {**canonical, "report_scope_hash": hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]}


def _preview_report(report_scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "bundle_version": "report_bundle_v1",
        "status": "preview_not_reproducible",
        "run_id": str(report_scope.get("run_id") or ""),
        "dump_id": str(report_scope.get("dump_id") or ""),
        "report_scope": report_scope,
        "message": "Final report build requires explicit run_id. Dump-only and latest-view report modes are development previews because they do not have run-scoped passports, statistics and checksums.",
        "no_latest_fallback": False,
    }


def _cohort_summary(cohort: dict[str, Any]) -> dict[str, Any] | None:
    if not cohort:
        return None
    return {
        "cohort_id": cohort.get("cohort_id"),
        "name": cohort.get("name"),
        "source": cohort.get("source"),
        "metric": cohort.get("metric"),
        "fraction_mode": cohort.get("fraction_mode"),
        "n_authors": cohort.get("n_authors"),
        "checksum": cohort.get("checksum"),
        "membership_filters": cohort.get("filters") or {},
    }


def _hash_dict(value: dict[str, Any]) -> str:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _query_params(params: dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if str(value or "").strip()}
    return urlencode(clean)


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in str(value).strip())[:140] or "artifact"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
