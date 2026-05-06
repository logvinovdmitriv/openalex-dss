from __future__ import annotations

import argparse
import csv
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
RUN_ID = "validation_scientometric_mvp"
DUMP_ID = "validation_fixture_dump"
FRACTION_MODE = "integer"
BASELINE_METRIC = "h"
RANK_TOP_N = 5
METRICS = ["p", "c", "c_frac", "h", "i10", "g", "islv"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a deterministic end-to-end validation of the scientometric MVP pipeline.")
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
            "slice_name": "validation_scientometric_mvp_fixture",
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
                "warning": "Deterministic local fixture validates the MVP pipeline and exports; it is not a real OpenAlex scientific slice.",
            },
        }
    )
    with patch.object(cohorts.uuid, "uuid4", return_value=SimpleNamespace(hex="validation000000000000000000000000")):
        cohort = cohorts.create_cohort(
            {
                "name": "Validation Top-5 by h",
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
        exports_dir / "rank-shifts.csv",
        scientometrics.build_rank_shift_export_rows(**analysis_kwargs),
        ["baseline_metric", "compare_metric", "author_id", "author_display_name", "baseline_rank", "metric_rank", "rank_delta", "abs_rank_delta"],
    )
    _write_csv(
        exports_dir / "outliers.csv",
        scientometrics.build_outlier_export_rows(**analysis_kwargs),
        ["metric", "author_id", "author_display_name", "value", "rule", "lower_fence", "upper_fence"],
    )
    _write_csv(exports_dir / "findings.csv", _finding_rows(payload), ["id", "type", "metric", "baseline_metric", "severity", "text", "recommendation", "evidence_json"])
    (exports_dir / "conclusion.md").write_text(scientometrics.scientometric_conclusion_markdown(payload), encoding="utf-8", newline="\n")
    _write_json(exports_dir / "report_bundle.json", report)

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
        "raw_works": 12,
        "n_authors": payload["n_authors"],
        "findings": len(payload.get("findings") or []),
        "report_scope_hash": report["report_scope"]["report_scope_hash"],
        "report_bundle_version": report["bundle_version"],
        "analysis_version": payload["analysis_version"],
        "findings_version": payload["finding_summary"]["findings_version"],
        "conclusion_version": payload["conclusion_draft"]["version"],
        "analysis_eligibility": build["analysis_eligibility"],
        "artifacts": {
            "raw_fixture": str(raw_path),
            "scientometrics_json": str(exports_dir / "scientometrics.json"),
            "descriptive_csv": str(exports_dir / "descriptive.csv"),
            "correlations_csv": str(exports_dir / "correlations.csv"),
            "rank_shifts_csv": str(exports_dir / "rank-shifts.csv"),
            "outliers_csv": str(exports_dir / "outliers.csv"),
            "findings_csv": str(exports_dir / "findings.csv"),
            "conclusion_md": str(exports_dir / "conclusion.md"),
            "report_bundle_json": str(exports_dir / "report_bundle.json"),
            "run_report_bundle": str(data_dir / "runs" / RUN_ID / "reports" / f"report_{report['report_scope']['report_scope_hash']}.json"),
        },
    }
    manifest_path = data_dir / "validation" / "mvp_validation_manifest.json"
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


if __name__ == "__main__":
    main()
