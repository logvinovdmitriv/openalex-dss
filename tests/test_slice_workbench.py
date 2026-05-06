from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps/api"
SRC = ROOT / "src"
for path in (API, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services import slice_workbench  # noqa: E402


class SliceWorkbenchTests(unittest.TestCase):
    def test_slice_estimate_and_materialization_plan_keep_download_policy_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = {
                "slice_id": "slice_test",
                "entity_level": "subfield",
                "entity_id_short": "1706",
                "entity_id_full": "https://openalex.org/subfields/1706",
                "entity_display_name": "Computer Science Applications",
                "country_code": "RU",
                "from_publication_date": "2020-01-01",
                "to_publication_date": "2025-12-31",
                "work_type": "article|review",
                "download_policy": {
                    "complete_slice_required": True,
                    "allow_incomplete_preview": False,
                },
            }
            fake_plan = {
                "decision": {"status": "can_fetch", "can_execute": True, "reasons": [], "warnings": []},
                "estimate": {
                    "estimate_count": 1000,
                    "planned_records": 1000,
                    "api_requests_planned": 10,
                    "estimated_raw_mb": 12.5,
                    "estimated_raw_bytes": 12_500_000,
                },
                "openalex_filter": "primary_topic.subfield.id:1706,authorships.institutions.country_code:RU",
                "filter_classes": {"pushdown_openalex": ["subject", "country"]},
                "download_policy": {**payload["download_policy"], "user_controls_download_after_estimate": True},
                "limits": {"max_api_requests_per_job": 2000},
            }

            with (
                patch.object(slice_workbench, "SLICES_DIR", tmp_path / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
                patch.object(slice_workbench.query_planner, "plan_slice", return_value=fake_plan),
            ):
                created = slice_workbench.create_slice(payload)
                self.assertNotIn("limits", created["slice_definition"])
                self.assertEqual(created["download_policy_default"]["complete_slice_required"], True)

                estimate = slice_workbench.estimate_slice(created["slice_id"], {"download_policy": payload["download_policy"]})
                self.assertEqual(estimate["download_policy"]["user_controls_download_after_estimate"], True)

                materialization = slice_workbench.create_materialization_plan(
                    created["slice_id"],
                    {"storage_profile_id": "minimal_analytics", "download_policy": payload["download_policy"]},
                )
                self.assertEqual(materialization["source_strategy"], "openalex_cli")
                self.assertEqual(materialization["download_policy"]["complete_slice_required"], True)
                self.assertEqual(materialization["download_policy"]["user_controls_download_after_estimate"], True)
                self.assertEqual(materialization["state"], "planned")

    def test_materialization_completion_advances_slice_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = {
                "slice_id": "slice_done",
                "entity_level": "subfield",
                "entity_id_short": "1706",
                "entity_display_name": "Computer Science Applications",
                "from_publication_date": "2020-01-01",
                "to_publication_date": "2025-12-31",
            }
            fake_plan = {
                "decision": {"status": "can_fetch", "can_execute": True, "reasons": [], "warnings": []},
                "estimate": {
                    "estimate_count": 10,
                    "estimate_signature": "estimate-ok",
                    "download_signature": "download-ok",
                },
                "openalex_filter": "primary_topic.subfield.id:1706",
                "filter_classes": {},
                "download_policy": {"user_controls_download_after_estimate": True},
                "limits": {},
            }
            with (
                patch.object(slice_workbench, "SLICES_DIR", tmp_path / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
                patch.object(slice_workbench.query_planner, "plan_slice", return_value=fake_plan),
            ):
                created = slice_workbench.create_slice(payload)
                materialization = slice_workbench.create_materialization_plan(created["slice_id"])
                materialization["run_id"] = "run_done"
                materialization["state"] = "materializing"
                slice_workbench._write_materialization(materialization)

                slice_workbench.mark_materialization_run_completed(
                    "run_done",
                    {
                        "fetch": {"dump": {"dump_id": "dump_done", "raw_jsonl": "/tmp/works.jsonl.gz"}},
                        "build": {"status": "ok"},
                        "no_data": False,
                    },
                )

                updated_slice = slice_workbench.get_slice(created["slice_id"])
                updated_plan = slice_workbench.get_materialization_plan(materialization["materialization_id"])
                self.assertEqual(updated_slice["state"], "analyzed")
                self.assertEqual(updated_plan["state"], "ready")
                self.assertEqual(updated_plan["dump_id"], "dump_done")

    def test_materialization_no_data_marks_slice_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = {
                "slice_id": "slice_empty",
                "entity_level": "subfield",
                "entity_id_short": "1706",
                "entity_display_name": "Computer Science Applications",
            }
            fake_plan = {
                "decision": {"status": "no_data", "can_execute": False, "reasons": [], "warnings": []},
                "estimate": {"estimate_count": 0, "estimate_signature": "estimate-empty", "download_signature": "download-empty"},
                "openalex_filter": "primary_topic.subfield.id:1706",
                "filter_classes": {},
                "download_policy": {"user_controls_download_after_estimate": True},
                "limits": {},
            }
            with (
                patch.object(slice_workbench, "SLICES_DIR", tmp_path / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
                patch.object(slice_workbench.query_planner, "plan_slice", return_value=fake_plan),
            ):
                created = slice_workbench.create_slice(payload)
                materialization = slice_workbench.create_materialization_plan(created["slice_id"])
                materialization["run_id"] = "run_empty"
                slice_workbench._write_materialization(materialization)

                slice_workbench.mark_materialization_run_completed("run_empty", {"fetch": {"dump": {"no_data": True}}, "build": None, "no_data": True})

                self.assertEqual(slice_workbench.get_slice(created["slice_id"])["state"], "empty")
                self.assertEqual(slice_workbench.get_materialization_plan(materialization["materialization_id"])["state"], "empty")

    def test_materialization_failure_marks_slice_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = {
                "slice_id": "slice_failed",
                "entity_level": "subfield",
                "entity_id_short": "1706",
                "entity_display_name": "Computer Science Applications",
            }
            fake_plan = {
                "decision": {"status": "can_fetch", "can_execute": True, "reasons": [], "warnings": []},
                "estimate": {"estimate_count": 10, "estimate_signature": "estimate", "download_signature": "download"},
                "openalex_filter": "primary_topic.subfield.id:1706",
                "filter_classes": {},
                "download_policy": {"user_controls_download_after_estimate": True},
                "limits": {},
            }
            with (
                patch.object(slice_workbench, "SLICES_DIR", tmp_path / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
                patch.object(slice_workbench.query_planner, "plan_slice", return_value=fake_plan),
            ):
                created = slice_workbench.create_slice(payload)
                materialization = slice_workbench.create_materialization_plan(created["slice_id"])
                materialization["run_id"] = "run_failed"
                materialization["state"] = "materializing"
                slice_workbench._write_materialization(materialization)

                slice_workbench.mark_materialization_run_failed("run_failed", "boom")

                updated_slice = slice_workbench.get_slice(created["slice_id"])
                updated_plan = slice_workbench.get_materialization_plan(materialization["materialization_id"])
                self.assertEqual(updated_slice["state"], "failed")
                self.assertEqual(updated_plan["state"], "failed")
                self.assertEqual(updated_plan["error"], "boom")

    def test_failed_slice_can_be_retried_to_materializing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = {
                "slice_id": "slice_retry_failed",
                "entity_level": "subfield",
                "entity_id_short": "1706",
                "entity_display_name": "Computer Science Applications",
            }
            fake_plan = {
                "decision": {"status": "can_fetch", "can_execute": True, "reasons": [], "warnings": []},
                "estimate": {"estimate_count": 10, "estimate_signature": "estimate", "download_signature": "download"},
                "openalex_filter": "primary_topic.subfield.id:1706",
                "filter_classes": {},
                "download_policy": {"user_controls_download_after_estimate": True},
                "limits": {},
            }
            with (
                patch.object(slice_workbench, "SLICES_DIR", tmp_path / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
                patch.object(slice_workbench.query_planner, "plan_slice", return_value=fake_plan),
                patch.object(slice_workbench.jobs, "create_run", return_value={"run_id": "run_retry", "status": "queued"}) as create_run,
                patch.object(slice_workbench.jobs, "start_run", return_value={"run_id": "run_retry", "status": "queued"}),
                patch.object(slice_workbench.jobs, "get_run", return_value={"run_id": "run_retry", "status": "queued"}),
            ):
                created = slice_workbench.create_slice(payload)
                materialization = slice_workbench.create_materialization_plan(created["slice_id"])
                materialization["run_id"] = "run_failed"
                slice_workbench._write_materialization(materialization)
                slice_workbench.mark_materialization_run_failed("run_failed", "boom")

                retried = slice_workbench.run_materialization(materialization["materialization_id"])

                self.assertEqual(retried["materialization"]["state"], "materializing")
                self.assertEqual(slice_workbench.get_slice(created["slice_id"])["state"], "materializing")
                self.assertEqual(create_run.call_args.args[1]["materialization_id"], materialization["materialization_id"])
                self.assertEqual(create_run.call_args.kwargs["autostart"], False)

    def test_empty_slice_can_be_reestimated_and_replanned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = {
                "slice_id": "slice_retry_empty",
                "entity_level": "subfield",
                "entity_id_short": "1706",
                "entity_display_name": "Computer Science Applications",
            }
            fake_plan = {
                "decision": {"status": "can_fetch", "can_execute": True, "reasons": [], "warnings": []},
                "estimate": {"estimate_count": 10, "estimate_signature": "estimate", "download_signature": "download"},
                "openalex_filter": "primary_topic.subfield.id:1706",
                "filter_classes": {},
                "download_policy": {"user_controls_download_after_estimate": True},
                "limits": {},
            }
            with (
                patch.object(slice_workbench, "SLICES_DIR", tmp_path / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
                patch.object(slice_workbench.query_planner, "plan_slice", return_value=fake_plan),
            ):
                created = slice_workbench.create_slice(payload)
                materialization = slice_workbench.create_materialization_plan(created["slice_id"])
                materialization["run_id"] = "run_empty"
                slice_workbench._write_materialization(materialization)
                slice_workbench.mark_materialization_run_completed("run_empty", {"fetch": {"dump": {"no_data": True}}, "build": None, "no_data": True})

                replanned = slice_workbench.create_materialization_plan(created["slice_id"])

                self.assertEqual(replanned["state"], "planned")
                self.assertEqual(slice_workbench.get_slice(created["slice_id"])["state"], "planned")

    def test_success_after_failure_advances_to_analyzed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = {
                "slice_id": "slice_success_after_failure",
                "entity_level": "subfield",
                "entity_id_short": "1706",
                "entity_display_name": "Computer Science Applications",
            }
            fake_plan = {
                "decision": {"status": "can_fetch", "can_execute": True, "reasons": [], "warnings": []},
                "estimate": {"estimate_count": 10, "estimate_signature": "estimate", "download_signature": "download"},
                "openalex_filter": "primary_topic.subfield.id:1706",
                "filter_classes": {},
                "download_policy": {"user_controls_download_after_estimate": True},
                "limits": {},
            }
            with (
                patch.object(slice_workbench, "SLICES_DIR", tmp_path / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
                patch.object(slice_workbench.query_planner, "plan_slice", return_value=fake_plan),
            ):
                created = slice_workbench.create_slice(payload)
                materialization = slice_workbench.create_materialization_plan(created["slice_id"])
                materialization["run_id"] = "run_failed_then_ok"
                slice_workbench._write_materialization(materialization)
                slice_workbench.mark_materialization_run_failed("run_failed_then_ok", "boom")

                slice_workbench.mark_materialization_run_completed(
                    "run_failed_then_ok",
                    {"fetch": {"dump": {"dump_id": "dump_ok"}}, "build": {"status": "ok"}, "no_data": False},
                )

                self.assertEqual(slice_workbench.get_slice(created["slice_id"])["state"], "analyzed")
                self.assertEqual(slice_workbench.get_materialization_plan(materialization["materialization_id"])["state"], "ready")

    def test_materialization_failure_found_by_materialization_id_even_if_run_id_race(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = {
                "slice_id": "slice_race",
                "entity_level": "subfield",
                "entity_id_short": "1706",
                "entity_display_name": "Computer Science Applications",
            }
            fake_plan = {
                "decision": {"status": "can_fetch", "can_execute": True, "reasons": [], "warnings": []},
                "estimate": {"estimate_count": 10, "estimate_signature": "estimate", "download_signature": "download"},
                "openalex_filter": "primary_topic.subfield.id:1706",
                "filter_classes": {},
                "download_policy": {"user_controls_download_after_estimate": True},
                "limits": {},
            }
            with (
                patch.object(slice_workbench, "SLICES_DIR", tmp_path / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
                patch.object(slice_workbench.query_planner, "plan_slice", return_value=fake_plan),
            ):
                created = slice_workbench.create_slice(payload)
                materialization = slice_workbench.create_materialization_plan(created["slice_id"])

                slice_workbench.mark_materialization_run_failed("run_not_written_yet", "boom", materialization_id=materialization["materialization_id"])

                self.assertEqual(slice_workbench.get_slice(created["slice_id"])["state"], "failed")
                self.assertEqual(slice_workbench.get_materialization_plan(materialization["materialization_id"])["state"], "failed")

    def test_job_completion_before_run_materialization_return_does_not_regress_ready_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = {
                "slice_id": "slice_atomic",
                "entity_level": "subfield",
                "entity_id_short": "1706",
                "entity_display_name": "Computer Science Applications",
            }
            fake_plan = {
                "decision": {"status": "can_fetch", "can_execute": True, "reasons": [], "warnings": []},
                "estimate": {"estimate_count": 10, "estimate_signature": "estimate", "download_signature": "download"},
                "openalex_filter": "primary_topic.subfield.id:1706",
                "filter_classes": {},
                "download_policy": {"user_controls_download_after_estimate": True},
                "limits": {},
            }

            with (
                patch.object(slice_workbench, "SLICES_DIR", tmp_path / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
                patch.object(slice_workbench.query_planner, "plan_slice", return_value=fake_plan),
                patch.object(slice_workbench.jobs, "create_run", return_value={"run_id": "run_fast", "status": "queued"}),
                patch.object(slice_workbench.jobs, "get_run", return_value={"run_id": "run_fast", "status": "completed"}),
            ):
                created = slice_workbench.create_slice(payload)
                materialization = slice_workbench.create_materialization_plan(created["slice_id"])

                def complete_immediately(run_id: str) -> dict[str, str]:
                    slice_workbench.mark_materialization_run_completed(
                        run_id,
                        {"fetch": {"dump": {"dump_id": "dump_fast"}}, "build": {"status": "ok"}, "no_data": False},
                        materialization_id=materialization["materialization_id"],
                    )
                    return {"run_id": run_id, "status": "completed"}

                with patch.object(slice_workbench.jobs, "start_run", side_effect=complete_immediately):
                    result = slice_workbench.run_materialization(materialization["materialization_id"])

                self.assertEqual(result["materialization"]["state"], "ready")
                self.assertEqual(slice_workbench.get_slice(created["slice_id"])["state"], "analyzed")

    def test_materialization_plan_recomputes_stale_estimate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = {
                "slice_id": "slice_stale",
                "entity_level": "subfield",
                "entity_id_short": "1706",
                "entity_display_name": "Computer Science Applications",
            }
            old_plan = {
                "decision": {"status": "can_fetch", "can_execute": True, "reasons": [], "warnings": []},
                "estimate": {"estimate_count": 10, "estimate_signature": "old-estimate", "download_signature": "old-download"},
                "openalex_filter": "primary_topic.subfield.id:1706",
                "filter_classes": {},
                "download_policy": {"user_controls_download_after_estimate": True},
                "limits": {},
            }
            new_plan = {
                **old_plan,
                "estimate": {"estimate_count": 12, "estimate_signature": "new-estimate", "download_signature": "new-download"},
            }
            with (
                patch.object(slice_workbench, "SLICES_DIR", tmp_path / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
                patch.object(slice_workbench.query_planner, "plan_slice", side_effect=[old_plan, new_plan]),
            ):
                created = slice_workbench.create_slice(payload)
                slice_workbench.estimate_slice(created["slice_id"])
                materialization = slice_workbench.create_materialization_plan(created["slice_id"])

                self.assertEqual(materialization["accepted_estimate_signature"], "new-estimate")
                self.assertEqual(materialization["accepted_download_signature"], "new-download")


if __name__ == "__main__":
    unittest.main()
