from __future__ import annotations

import sys
from pathlib import Path
import os


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
API = ROOT / "apps/api"
for path in (SRC, API):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


DATA = Path(os.environ.get("OPENALEX_DSS_DATA_DIR", ROOT.parent / "openalex-dss-data")).expanduser().resolve()


def data_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "data":
        return DATA.joinpath(*path.parts[1:])
    return ROOT / path
