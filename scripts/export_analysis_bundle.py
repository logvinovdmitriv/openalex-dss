from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METRICS = "p,c,c_frac,h,i10,g,iupv_s"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a scoped scientometric analysis bundle for a computed run.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dump-id", required=True)
    parser.add_argument("--fraction-mode", default="strict_authors_count")
    parser.add_argument("--metrics", default=DEFAULT_METRICS)
    parser.add_argument("--baseline", default="h")
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument("--out", required=True, help="Output directory for JSON/CSV/Markdown exports.")
    parser.add_argument("--data-dir", default="", help="Optional OPENALEX_DSS_DATA_DIR override.")
    args = parser.parse_args()

    if args.data_dir:
        os.environ["OPENALEX_DSS_DATA_DIR"] = str(Path(args.data_dir).expanduser().resolve())
    for path in (ROOT / "apps/api", ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    from app.services import reports, scientometrics

    metrics = [item.strip() for item in args.metrics.replace("|", ",").split(",") if item.strip()]
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    analysis_kwargs = {
        "fraction_mode": args.fraction_mode,
        "metrics": metrics,
        "baseline_metric": args.baseline,
        "filters": {},
        "run_id": args.run_id,
        "dump_id": args.dump_id,
        "top_n": args.top_n,
    }
    payload = scientometrics.build_scientometric_analysis(**analysis_kwargs)
    report = reports.build_report_bundle(
        metric=args.baseline,
        fraction_mode=args.fraction_mode,
        limit=args.top_n,
        run_id=args.run_id,
        dump_id=args.dump_id,
        filters={},
        scientometric_metrics=metrics,
        baseline_metric=args.baseline,
        rank_top_n=args.top_n,
    )

    artifacts = {
        "analysis_json": out_dir / "analysis.json",
        "report_bundle_json": out_dir / "report_bundle.json",
        "descriptive_csv": out_dir / "descriptive.csv",
        "correlations_csv": out_dir / "correlations.csv",
        "rank_comparisons_csv": out_dir / "rank_comparisons.csv",
        "pairwise_metric_comparison_csv": out_dir / "pairwise_metric_comparison.csv",
        "findings_csv": out_dir / "findings.csv",
        "conclusion_md": out_dir / "conclusion.md",
    }
    _write_json(artifacts["analysis_json"], payload)
    _write_json(artifacts["report_bundle_json"], report)
    _write_csv(artifacts["descriptive_csv"], _descriptive_rows(payload), _descriptive_fields())
    _write_csv(artifacts["correlations_csv"], _correlation_rows(payload), ["method", "left_metric", "right_metric", "value"])
    _write_csv(artifacts["rank_comparisons_csv"], _rank_rows(payload), ["metric", "median_abs_delta", "p90_abs_delta", "max_abs_delta", "jaccard_top_n_exact"])
    _write_csv(artifacts["pairwise_metric_comparison_csv"], payload.get("pairwise_metric_comparison") or [], _pairwise_fields())
    _write_csv(artifacts["findings_csv"], _finding_rows(payload), ["id", "type", "metric", "baseline_metric", "severity", "text", "recommendation", "evidence_json"])
    artifacts["conclusion_md"].write_text(scientometrics.scientometric_conclusion_markdown(payload), encoding="utf-8", newline="\n")

    manifest = {
        "schema": "analysis_bundle_manifest",
        "run_id": args.run_id,
        "dump_id": args.dump_id,
        "fraction_mode": args.fraction_mode,
        "baseline_metric": args.baseline,
        "metrics": metrics,
        "data_scope": (payload.get("scope") or {}).get("data_scope"),
        "analysis_author_scope": (payload.get("scope") or {}).get("analysis_author_scope"),
        "analysis_id": (payload.get("scope") or {}).get("analysis_id"),
        "filters_hash": (payload.get("scope") or {}).get("filters_hash"),
        "artifacts": {name: str(path) for name, path in artifacts.items()},
        "checksums": {name: _sha256(path) for name, path in artifacts.items()},
    }
    manifest_path = out_dir / "bundle_manifest.json"
    _write_json(manifest_path, manifest)
    print(json.dumps({"status": "ok", "manifest": str(manifest_path), **manifest}, ensure_ascii=False, indent=2, sort_keys=True))


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


def _rank_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"metric": metric, **(summary or {})}
        for metric, summary in ((payload.get("rank_comparisons") or {}).get("comparisons") or {}).items()
    ]


def _pairwise_fields() -> list[str]:
    return [
        "metric_a",
        "metric_b",
        "spearman",
        "kendall_tau_b",
        "pearson_log1p",
        "top10_overlap",
        "top20_overlap",
        "top50_overlap",
        "median_abs_rank_delta",
        "p90_abs_rank_delta",
        "max_abs_rank_delta",
        "share_abs_delta_le_5",
        "share_abs_delta_le_10",
    ]


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
