from __future__ import annotations

import sys
import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints
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
from app.api.routes import slices as slices_routes  # noqa: E402
from app.api import schemas as public_schemas  # noqa: E402
from app.api.schemas import AnalysisRunRequest, RunRequest, SliceCreateRequest  # noqa: E402
from app.services.internal_payloads import InternalPipelinePayload, normalize_internal_pipeline_payload  # noqa: E402


class PublicApiSurfaceTests(unittest.TestCase):
    def test_stale_pipeline_routes_are_not_public(self) -> None:
        route_paths = {getattr(route, "path", "") for route in app.routes}

        self.assertFalse(any(path.startswith("/api/v1/pipeline") for path in route_paths))

    def test_stale_slice_plan_route_is_not_public(self) -> None:
        route_paths = {getattr(route, "path", "") for route in app.routes}

        self.assertNotIn("/api/v1/slices/plan", route_paths)

    def test_stale_state_and_snapshot_diagnostics_are_not_public(self) -> None:
        route_paths = {getattr(route, "path", "") for route in app.routes}

        self.assertNotIn("/api/v1/state", route_paths)
        self.assertNotIn("/api/v1/snapshot/manifest", route_paths)
        self.assertIn("/api/v1/workbench", route_paths)
        self.assertIn("/api/v1/catalog", route_paths)

    def test_local_data_preview_routes_are_public(self) -> None:
        route_paths = {getattr(route, "path", "") for route in app.routes}

        self.assertIn("/api/v1/local-data/summary", route_paths)
        self.assertIn("/api/v1/local-data/preview", route_paths)
        self.assertIn("/api/v1/local-data/preview.csv", route_paths)

    def test_generic_table_browser_routes_are_not_public(self) -> None:
        route_paths = {getattr(route, "path", "") for route in app.routes}

        self.assertNotIn("/api/v1/tables/{table}", route_paths)
        self.assertNotIn("/api/v1/exports/{table}.csv", route_paths)
        self.assertNotIn("/api/v1/exports/{table}.json", route_paths)
        self.assertNotIn("/api/v1/runs/{run_id}/tables/{table_name}", route_paths)

    def test_slice_create_schema_does_not_expose_internal_pipeline_fields(self) -> None:
        props = SliceCreateRequest.model_json_schema()["properties"]

        for field in (
            "slice_name",
            "workflow_mode",
            "raw_openalex_filter",
            "api_key",
            "source_path",
            "source_strategy",
            "sort",
            "per_page",
            "accepted_estimate_signature",
            "accepted_download_signature",
            "fraction_modes",
            "fraction_mode_default",
            "lrdi_p0",
            "lrdi_lambda",
            "analysis_year",
        ):
            self.assertNotIn(field, props)

        self.assertIn("filter_mode", props)
        self.assertIn("country_code", props)

    def test_slice_create_request_rejects_internal_pipeline_fields(self) -> None:
        for field in ("slice_name", "workflow_mode", "sort", "per_page", "api_key", "raw_openalex_filter", "source_path", "accepted_download_signature", "lrdi_p0"):
            with self.assertRaises(ValidationError):
                SliceCreateRequest(filter_mode="all", **{field: "stale"})

    def test_public_slices_route_uses_slice_create_request_schema(self) -> None:
        annotation_name = inspect.signature(slices_routes.create_slice).parameters["payload"].annotation
        annotation = get_type_hints(slices_routes.create_slice)["payload"]

        self.assertEqual(annotation_name, "SliceCreateRequest")
        self.assertIs(annotation, SliceCreateRequest)

    def test_internal_pipeline_payload_is_not_a_public_schema(self) -> None:
        public_exports = set(vars(public_schemas))
        internal_props = InternalPipelinePayload.model_json_schema()["properties"]

        self.assertNotIn("PipelineRequest", public_exports)
        self.assertIn("slice_name", internal_props)
        self.assertIn("workflow_mode", internal_props)
        self.assertIn("sort", internal_props)
        self.assertIn("per_page", internal_props)
        self.assertIn("raw_openalex_filter", internal_props)
        self.assertIn("accepted_download_signature", internal_props)
        self.assertIn("download_policy", internal_props)
        self.assertIn("dump_manifest", internal_props)
        self.assertIn("analysis_eligibility", internal_props)
        self.assertIn("active_context_source", internal_props)
        self.assertIn("run_id", internal_props)
        self.assertIn("dump_id", internal_props)
        internal = InternalPipelinePayload(filter_mode="all", api_key="secret", workflow_mode="strict_works", extra_field="ignored")
        self.assertEqual(internal.api_key, "secret")
        self.assertEqual(internal.workflow_mode, "strict_works")

    def test_internal_pipeline_payload_normalizer_keeps_service_context_and_drops_unknown_extras(self) -> None:
        normalized = normalize_internal_pipeline_payload(
            {
                "filter_mode": "all",
                "api_key": "secret",
                "accepted_download_signature": "download-ok",
                "download_policy": {"complete_slice_required": True},
                "run_id": "run_a",
                "dump_id": "dump_a",
                "dump_manifest": {"dump_id": "dump_a"},
                "analysis_eligibility": {"status": "final", "allowed_for_final_analysis": True},
                "active_context_source": "materialization",
                "unknown_extra": "drop-me",
            }
        )

        self.assertEqual(normalized["api_key"], "secret")
        self.assertEqual(normalized["accepted_download_signature"], "download-ok")
        self.assertEqual(normalized["download_policy"], {"complete_slice_required": True})
        self.assertEqual(normalized["run_id"], "run_a")
        self.assertEqual(normalized["dump_id"], "dump_a")
        self.assertEqual(normalized["dump_manifest"], {"dump_id": "dump_a"})
        self.assertEqual(normalized["analysis_eligibility"]["status"], "final")
        self.assertEqual(normalized["active_context_source"], "materialization")
        self.assertNotIn("unknown_extra", normalized)

    def test_run_request_exposes_only_recalculate_action(self) -> None:
        self.assertEqual(RunRequest(payload={"dump_id": "dump_a"}).action, "recalculate")
        self.assertEqual(RunRequest(action="recalculate", payload={"dump_id": "dump_a"}).action, "recalculate")
        self.assertEqual(RunRequest(payload={"dump_id": "dump_a"}).payload.dump_id, "dump_a")
        self.assertEqual(RunRequest.model_json_schema()["properties"]["action"]["const"], "recalculate")
        self.assertIn("payload", RunRequest.model_json_schema()["required"])
        self.assertIn("dump_id", AnalysisRunRequest.model_json_schema()["required"])

        for action in ("plan", "fetch_slice_dump", "build_from_openalex", "download"):
            with self.assertRaises(ValidationError):
                RunRequest(action=action, payload={"dump_id": "dump_a"})

    def test_public_recalculate_requires_dump_id(self) -> None:
        for payload in ({}, {"dump_id": ""}, {"dump_id": "   "}):
            with self.assertRaises(ValidationError):
                RunRequest(action="recalculate", payload=payload)

    def test_public_runs_route_defensively_rejects_stale_actions(self) -> None:
        for action in ("plan", "fetch_slice_dump", "build_from_openalex", "download"):
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
