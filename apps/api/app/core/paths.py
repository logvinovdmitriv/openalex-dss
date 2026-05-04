from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src"


def _data_root() -> Path:
    configured = os.environ.get("OPENALEX_DSS_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (ROOT.parent / "openalex-dss-data").resolve()


DATA = _data_root()
WAREHOUSE = DATA / "warehouse" / "openalex_dss.duckdb"
BI_WAREHOUSE = DATA / "warehouse" / "openalex_dss_bi.duckdb"

TABLE_FILES = {
    "authors_preview": DATA / "normalized" / "author_profiles_flat.csv",
    "author_profiles": DATA / "normalized" / "author_profiles_flat.csv",
    "works": DATA / "normalized" / "works_flat.csv",
    "authorships": DATA / "normalized" / "authorships_flat.csv",
    "author_work": DATA / "marts" / "author_work_metrics.csv",
    "authors_local_metrics": DATA / "results" / "author_indices.csv",
    "indices": DATA / "results" / "author_indices.csv",
    "ratings": DATA / "results" / "rating_positions.csv",
    "top1_sensitivity": DATA / "results" / "theory_top1_sensitivity.csv",
    "fraction_sensitivity": DATA / "results" / "theory_fraction_mode_sensitivity.csv",
}

JSON_FILES = {
    "fetch_meta": DATA / "passports" / "fetch_meta.json",
    "quality": DATA / "passports" / "quality_report.json",
    "stats": DATA / "results" / "stats_summary.json",
    "theory": DATA / "results" / "theory_validation.json",
    "checksums": DATA / "passports" / "checksums.json",
    "pipeline": DATA / "passports" / "pipeline_summary.json",
    "author_preview_meta": DATA / "passports" / "author_preview_meta.json",
    "author_preview_quality": DATA / "passports" / "author_preview_quality.json",
    "report_bundle": DATA / "results" / "report_bundle.json",
}
