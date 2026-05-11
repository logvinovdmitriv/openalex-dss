from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import yaml

from app.core.paths import DATA, ROOT
from app.services import cohorts, custom_metrics, scientometrics, warehouse
from app.services.analysis_filters import clean_analysis_filters


REPORT_BUNDLE_SCHEMA = "report_bundle"
REPORT_SCOPE_SCHEMA = "report_scope"
DEFAULT_REPORT_SCIENTOMETRIC_METRICS = ("p", "c", "cpp", "h", "i10", "g")
REPORT_BUNDLE_KEEP = 5


def build_report_bundle(
    metric: str = "h",
    fraction_mode: str = "strict_authors_count",
    limit: int = 50,
    *,
    run_id: str = "",
    dump_id: str = "",
    filters: dict[str, Any] | None = None,
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
    scientometric_metrics: list[str] | tuple[str, ...] | str | None = None,
    baseline_metric: str = "h",
    rank_top_n: int = 100,
    data_filters: dict[str, Any] | None = None,
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = 0,
    custom_metric_defs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    filters = _clean_filters(filters or {})
    custom_metric_defs = custom_metrics.parse_custom_metrics(custom_metric_defs)
    data_filters = warehouse.parse_column_filters(data_filters)
    data_sort = str(data_sort or "").strip()
    data_direction = "asc" if str(data_direction or "").strip().lower() == "asc" else "desc"
    data_limit = max(0, min(_int_value(data_limit, 0), 500_000))
    scientometric_metric_list = _scientometric_metrics(scientometric_metrics)
    baseline_metric = str(baseline_metric or "h").strip() or "h"
    rank_top_n = max(1, min(int(rank_top_n or 100), 1000))
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
        cohort_filter_policy = str(cohort_ctx.get("filter_policy") or cohort_filter_policy or "membership")
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
            scientometric_metrics=scientometric_metric_list,
            baseline_metric=baseline_metric,
            rank_top_n=rank_top_n,
            data_filters=data_filters,
            data_sort=data_sort,
            data_direction=data_direction,
            data_limit=data_limit,
            custom_metric_defs=custom_metric_defs,
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
        scientometric_metrics=scientometric_metric_list,
        baseline_metric=baseline_metric,
        rank_top_n=rank_top_n,
        data_filters=data_filters,
        data_sort=data_sort,
        data_direction=data_direction,
        data_limit=data_limit,
        custom_metric_defs=custom_metric_defs,
    )
    scope_hash = report_scope["report_scope_hash"]
    docs = _run_report_artifacts(run_id)
    missing = [name for name, value in docs.items() if not value]
    if missing:
        report = _incomplete_run_report(run_id=run_id, dump_id=dump_id, missing=missing, report_scope=report_scope)
        _write_report_bundle(run_id, scope_hash, report)
        return report
    state = docs["pipeline"]
    quality = docs["quality"]
    checksums = docs["checksums"]
    slice_passport = docs["slice_passport"]
    calculation_passport = docs["calculation_passport"]
    current_slice = state.get("slice") or state.get("current_slice") or {}
    request = state.get("request") or {}
    analysis_eligibility = calculation_passport.get("analysis_eligibility") or {"status": "unknown", "allowed_for_final_analysis": False}
    analysis_status = _analysis_status(analysis_eligibility, checksums)

    data_selection_kwargs = _data_selection_kwargs(data_filters=data_filters, data_sort=data_sort, data_direction=data_direction, data_limit=data_limit)
    top = warehouse.metric_ranking(
        fraction_mode,
        metric,
        filters,
        limit=limit,
        max_limit=500,
        run_id=run_id,
        dump_id=dump_id,
        author_ids=cohort_author_ids,
        custom_metric_defs=custom_metric_defs,
        **data_selection_kwargs,
    )
    distribution = warehouse.metric_distribution(
        fraction_mode,
        metric,
        filters,
        run_id=run_id,
        dump_id=dump_id,
        author_ids=cohort_author_ids,
        custom_metric_defs=custom_metric_defs,
        **data_selection_kwargs,
    )
    resolved_dump_id = dump_id or str(top.get("dump_id") or calculation_passport.get("dump_id") or "")
    report_scope["dump_id"] = resolved_dump_id
    scientometric_analysis = scientometrics.build_scientometric_analysis(
        fraction_mode=fraction_mode,
        metrics=scientometric_metric_list,
        baseline_metric=baseline_metric,
        filters=filters,
        run_id=run_id,
        dump_id=resolved_dump_id,
        cohort_id=cohort_id,
        cohort_filter_policy=cohort_filter_policy,
        top_n=rank_top_n,
        data_filters=data_filters,
        data_sort=data_sort,
        data_direction=data_direction,
        data_limit=data_limit,
        custom_metric_defs=custom_metric_defs,
    )
    custom_metric_query = json.dumps(custom_metric_defs, ensure_ascii=False) if custom_metric_defs else ""
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
            "data_filters": json.dumps(data_filters, ensure_ascii=False) if data_filters else "",
            "data_sort": data_sort,
            "data_direction": data_direction if data_sort else "",
            "data_limit": data_limit if data_limit else "",
            "custom_metric_defs": custom_metric_query,
        }
    )
    statistics_query = _query_params(
        {
            **filters,
            "fraction_mode": fraction_mode,
            "run_id": run_id,
            "dump_id": resolved_dump_id,
            "cohort_filter_policy": cohort_filter_policy,
            "data_filters": json.dumps(data_filters, ensure_ascii=False) if data_filters else "",
            "data_sort": data_sort,
            "data_direction": data_direction if data_sort else "",
            "data_limit": data_limit if data_limit else "",
            "custom_metric_defs": custom_metric_query,
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
            "scientometric_metrics": ",".join(scientometric_metric_list),
            "baseline_metric": baseline_metric,
            "rank_top_n": rank_top_n,
            "data_filters": json.dumps(data_filters, ensure_ascii=False) if data_filters else "",
            "data_sort": data_sort,
            "data_direction": data_direction if data_sort else "",
            "data_limit": data_limit if data_limit else "",
            "custom_metric_defs": custom_metric_query,
        }
    )
    scientometric_query = _query_params(
        {
            **filters,
            "fraction_mode": fraction_mode,
            "metrics": ",".join(scientometric_metric_list),
            "baseline_metric": baseline_metric,
            "top_n": rank_top_n,
            "run_id": run_id,
            "dump_id": resolved_dump_id,
            "cohort_id": cohort_id,
            "cohort_filter_policy": cohort_filter_policy,
            "data_filters": json.dumps(data_filters, ensure_ascii=False) if data_filters else "",
            "data_sort": data_sort,
            "data_direction": data_direction if data_sort else "",
            "data_limit": data_limit if data_limit else "",
            "custom_metric_defs": custom_metric_query,
        }
    )
    exports = {
        "ranking_csv": f"/api/v1/analytics/ranking.csv?{export_query}",
        "cohort_author_metrics_csv": f"/api/v1/cohorts/{cohort_id}/author-metrics.csv?{export_query}" if cohort_id else None,
        "cohort_author_metrics_json": f"/api/v1/cohorts/{cohort_id}/author-metrics.json?{export_query}" if cohort_id else None,
        "cohort_statistics_json": f"/api/v1/cohorts/{cohort_id}/statistics?{statistics_query}" if cohort_id else None,
        "scientometrics_json": f"/api/v1/analytics/scientometrics.json?{scientometric_query}",
        "scientometrics_descriptive_csv": f"/api/v1/analytics/scientometrics/descriptive.csv?{scientometric_query}",
        "scientometrics_correlations_csv": f"/api/v1/analytics/scientometrics/correlations.csv?{scientometric_query}",
        "scientometrics_outliers_csv": f"/api/v1/analytics/scientometrics/outliers.csv?{scientometric_query}",
        "scientometrics_top_outliers_csv": f"/api/v1/analytics/scientometrics/top-outliers.csv?{scientometric_query}",
        "scientometrics_findings_csv": f"/api/v1/analytics/scientometrics/findings.csv?{scientometric_query}",
        "scientometrics_conclusion_md": f"/api/v1/analytics/scientometrics/conclusion.md?{scientometric_query}",
        "report_bundle_json": f"/api/v1/reports/bundle.json?{bundle_query}" if bundle_query else "/api/v1/reports/bundle.json",
        "sha256_manifest": checksums.get("sha256_manifest"),
    }
    exports.update(
        _local_data_csv_exports(
            run_id=run_id,
            dump_id=resolved_dump_id,
            data_filters=data_filters,
            data_sort=data_sort,
            data_direction=data_direction,
        )
    )

    report = {
        "schema": REPORT_BUNDLE_SCHEMA,
        "status": "ok",
        "run_id": run_id,
        "dump_id": resolved_dump_id,
        "report_scope": report_scope,
        "filters": filters,
        "data_filters": data_filters,
        "data_sort": data_sort,
        "data_direction": data_direction,
        "data_limit": data_limit,
        "custom_metrics": custom_metrics.metric_catalog(custom_metric_defs),
        "cohort_id": cohort_id,
        "cohort": _cohort_summary(cohort),
        "cohort_context": cohorts.cohort_context_summary(cohort_ctx) if cohort_ctx else None,
        "warnings": _report_warnings(cohort_filter_policy),
        "interpretation_policy": {
            "strict_mode": "Математические выводы строятся только по локально пересчитанным works-based индексам.",
            "api_usage": "OpenAlex API используется для подсказок, ID, оценки, справочников лимитов и точечного обогащения. Уже скачанные локальные срезы анализируются без API; новая загрузка через установленный загрузчик OpenAlex может требовать ключ OpenAlex.",
            "decision_boundary": "Метрики формируют пул кандидатов и объяснение, но не заменяют экспертное решение.",
        },
        "slice_passport": slice_passport,
        "calculation_passport": calculation_passport,
        "analysis_eligibility": analysis_eligibility,
        "analysis_status": analysis_status,
        "current_slice": current_slice,
        "openalex_request": request,
        "quality_report": quality,
        "funnel": _quality_funnel(quality, run_id=run_id),
        "rank_table": top,
        "distribution": distribution,
        "scientometric_analysis": scientometric_analysis,
        "checksums": checksums,
        "exports": exports,
        "export_notes": {
            "scientometrics_outliers_csv": "Contains all IQR outliers for the selected scientometric metrics.",
            "scientometrics_top_outliers_csv": "Contains the compact top outlier rows exposed in the scientometric JSON/boxplot payload.",
            "scientometrics_findings_csv": "Contains structured interpretation findings with evidence JSON for the selected scientometric analysis scope.",
            "scientometrics_conclusion_md": "Contains the deterministic conclusion draft rendered as Markdown for the selected scientometric analysis scope.",
        },
        "methodology_protocol": {
            "analysis_protocol_id": "baseline_core" if not custom_metric_defs else "custom_formula_validation",
            "protocol_version": _analysis_protocol_version(),
            "source_mode": "openalex_cli_filtered_metadata",
            "storage_rule": "raw immutable dump -> dump tables -> run-scoped metric tables",
            "topic_mapping_rule": "ВАК-код не является OpenAlex-фильтром; mapping фиксируется отдельно как resolved entities / mapping file.",
            "pci_percentile_composite_formula": "100 * (pr(P) * pr(h) * pr(C_frac)) ** (1/3)",
            "iupv_s_formula": "100 * percentile_rank(sum(log1p(cited_credit)))",
            "islv_formula": "100 * weighted_geomean(pr(h), pr(C_frac), pr(g), pr(i10), pr(P)) * (1 - lambda * max(0, top1_share - tau))",
            "polyanin_status": "f5/fm5 are operational threshold metrics until a primary source definition is confirmed.",
        },
    }
    _write_report_bundle(run_id, scope_hash, report)
    return report


def _analysis_status(analysis_eligibility: dict[str, Any], checksums: dict[str, Any]) -> dict[str, Any]:
    allowed = bool(analysis_eligibility.get("allowed_for_final_analysis"))
    if not allowed:
        status = "blocked" if analysis_eligibility.get("status") not in {"unknown", "exploratory"} else "exploratory"
    elif checksums.get("sha256_manifest"):
        status = "final_reproducible"
    else:
        status = "pilot_ready"
    return {
        "status": status,
        "allowed_for_final_report": status == "final_reproducible",
        "message": {
            "final_reproducible": "Финальный воспроизводимый анализ: dump полный, gate пройден, checksums доступны.",
            "pilot_ready": "Пилотный анализ: расчет разрешен, но полный checksum-manifest не найден.",
            "exploratory": "Предварительный анализ: результат можно исследовать, но нельзя выдавать как финальный.",
            "blocked": "Финальный анализ заблокирован условиями качества или полноты данных.",
        }.get(status, status),
    }


def _analysis_protocol_version() -> str:
    path = ROOT / "configs/analysis_protocols.yaml"
    if not path.is_file():
        return "0"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return "0"
    return str(data.get("version") or "1.0")


def report_bundle_json(
    *,
    run_id: str = "",
    dump_id: str = "",
    metric: str = "h",
    fraction_mode: str = "strict_authors_count",
    limit: int = 50,
    filters: dict[str, Any] | None = None,
    cohort_id: str = "",
    cohort_filter_policy: str = "membership",
    scientometric_metrics: list[str] | tuple[str, ...] | str | None = None,
    baseline_metric: str = "h",
    rank_top_n: int = 100,
    data_filters: dict[str, Any] | None = None,
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = 0,
    custom_metric_defs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return build_report_bundle(
        metric=metric,
        fraction_mode=fraction_mode,
        limit=limit,
        run_id=run_id,
        dump_id=dump_id,
        filters=filters,
        cohort_id=cohort_id,
        cohort_filter_policy=cohort_filter_policy,
        scientometric_metrics=scientometric_metrics,
        baseline_metric=baseline_metric,
        rank_top_n=rank_top_n,
        data_filters=data_filters,
        data_sort=data_sort,
        data_direction=data_direction,
        data_limit=data_limit,
        custom_metric_defs=custom_metric_defs,
    )


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


def _report_bundle_path(run_id: str, scope_hash: str) -> Path:
    if not str(run_id or "").strip() or not str(scope_hash or "").strip():
        raise ValueError("run_id and report_scope_hash are required for report bundle persistence")
    return DATA / "runs" / _safe_id(run_id) / "reports" / f"report_{_safe_id(scope_hash)}.json"


def _write_report_bundle(run_id: str, scope_hash: str, report: dict[str, Any]) -> Path:
    path = _report_bundle_path(run_id, scope_hash)
    _write_json(path, report)
    _prune_report_bundles(run_id, keep=report_bundle_keep())
    return path


def _prune_report_bundles(run_id: str, *, keep: int = REPORT_BUNDLE_KEEP) -> list[str]:
    if keep < 1:
        return []
    reports_dir = DATA / "runs" / _safe_id(run_id) / "reports"
    if not reports_dir.is_dir():
        return []
    files = sorted(reports_dir.glob("report_*.json"), key=_path_mtime, reverse=True)
    removed: list[str] = []
    for path in files[keep:]:
        try:
            path.unlink()
            removed.append(str(path))
        except OSError:
            continue
    return removed


def report_bundle_keep() -> int:
    config_path = ROOT / "configs" / "execution_limits.yaml"
    try:
        doc = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        policy = doc.get("storage_policy") if isinstance(doc, dict) else {}
        value = int((policy or {}).get("max_retained_report_bundles_per_run", REPORT_BUNDLE_KEEP))
    except Exception:
        value = REPORT_BUNDLE_KEEP
    return max(1, value)


def _path_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _run_report_artifacts(run_id: str) -> dict[str, dict[str, Any]]:
    return {
        "pipeline": warehouse.read_json_doc("pipeline", run_id=run_id) or {},
        "quality": warehouse.read_json_doc("quality", run_id=run_id) or {},
        "checksums": warehouse.read_json_doc("checksums", run_id=run_id) or {},
        "slice_passport": _read_run_json(run_id, "slice_passport.json"),
        "calculation_passport": _read_run_json(run_id, "calculation_passport.json"),
    }


def _read_run_json(run_id: str, filename: str) -> dict[str, Any]:
    return _read_json(DATA / "runs" / _safe_id(run_id) / "passports" / filename)


def _incomplete_run_report(*, run_id: str, dump_id: str, missing: list[str], report_scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": REPORT_BUNDLE_SCHEMA,
        "status": "incomplete_run_artifacts",
        "run_id": run_id,
        "dump_id": dump_id,
        "report_scope": report_scope,
        "missing_artifacts": missing,
        "message": "Run-scoped report was not built because one or more artifacts are missing for the selected run_id.",
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
    cohort_filter_policy: str = "membership",
    scientometric_metrics: list[str] | tuple[str, ...] | None = None,
    baseline_metric: str = "h",
    rank_top_n: int = 100,
    data_filters: dict[str, Any] | None = None,
    data_sort: str = "",
    data_direction: str = "desc",
    data_limit: int = 0,
    custom_metric_defs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    membership_filters = _clean_filters(cohort_membership_filters or {})
    data_filters = warehouse.parse_column_filters(data_filters)
    data_sort = str(data_sort or "").strip()
    data_direction = "asc" if str(data_direction or "").strip().lower() == "asc" else "desc"
    data_limit = max(0, min(_int_value(data_limit, 0), 500_000))
    scientometric_metric_list = _scientometric_metrics(scientometric_metrics)
    custom_metric_defs = custom_metrics.parse_custom_metrics(custom_metric_defs)
    canonical = {
        "schema": REPORT_SCOPE_SCHEMA,
        "run_id": run_id,
        "dump_id": dump_id,
        "filters": _clean_filters(filters),
        "data_filters": data_filters,
        "data_filters_hash": _hash_dict(data_filters),
        "data_sort": data_sort,
        "data_direction": data_direction,
        "data_limit": data_limit,
        "cohort_id": str(cohort_id or "").strip(),
        "cohort_checksum": str(cohort_checksum or "").strip(),
        "cohort_n_authors": int(cohort_n_authors or 0),
        "cohort_membership_filters": membership_filters,
        "cohort_membership_filters_hash": _hash_dict(membership_filters),
        "cohort_filter_policy": str(cohort_filter_policy or "membership").strip().lower(),
        "metric": str(metric or "").strip(),
        "fraction_mode": str(fraction_mode or "").strip(),
        "limit": int(limit or 0),
        "scientometric_metrics": scientometric_metric_list,
        "custom_metrics": custom_metrics.metric_catalog(custom_metric_defs),
        "scientometric_analysis_schema": scientometrics.SCIENTOMETRIC_ANALYSIS_SCHEMA,
        "scientometric_findings_schema": scientometrics.SCIENTOMETRIC_FINDINGS_SCHEMA,
        "scientometric_conclusion_schema": scientometrics.SCIENTOMETRIC_CONCLUSION_SCHEMA,
        "baseline_metric": str(baseline_metric or "h").strip() or "h",
        "rank_top_n": max(1, min(int(rank_top_n or 100), 1000)),
    }
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {**canonical, "report_scope_hash": hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]}


def _preview_report(report_scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": REPORT_BUNDLE_SCHEMA,
        "status": "preview_not_reproducible",
        "run_id": str(report_scope.get("run_id") or ""),
        "dump_id": str(report_scope.get("dump_id") or ""),
        "report_scope": report_scope,
        "message": "Final report build requires explicit run_id with run-scoped passports, checksums and local metric tables.",
    }


def _report_warnings(cohort_filter_policy: str) -> list[str]:
    del cohort_filter_policy
    return []


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


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _scientometric_metrics(metrics: list[str] | tuple[str, ...] | str | None) -> list[str]:
    if isinstance(metrics, str):
        raw = metrics.replace("|", ",").split(",")
    else:
        raw = list(metrics or DEFAULT_REPORT_SCIENTOMETRIC_METRICS)
    values = [str(metric).strip() for metric in raw if str(metric).strip()]
    if not values:
        values = list(DEFAULT_REPORT_SCIENTOMETRIC_METRICS)
    unique: list[str] = []
    for metric in values:
        if metric not in unique:
            unique.append(metric)
    return unique


def _query_params(params: dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if str(value or "").strip()}
    return urlencode(clean)


def _data_selection_kwargs(*, data_filters: dict[str, Any], data_sort: str, data_direction: str, data_limit: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if data_filters:
        out["data_filters"] = data_filters
    if data_sort:
        out["data_sort"] = data_sort
        out["data_direction"] = data_direction
    if data_limit > 0:
        out["data_limit"] = data_limit
    return out


def _local_data_csv_export(
    kind: str,
    *,
    run_id: str = "",
    dump_id: str = "",
    data_filters: dict[str, Any] | None = None,
    data_sort: str = "",
    data_direction: str = "desc",
) -> str:
    query = _query_params(
        {
            "kind": kind,
            "run_id": run_id,
            "dump_id": dump_id,
            "data_filters": json.dumps(data_filters, ensure_ascii=False) if data_filters else "",
            "sort": data_sort,
            "direction": data_direction if data_sort else "",
        }
    )
    return f"/api/v1/local-data/preview.csv?{query}"


def _local_data_csv_exports(
    *,
    run_id: str = "",
    dump_id: str = "",
    data_filters: dict[str, Any] | None = None,
    data_sort: str = "",
    data_direction: str = "desc",
) -> dict[str, str]:
    if not (str(run_id or "").strip() or str(dump_id or "").strip()):
        return {}
    return {
        "local_indices_csv": _local_data_csv_export(
            "indices", run_id=run_id, dump_id=dump_id, data_filters=data_filters, data_sort=data_sort, data_direction=data_direction
        ),
        "local_works_csv": _local_data_csv_export(
            "works", run_id=run_id, dump_id=dump_id, data_filters=data_filters, data_sort=data_sort, data_direction=data_direction
        ),
        "local_authorships_csv": _local_data_csv_export(
            "authorships", run_id=run_id, dump_id=dump_id, data_filters=data_filters, data_sort=data_sort, data_direction=data_direction
        ),
        "local_work_topics_csv": _local_data_csv_export(
            "work_topics", run_id=run_id, dump_id=dump_id, data_filters=data_filters, data_sort=data_sort, data_direction=data_direction
        ),
    }


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in str(value).strip())[:140] or "artifact"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
