from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps/api"
SRC = ROOT / "src"
for path in (API, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.main import app  # noqa: E402
from app.api.routes import runs as runs_routes  # noqa: E402
from app.api.schemas import AnalysisRunRequest, RunRequest  # noqa: E402


class PublicApiSurfaceTests(unittest.TestCase):
    def test_legacy_pipeline_routes_are_not_public(self) -> None:
        route_paths = {getattr(route, "path", "") for route in app.routes}

        self.assertFalse(any(path.startswith("/api/v1/pipeline") for path in route_paths))

    def test_legacy_slice_plan_route_is_not_public(self) -> None:
        route_paths = {getattr(route, "path", "") for route in app.routes}

        self.assertNotIn("/api/v1/slices/plan", route_paths)

    def test_legacy_state_and_snapshot_diagnostics_are_not_public(self) -> None:
        route_paths = {getattr(route, "path", "") for route in app.routes}

        self.assertNotIn("/api/v1/state", route_paths)
        self.assertNotIn("/api/v1/snapshot/manifest", route_paths)
        self.assertIn("/api/v1/workbench", route_paths)
        self.assertIn("/api/v1/catalog", route_paths)

    def test_run_request_exposes_only_recalculate_action(self) -> None:
        self.assertEqual(RunRequest(payload={"dump_id": "dump_a"}).action, "recalculate")
        self.assertEqual(RunRequest(action="recalculate", payload={"dump_id": "dump_a"}).action, "recalculate")
        self.assertEqual(RunRequest(payload={"dump_id": "dump_a"}).payload.dump_id, "dump_a")
        self.assertEqual(RunRequest.model_json_schema()["properties"]["action"]["const"], "recalculate")
        self.assertIn("payload", RunRequest.model_json_schema()["required"])
        self.assertIn("dump_id", AnalysisRunRequest.model_json_schema()["required"])

        for action in ("plan", "fetch_slice_dump", "build_from_openalex", "import_file"):
            with self.assertRaises(ValidationError):
                RunRequest(action=action, payload={"dump_id": "dump_a"})

    def test_public_recalculate_requires_dump_id(self) -> None:
        for payload in ({}, {"dump_id": ""}, {"dump_id": "   "}):
            with self.assertRaises(ValidationError):
                RunRequest(action="recalculate", payload=payload)

    def test_public_runs_route_defensively_rejects_legacy_actions(self) -> None:
        for action in ("plan", "fetch_slice_dump", "build_from_openalex", "import_file"):
            request = SimpleNamespace(action=action, payload=AnalysisRunRequest(dump_id="dump_a"))

            with self.assertRaises(runs_routes.HTTPException) as raised:
                runs_routes.create_run(request)

            self.assertEqual(raised.exception.status_code, 400)
            self.assertIn("Unsupported public run action", str(raised.exception.detail))

    def test_public_runs_route_defensively_requires_dump_id(self) -> None:
        request = SimpleNamespace(action="recalculate", payload=SimpleNamespace(model_dump=lambda **_: {}))

        with self.assertRaises(runs_routes.HTTPException) as raised:
            runs_routes.create_run(request)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "dump_id is required for public recalculate runs")

    def test_public_runs_route_accepts_recalculate(self) -> None:
        request = RunRequest(action="recalculate", payload=AnalysisRunRequest(dump_id="dump_a"))

        with patch.object(
            runs_routes.jobs,
            "create_run",
            return_value={"run_id": "run_a", "status": "queued"},
        ) as create_run:
            payload = runs_routes.create_run(request)

        self.assertEqual(payload, {"run_id": "run_a", "status": "queued"})
        create_run.assert_called_once_with("recalculate", {"dump_id": "dump_a"})


if __name__ == "__main__":
    unittest.main()
