from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = (ROOT.parent / "openalex-dss-validation-data").resolve()
RUN_ID = "validation_scientometric"
DUMP_ID = "validation_fixture_dump"
FRACTION_MODE = "integer"
BASELINE_METRIC = "h"
RANK_TOP_N = 5
METRICS = ["p", "c", "c_frac", "h", "i10", "g", "iupv_s"]
REQUIRED_INDEX_FIELDS = ["rfi_log_frac", "iupv_s"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a deterministic end-to-end validation of the scientometric DSS pipeline.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA), help="External validation data root. Default: ../openalex-dss-validation-data")
    parser.add_argument("--reset", action="store_true", help="Delete the validation data root before running.")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).expanduser().resolve()
    if data_dir.exists():
        if not args.reset:
            raise SystemExit(f"{data_dir} already exists. Pass --reset to rebuild the deterministic validation artifacts.")
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True)
    os.environ["OPENALEX_DSS_DATA_DIR"] = str(data_dir)

    for path in (ROOT / "apps/api", ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    from app.services import cohorts, pipeline, reports, scientometrics

    raw_path = _write_fixture(data_dir)
    build = pipeline.import_local_file(
        {
            "source_path": str(raw_path),
            "run_id": RUN_ID,
            "dump_id": DUMP_ID,
            "slice_name": "validation_scientometric_fixture",
            "workflow_mode": "strict_works",
            "entity_level": "topic",
            "entity_id_short": "T100",
            "entity_id_full": "https://openalex.org/T100",
            "entity_display_name": "Validation Topic",
            "filter_mode": "primary_topic",
            "country_code": "RU",
            "from_publication_date": "2020-01-01",
            "to_publication_date": "2024-12-31",
            "work_type": "article",
            "fraction_mode_default": FRACTION_MODE,
            "fraction_modes": ["strict_authors_count", "renorm_valid_authors", "integer"],
            "analysis_year": 2026,
            "import_mode": "exploratory",
            "analysis_eligibility": {
                "status": "validation_fixture_not_for_final_analysis",
                "allowed_for_final_analysis": False,
                "warning": "Deterministic local fixture validates the DSS pipeline and exports; it is not a real OpenAlex scientific slice.",
            },
        }
    )
    with patch.object(cohorts.uuid, "uuid4", return_value=SimpleNamespace(hex="validation000000000000000000000000")):
        cohort = cohorts.create_cohort(
            {
                "name": "Первые 5 авторов по индексу Хирша",
                "source": "top_n",
                "run_id": RUN_ID,
                "dump_id": DUMP_ID,
                "fraction_mode": FRACTION_MODE,
                "metric": BASELINE_METRIC,
                "top_n": RANK_TOP_N,
                "filters": {},
            }
        )

    analysis_kwargs = {
        "fraction_mode": FRACTION_MODE,
        "metrics": METRICS,
        "baseline_metric": BASELINE_METRIC,
        "filters": {},
        "run_id": RUN_ID,
        "dump_id": DUMP_ID,
        "cohort_id": cohort["cohort_id"],
        "cohort_filter_policy": "membership",
        "top_n": RANK_TOP_N,
    }
    payload = scientometrics.build_scientometric_analysis(**analysis_kwargs)
    report = reports.build_report_bundle(
        metric=BASELINE_METRIC,
        fraction_mode=FRACTION_MODE,
        limit=RANK_TOP_N,
        run_id=RUN_ID,
        dump_id=DUMP_ID,
        filters={},
        cohort_id=cohort["cohort_id"],
        cohort_filter_policy="membership",
        scientometric_metrics=METRICS,
        baseline_metric=BASELINE_METRIC,
        rank_top_n=RANK_TOP_N,
    )

    exports_dir = data_dir / "validation" / "exports" / RUN_ID
    exports_dir.mkdir(parents=True, exist_ok=True)
    _write_json(exports_dir / "scientometrics.json", payload)
    _write_csv(exports_dir / "descriptive.csv", _descriptive_rows(payload), _descriptive_fields())
    _write_csv(exports_dir / "correlations.csv", _correlation_rows(payload), ["method", "left_metric", "right_metric", "value"])
    _write_csv(
        exports_dir / "outliers.csv",
        scientometrics.build_outlier_export_rows(**analysis_kwargs),
        ["metric", "author_id", "author_display_name", "value", "rule", "lower_fence", "upper_fence"],
    )
    _write_csv(
        exports_dir / "top-outliers.csv",
        _top_outlier_rows(payload),
        ["metric", "author_id", "author_display_name", "value", "rule", "lower_fence", "upper_fence"],
    )
    _write_csv(exports_dir / "findings.csv", _finding_rows(payload), ["id", "type", "metric", "baseline_metric", "severity", "text", "recommendation", "evidence_json"])
    (exports_dir / "conclusion.md").write_text(scientometrics.scientometric_conclusion_markdown(payload), encoding="utf-8", newline="\n")
    _write_json(exports_dir / "report_bundle.json", report)
    artifacts = {
        "raw_fixture": str(raw_path),
        "scientometrics_json": str(exports_dir / "scientometrics.json"),
        "descriptive_csv": str(exports_dir / "descriptive.csv"),
        "correlations_csv": str(exports_dir / "correlations.csv"),
        "outliers_csv": str(exports_dir / "outliers.csv"),
        "top_outliers_csv": str(exports_dir / "top-outliers.csv"),
        "findings_csv": str(exports_dir / "findings.csv"),
        "conclusion_md": str(exports_dir / "conclusion.md"),
        "report_bundle_json": str(exports_dir / "report_bundle.json"),
        "run_report_bundle": str(data_dir / "runs" / RUN_ID / "reports" / f"report_{report['report_scope']['report_scope_hash']}.json"),
    }

    manifest = {
        "status": "ok",
        "validation_mode": "deterministic_local_openalex_like_fixture",
        "data_dir": str(data_dir),
        "run_id": RUN_ID,
        "dump_id": DUMP_ID,
        "cohort_id": cohort["cohort_id"],
        "cohort_checksum": cohort["checksum"],
        "fraction_mode": FRACTION_MODE,
        "baseline_metric": BASELINE_METRIC,
        "rank_top_n": RANK_TOP_N,
        "metrics": METRICS,
        "required_index_fields": REQUIRED_INDEX_FIELDS,
        "raw_works": 12,
        "n_authors": payload["n_authors"],
        "findings": len(payload.get("findings") or []),
        "report_scope_hash": report["report_scope"]["report_scope_hash"],
        "report_bundle_schema": report["schema"],
        "analysis_schema": payload["schema"],
        "findings_schema": payload["finding_summary"]["schema"],
        "conclusion_schema": payload["conclusion_draft"]["schema"],
        "analysis_eligibility": build["analysis_eligibility"],
        "artifacts": artifacts,
        "artifact_checksums": _artifact_checksums(artifacts),
    }
    _assert_validation_invariants(
        manifest=manifest,
        payload=payload,
        report=report,
        build=build,
        cohort=cohort,
        scientometrics_module=scientometrics,
    )
    manifest_path = data_dir / "validation" / "scientometric_validation_manifest.json"
    _write_json(manifest_path, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


def _write_fixture(data_dir: Path) -> Path:
    raw = data_dir / "validation" / "raw" / "fixture_works.jsonl"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in _fixture_works()) + "\n", encoding="utf-8", newline="\n")
    return raw


def _fixture_works() -> list[dict[str, Any]]:
    return [
        _work(1, "Highly cited validation work", 120, ["A1", "A2"], 2020),
        _work(2, "Fractional collaboration work", 45, ["A1", "A3", "A4"], 2021),
        _work(3, "Solo influence work", 30, ["A1"], 2022),
        _work(4, "A1 steady output", 12, ["A1"], 2023),
        _work(5, "A1 recent output", 3, ["A1", "A5"], 2024),
        _work(6, "A2 follow-up", 40, ["A2"], 2020),
        _work(7, "A2 collaboration", 6, ["A2", "A3"], 2021),
        _work(8, "A3 methods paper", 22, ["A3"], 2022),
        _work(9, "A3 small paper", 2, ["A3"], 2023),
        _work(10, "A4 zero cited", 0, ["A4"], 2024),
        _work(11, "A5 zero cited", 0, ["A5"], 2024),
        _work(12, "A6 single cited", 1, ["A6"], 2024),
    ]


def _work(number: int, title: str, citations: int, author_ids: list[str], year: int) -> dict[str, Any]:
    positions = ["first"] + ["middle"] * max(0, len(author_ids) - 2) + (["last"] if len(author_ids) > 1 else [])
    primary_topic = _topic()
    return {
        "id": f"https://openalex.org/WV{number:03d}",
        "doi": f"https://doi.org/10.5555/validation.{number}",
        "display_name": title,
        "publication_year": year,
        "publication_date": f"{year}-01-{min(number, 28):02d}",
        "type": "article",
        "language": "en",
        "cited_by_count": citations,
        "is_retracted": False,
        "is_paratext": False,
        "is_xpac": False,
        "is_authors_truncated": False,
        "open_access": {"is_oa": True},
        "has_abstract": True,
        "primary_topic": primary_topic,
        "topics": [primary_topic],
        "primary_location": {"source": {"id": "https://openalex.org/S1", "display_name": "Validation Journal", "type": "journal"}},
        "ids": {"doi": f"https://doi.org/10.5555/validation.{number}"},
        "created_date": "2024-01-01",
        "updated_date": "2026-05-06",
        "authorships": [_authorship(author_id, positions[index]) for index, author_id in enumerate(author_ids)],
    }


def _authorship(author_id: str, position: str) -> dict[str, Any]:
    names = {
        "A1": "Author One",
        "A2": "Author Two",
        "A3": "Author Three",
        "A4": "Author Four",
        "A5": "Author Five",
        "A6": "Author Six",
    }
    return {
        "author_position": position,
        "author": {"id": f"https://openalex.org/{author_id}", "display_name": names[author_id], "orcid": None},
        "institutions": [{"id": "https://openalex.org/I1", "display_name": "Validation University", "country_code": "RU"}],
        "countries": ["RU"],
        "is_corresponding": position in {"first", "last"},
        "raw_author_name": names[author_id],
    }


def _topic() -> dict[str, Any]:
    return {
        "id": "https://openalex.org/T100",
        "display_name": "Validation Topic",
        "score": 0.95,
        "subfield": {"id": "https://openalex.org/subfields/1706", "display_name": "Computer Science Applications"},
        "field": {"id": "https://openalex.org/fields/17", "display_name": "Computer Science"},
        "domain": {"id": "https://openalex.org/domains/3", "display_name": "Physical Sciences"},
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _descriptive_fields() -> list[str]:
    return [
        "metric",
        "n",
        "missing_count",
        "zero_count",
        "zero_rate",
        "min",
        "q1",
        "median",
        "q3",
        "max",
        "mean",
        "stddev",
        "coefficient_of_variation",
        "iqr",
        "p90",
        "p95",
        "p99",
        "skewness",
        "excess_kurtosis",
        "tie_rate",
        "unique_count",
        "outlier_count_iqr",
        "outlier_share_iqr",
    ]


def _descriptive_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"metric": metric, **(summary or {})} for metric, summary in (payload.get("descriptive") or {}).items()]


def _correlation_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for method, matrix_payload in (payload.get("correlations") or {}).items():
        matrix = (matrix_payload or {}).get("matrix") if method == "kendall_tau_b" else matrix_payload
        if not isinstance(matrix, dict):
            continue
        for left_metric, right_values in matrix.items():
            if not isinstance(right_values, dict):
                continue
            for right_metric, value in right_values.items():
                rows.append({"method": method, "left_metric": left_metric, "right_metric": right_metric, "value": value})
    return rows


def _top_outlier_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    boxplots = payload.get("boxplots") or {}
    for metric, metric_outliers in (payload.get("outliers") or {}).items():
        boxplot = boxplots.get(metric) or {}
        for row in metric_outliers or []:
            rows.append(
                {
                    "metric": metric,
                    "author_id": row.get("author_id"),
                    "author_display_name": row.get("author_display_name"),
                    "value": row.get("value"),
                    "rule": boxplot.get("outlier_rule") or "iqr_1_5",
                    "lower_fence": boxplot.get("lower_fence"),
                    "upper_fence": boxplot.get("upper_fence"),
                }
            )
    return rows


def _finding_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for finding in payload.get("findings") or []:
        rows.append(
            {
                "id": finding.get("id"),
                "type": finding.get("type"),
                "metric": finding.get("metric"),
                "baseline_metric": finding.get("baseline_metric"),
                "severity": finding.get("severity"),
                "text": finding.get("text"),
                "recommendation": finding.get("recommendation"),
                "evidence_json": json.dumps(finding.get("evidence") or {}, ensure_ascii=False, sort_keys=True),
            }
        )
    return rows


def _artifact_checksums(artifacts: dict[str, str]) -> dict[str, str]:
    return {name: _sha256(Path(path)) for name, path in artifacts.items()}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_validation_invariants(
    *,
    manifest: dict[str, Any],
    payload: dict[str, Any],
    report: dict[str, Any],
    build: dict[str, Any],
    cohort: dict[str, Any],
    scientometrics_module: Any,
) -> None:
    scope = payload.get("scope") or {}
    report_scope = report.get("report_scope") or {}
    report_analysis_scope = ((report.get("scientometric_analysis") or {}).get("scope") or {})
    expected_scope = {
        "run_id": RUN_ID,
        "dump_id": DUMP_ID,
        "cohort_id": cohort["cohort_id"],
        "fraction_mode": FRACTION_MODE,
        "baseline_metric": BASELINE_METRIC,
        "rank_top_n": RANK_TOP_N,
    }
    for key, expected in expected_scope.items():
        _require(scope.get(key) == expected, f"scientometrics scope mismatch for {key}: {scope.get(key)!r} != {expected!r}")
        _require(report_scope.get(key) == expected, f"report scope mismatch for {key}: {report_scope.get(key)!r} != {expected!r}")
        _require(report_analysis_scope.get(key) == expected, f"report scientometric scope mismatch for {key}: {report_analysis_scope.get(key)!r} != {expected!r}")
    _require(manifest["status"] == "ok", "manifest status is not ok")
    _require(manifest["cohort_checksum"] == cohort["checksum"], "manifest cohort checksum does not match cohort checksum")
    _require(manifest["n_authors"] == payload["n_authors"] == RANK_TOP_N, "validated author count does not match the fixed author group")
    _require(manifest["raw_works"] == len(_fixture_works()), "validated raw work count does not match fixture")
    _require(manifest["analysis_schema"] == scientometrics_module.SCIENTOMETRIC_ANALYSIS_SCHEMA, "analysis schema mismatch")
    _require(manifest["findings_schema"] == scientometrics_module.SCIENTOMETRIC_FINDINGS_SCHEMA, "findings schema mismatch")
    _require(manifest["conclusion_schema"] == scientometrics_module.SCIENTOMETRIC_CONCLUSION_SCHEMA, "conclusion schema mismatch")
    _require(payload["conclusion_draft"]["schema"] == scientometrics_module.SCIENTOMETRIC_CONCLUSION_SCHEMA, "payload conclusion schema mismatch")
    _require(scope.get("data_scope") == "full_filtered_slice", "analysis must use full filtered slice scope")
    _require("iupv_s" in payload.get("metrics", []), "validation analysis must include iupv_s")
    _require("c_frac" in payload.get("metrics", []), "validation analysis must include c_frac")
    _require(any(finding.get("metric") == "iupv_s" for finding in payload.get("findings") or []), "missing IUPV-S candidate finding")
    _assert_iupv_s_tables(Path(manifest["data_dir"]))
    _require(build["analysis_eligibility"]["allowed_for_final_analysis"] is False, "validation fixture must not be eligible for final analysis")
    _require(bool(report["exports"]["scientometrics_conclusion_md"]), "report bundle is missing conclusion Markdown export")
    for key in (
        "scientometrics_json",
        "scientometrics_descriptive_csv",
        "scientometrics_correlations_csv",
        "scientometrics_outliers_csv",
        "scientometrics_top_outliers_csv",
        "scientometrics_findings_csv",
        "scientometrics_conclusion_md",
    ):
        _require(bool(report["exports"].get(key)), f"missing report export link: {key}")
    for name, path in manifest["artifacts"].items():
        _require(Path(path).is_file(), f"missing validation artifact: {name}={path}")
        _require(bool(manifest["artifact_checksums"].get(name)), f"missing validation checksum for artifact: {name}")


def _assert_iupv_s_tables(data_dir: Path) -> None:
    indices_path = data_dir / "runs" / RUN_ID / "tables" / "indices.csv"
    ratings_path = data_dir / "runs" / RUN_ID / "tables" / "ratings.csv"
    _require(indices_path.is_file(), f"missing indices table: {indices_path}")
    _require(ratings_path.is_file(), f"missing ratings table: {ratings_path}")
    with indices_path.open("r", encoding="utf-8", newline="") as handle:
        index_rows = list(csv.DictReader(handle))
    _require(bool(index_rows), "indices table is empty")
    index_fields = set(index_rows[0].keys())
    for field in REQUIRED_INDEX_FIELDS:
        _require(field in index_fields, f"indices table is missing {field}")
    positive_iupv = False
    for row in index_rows:
        rfi = _float(row.get("rfi_log_frac"))
        iupv_s = _float(row.get("iupv_s"))
        if rfi <= 0.0:
            _require(iupv_s == 0.0, "authors with rfi_log_frac=0 must have iupv_s=0")
        if iupv_s > 0.0:
            positive_iupv = True
    _require(positive_iupv, "at least one validation author must have positive iupv_s")
    with ratings_path.open("r", encoding="utf-8", newline="") as handle:
        rating_metrics = {str(row.get("metric_name") or "") for row in csv.DictReader(handle)}
    _require("iupv_s" in rating_metrics, "ratings table is missing metric_name=iupv_s")


def _float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    main()
