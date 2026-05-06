from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.paths import DATA, JSON_FILES
from app.services import warehouse


def build_report_bundle(
    metric: str = "islv",
    fraction_mode: str = "strict_authors_count",
    limit: int = 50,
    *,
    run_id: str = "",
    dump_id: str = "",
) -> dict[str, Any]:
    filters: dict[str, str] = {}
    scope = warehouse.resolve_analysis_scope(run_id=run_id, dump_id=dump_id)
    run_id = scope["run_id"]
    dump_id = scope["dump_id"]
    if run_id:
        docs = _run_report_artifacts(run_id)
        missing = [name for name, value in docs.items() if not value]
        if missing:
            report = _incomplete_run_report(run_id=run_id, dump_id=dump_id, missing=missing)
            _write_json(_report_bundle_path(run_id), report)
            return report
        state = docs["pipeline"]
        quality = docs["quality"]
        stats = docs["stats"]
        theory = docs["theory"]
        checksums = docs["checksums"]
        slice_passport = docs["slice_passport"]
        calculation_passport = docs["calculation_passport"]
    else:
        state = warehouse.read_json_doc("pipeline") or {}
        quality = warehouse.read_json_doc("quality") or {}
        stats = warehouse.read_json_doc("stats") or {}
        theory = warehouse.read_json_doc("theory") or {}
        checksums = warehouse.read_json_doc("checksums") or {}
        slice_passport = _read_json(DATA / "passports/slice_passport.json")
        calculation_passport = _read_json(DATA / "passports/calculation_passport.json")
    current_slice = state.get("slice") or state.get("current_slice") or {}
    request = state.get("request") or {}
    analysis_eligibility = calculation_passport.get("analysis_eligibility") or {"status": "unknown", "allowed_for_final_analysis": False}

    top = warehouse.metric_ranking(fraction_mode, metric, filters, limit=limit, max_limit=500, run_id=run_id, dump_id=dump_id)
    resolved_dump_id = dump_id or str(top.get("dump_id") or calculation_passport.get("dump_id") or "")
    scope_params = "".join(
        [
            f"&run_id={run_id}" if run_id else "",
            f"&dump_id={resolved_dump_id}" if resolved_dump_id and not run_id else "",
        ]
    )
    report = {
        "bundle_version": "report_bundle_v1",
        "status": "ok",
        "no_latest_fallback": bool(run_id),
        "run_id": run_id,
        "dump_id": resolved_dump_id,
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
        "statistics": stats,
        "stability_report": {
            "top1_sensitivity": theory.get("top1_sensitivity"),
            "fraction_mode_sensitivity": theory.get("fraction_mode_sensitivity"),
            "prefix_convergence": theory.get("prefix_convergence"),
        },
        "checksums": checksums,
        "exports": {
            "ranking_csv": f"/api/v1/analytics/ranking.csv?fraction_mode={fraction_mode}&metric={metric}{scope_params}",
            "authors_local_metrics_csv": f"/api/v1/exports/authors_local_metrics.csv?run_id={run_id}" if run_id else "/api/v1/exports/authors_local_metrics.csv",
            "works_csv": f"/api/v1/exports/works.csv?run_id={run_id}" if run_id else "/api/v1/exports/works.csv",
            "authorships_csv": f"/api/v1/exports/authorships.csv?run_id={run_id}" if run_id else "/api/v1/exports/authorships.csv",
            "report_bundle_json": f"/api/v1/reports/bundle.json?run_id={run_id}" if run_id else "/api/v1/reports/bundle.json",
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
    _write_json(_report_bundle_path(run_id), report)
    return report


def report_bundle_json(*, run_id: str = "", dump_id: str = "") -> dict[str, Any]:
    path = _report_bundle_path(run_id)
    if path.exists():
        cached = _read_json(path)
        if not run_id or cached.get("status") != "incomplete_run_artifacts":
            return cached
    return build_report_bundle(run_id=run_id, dump_id=dump_id)


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


def _report_bundle_path(run_id: str = "") -> Path:
    if run_id:
        return DATA / "runs" / _safe_id(run_id) / "results" / "report_bundle.json"
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


def _incomplete_run_report(*, run_id: str, dump_id: str, missing: list[str]) -> dict[str, Any]:
    return {
        "bundle_version": "report_bundle_v1",
        "status": "incomplete_run_artifacts",
        "run_id": run_id,
        "dump_id": dump_id,
        "missing_artifacts": missing,
        "no_latest_fallback": True,
        "message": "Run-scoped report was not built because one or more artifacts are missing for the selected run_id. Latest-view artifacts were intentionally not used.",
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
