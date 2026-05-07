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

TABLE_KINDS = (
    "works",
    "authorships",
    "work_topics",
    "author_work",
    "indices",
    "ratings",
)
