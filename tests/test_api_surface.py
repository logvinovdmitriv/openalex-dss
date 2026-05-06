from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps/api"
SRC = ROOT / "src"
for path in (API, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.main import app  # noqa: E402


class PublicApiSurfaceTests(unittest.TestCase):
    def test_legacy_pipeline_routes_are_not_public(self) -> None:
        route_paths = {getattr(route, "path", "") for route in app.routes}

        self.assertFalse(any(path.startswith("/api/v1/pipeline") for path in route_paths))


if __name__ == "__main__":
    unittest.main()
