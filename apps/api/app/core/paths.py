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

TABLE_FILES = {
    "works": DATA / "normalized" / "works_flat.csv",
    "authorships": DATA / "normalized" / "authorships_flat.csv",
    "work_topics": DATA / "normalized" / "work_topics_flat.csv",
    "author_work": DATA / "marts" / "author_work_metrics.csv",
    "authors_local_metrics": DATA / "results" / "author_indices.csv",
    "indices": DATA / "results" / "author_indices.csv",
    "ratings": DATA / "results" / "rating_positions.csv",
}

PARQUET_TABLE_FILES = {
    "works": DATA / "parquet" / "works_flat.parquet",
    "authorships": DATA / "parquet" / "authorships_flat.parquet",
    "work_topics": DATA / "parquet" / "work_topics_flat.parquet",
    "author_work": DATA / "marts" / "author_work_metrics.parquet",
    "authors_local_metrics": DATA / "results" / "author_indices.parquet",
    "indices": DATA / "results" / "author_indices.parquet",
    "ratings": DATA / "results" / "rating_positions.parquet",
}

JSON_FILES = {
    "fetch_meta": DATA / "passports" / "fetch_meta.json",
    "quality": DATA / "passports" / "quality_report.json",
    "checksums": DATA / "passports" / "checksums.json",
    "pipeline": DATA / "passports" / "pipeline_summary.json",
    "report_bundle": DATA / "results" / "report_bundle.json",
}
