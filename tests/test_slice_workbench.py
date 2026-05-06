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

from app.services import author_slice, slice_workbench  # noqa: E402


class SliceWorkbenchTests(unittest.TestCase):
    def test_workbench_summary_carries_quality_and_slice_centric_workflow(self) -> None:
        quality = {"quality_counts": {"works_without_authorships": 2, "authorships_null_author_id": 1}}
        active_context = {
            "active_run_id": "run_a",
            "active_dump_id": "dump_a",
            "source": "materialization",
            "updated_at_utc": "2026-05-07T00:00:00Z",
            "analysis_eligibility_status": "final",
            "allowed_for_final_analysis": True,
        }
        with (
            patch.object(
                slice_workbench.warehouse,
                "list_tables",
                return_value={"works": {"rows": 3}, "authorships": {"rows": 4}, "indices": {"rows": 2}},
            ),
            patch.object(slice_workbench.warehouse, "read_json_doc", return_value=quality),
            patch.object(slice_workbench.artifact_context, "read_active_context", return_value=active_context),
            patch.object(slice_workbench, "list_slices", return_value={"slices": [{"slice_id": "slice_a", "state": "ready"}], "total": 1}),
            patch.object(slice_workbench, "list_materialization_plans", return_value={"materializations": []}),
            patch.object(slice_workbench, "list_dumps", return_value={"dumps": [{"dump_id": "dump_a"}], "total": 1}),
        ):
            summary = slice_workbench.workbench_summary()

        self.assertEqual(summary["quality"], quality)
        self.assertEqual(summary["active_context"], active_context)
        self.assertEqual(summary["workflow"]["active_stage"], "analyzed")
        self.assertEqual(summary["workflow"]["active_run_id"], "run_a")
        self.assertEqual(summary["workflow"]["active_dump_id"], "dump_a")
        self.assertEqual(summary["workflow"]["active_context_source"], "materialization")
        self.assertEqual(summary["workflow"]["current_slice"]["slice_id"], "slice_a")
        self.assertEqual(summary["workflow"]["quality_summary"]["quality_flags"], 3)
        self.assertEqual(summary["workflow"]["quality_summary"]["analysis_eligibility_status"], "final")
        self.assertEqual(summary["workflow"]["quality_summary"]["allowed_for_final_analysis"], True)

    def test_workbench_summary_preserves_nullable_active_context_eligibility(self) -> None:
        for active_context, expected in (
            ({}, None),
            ({"allowed_for_final_analysis": False}, False),
            ({"allowed_for_final_analysis": True}, True),
        ):
            with self.subTest(active_context=active_context):
                with (
                    patch.object(slice_workbench.warehouse, "list_tables", return_value={}),
                    patch.object(slice_workbench.warehouse, "read_json_doc", return_value={}),
                    patch.object(slice_workbench.artifact_context, "read_active_context", return_value=active_context),
                    patch.object(slice_workbench, "list_slices", return_value={"slices": [], "total": 0}),
                    patch.object(slice_workbench, "list_materialization_plans", return_value={"materializations": []}),
                    patch.object(slice_workbench, "list_dumps", return_value={"dumps": [], "total": 0}),
                ):
                    summary = slice_workbench.workbench_summary()

            self.assertIs(summary["workflow"]["quality_summary"]["allowed_for_final_analysis"], expected)

    def test_workbench_summary_prioritizes_active_materialization(self) -> None:
        with (
            patch.object(
                slice_workbench.warehouse,
                "list_tables",
                return_value={"works": {"rows": 3}, "authorships": {"rows": 4}, "indices": {"rows": 2}},
            ),
            patch.object(slice_workbench.warehouse, "read_json_doc", return_value={}),
            patch.object(slice_workbench.artifact_context, "read_active_context", return_value={}),
            patch.object(slice_workbench, "list_slices", return_value={"slices": [{"slice_id": "slice_a", "state": "ready"}], "total": 1}),
            patch.object(
                slice_workbench,
                "list_materialization_plans",
                return_value={"materializations": [{"materialization_id": "mat_a", "state": "materializing"}]},
            ),
            patch.object(slice_workbench, "list_dumps", return_value={"dumps": [{"dump_id": "dump_a"}], "total": 1}),
        ):
            summary = slice_workbench.workbench_summary()

        self.assertEqual(summary["workflow"]["active_stage"], "materializing")

    def test_keyword_and_search_modes_do_not_require_subject(self) -> None:
        keyword_cfg = author_slice.config_from_payload(
            {
                "filter_mode": "keyword",
                "keyword_id": "https://openalex.org/K123",
                "keyword_display_name": "decision support",
            }
        )
        search_cfg = author_slice.config_from_payload(
            {
                "filter_mode": "search",
                "text_search_query": "ergodesign",
            }
        )

        self.assertEqual(keyword_cfg.entity_level, "")
        self.assertEqual(keyword_cfg.entity_id_short, "")
        self.assertEqual(search_cfg.entity_level, "")
        self.assertEqual(search_cfg.entity_id_short, "")

    def test_slice_id_hash_distinguishes_same_human_name_with_different_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(slice_workbench, "DATA", Path(tmp)),
                patch.object(slice_workbench, "SLICES_DIR", Path(tmp) / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", Path(tmp) / "materialization_plans"),
            ):
                first = slice_workbench.create_slice(
                    {
                        "slice_name": "same_human_name",
                        "filter_mode": "keyword",
                        "keyword_id": "https://openalex.org/K1",
                        "keyword_display_name": "decision support",
                    }
                )
                second = slice_workbench.create_slice(
                    {
                        "slice_name": "same_human_name",
                        "filter_mode": "keyword",
                        "keyword_id": "https://openalex.org/K2",
                        "keyword_display_name": "ergodesign",
                    }
                )
                titled = slice_workbench.create_slice(
                    {
                        "slice_name": "same_human_name",
                        "title": "Custom human title",
                        "filter_mode": "keyword",
                        "keyword_id": "https://openalex.org/K1",
                        "keyword_display_name": "decision support",
                    }
                )

        self.assertNotEqual(first["slice_id"], second["slice_id"])
        self.assertEqual(first["slice_id"], titled["slice_id"])
        self.assertTrue(first["slice_id"].startswith("same_human_name_"))
        self.assertEqual(len(first["slice_fingerprint"]), 10)

    def test_slice_fingerprint_uses_normalized_corpus_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(slice_workbench, "DATA", Path(tmp)),
                patch.object(slice_workbench, "SLICES_DIR", Path(tmp) / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", Path(tmp) / "materialization_plans"),
            ):
                base = slice_workbench.create_slice(
                    {
                        "slice_name": "normalized",
                        "filter_mode": "all",
                        "country_code": "ru",
                        "institution_id": "https://openalex.org/I123",
                        "from_publication_date": "2020-01-01",
                        "to_publication_date": "2024-12-31",
                        "fraction_modes": "integer",
                        "fraction_mode_default": "integer",
                        "lrdi_p0": 99,
                        "lrdi_lambda": 0.99,
                        "analysis_year": 1999,
                    }
                )
                same_corpus = slice_workbench.create_slice(
                    {
                        "slice_name": "normalized",
                        "filter_mode": "all",
                        "country_code": "RU",
                        "institution_id": "I123",
                        "from_publication_date": "2020-01-01",
                        "to_publication_date": "2024-12-31",
                        "fraction_modes": "strict_authors_count,renorm_valid_authors",
                        "fraction_mode_default": "strict_authors_count",
                        "lrdi_p0": 5,
                        "lrdi_lambda": 0.15,
                        "analysis_year": 2026,
                    }
                )
                different_corpus = slice_workbench.create_slice(
                    {
                        "slice_name": "normalized",
                        "filter_mode": "all",
                        "country_code": "DE",
                        "institution_id": "I123",
                        "from_publication_date": "2020-01-01",
                        "to_publication_date": "2024-12-31",
                    }
                )

        self.assertEqual(base["slice_fingerprint"], same_corpus["slice_fingerprint"])
        self.assertEqual(base["slice_id"], same_corpus["slice_id"])
        self.assertNotEqual(base["slice_fingerprint"], different_corpus["slice_fingerprint"])

    def test_explicit_slice_id_is_used_as_prefix_not_collision_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(slice_workbench, "DATA", Path(tmp)),
                patch.object(slice_workbench, "SLICES_DIR", Path(tmp) / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", Path(tmp) / "materialization_plans"),
            ):
                first = slice_workbench.create_slice({"slice_id": "manual_slice", "filter_mode": "keyword", "keyword_id": "https://openalex.org/K1"})
                second = slice_workbench.create_slice({"slice_id": "manual_slice", "filter_mode": "keyword", "keyword_id": "https://openalex.org/K2"})

        self.assertTrue(first["slice_id"].startswith("manual_slice_"))
        self.assertTrue(second["slice_id"].startswith("manual_slice_"))
        self.assertNotEqual(first["slice_id"], second["slice_id"])

    def test_slice_fingerprint_ignores_sort_but_materialization_fingerprint_uses_sort(self) -> None:
        fake_plan = {
            "decision": {"status": "can_fetch", "can_execute": True, "reasons": [], "warnings": []},
            "estimate": {"estimate_count": 1, "estimate_signature": "estimate", "download_signature": "download"},
            "openalex_filter": "from_publication_date:2020-01-01",
            "filter_classes": {},
            "download_policy": {"user_controls_download_after_estimate": True},
            "limits": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(slice_workbench, "DATA", Path(tmp)),
                patch.object(slice_workbench, "SLICES_DIR", Path(tmp) / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", Path(tmp) / "materialization_plans"),
                patch.object(slice_workbench.query_planner, "plan_slice", return_value=fake_plan),
            ):
                first = slice_workbench.create_slice({"slice_name": "sort_a", "filter_mode": "all", "sort": "cited_by_count:desc"})
                second = slice_workbench.create_slice({"slice_name": "sort_b", "filter_mode": "all", "sort": "publication_date:asc"})
                first_plan = slice_workbench.create_materialization_plan(first["slice_id"])
                second_plan = slice_workbench.create_materialization_plan(second["slice_id"])

        self.assertEqual(first["slice_fingerprint"], second["slice_fingerprint"])
        self.assertNotEqual(first_plan["materialization_fingerprint"], second_plan["materialization_fingerprint"])

    def test_materialization_fingerprint_uses_storage_profile_content(self) -> None:
        cfg = author_slice.config_from_payload({"filter_mode": "all", "sort": "cited_by_count:desc"})
        kwargs = {
            "slice_fingerprint": "slicehash",
            "source_strategy": "openalex_cli",
            "storage_profile_id": "minimal_analytics",
            "download_policy": {"complete_slice_required": True, "allow_incomplete_preview": False},
        }
        first_profiles = {
            "minimal_analytics": {
                "profile_id": "minimal_analytics",
                "selected_fields": ["id", "display_name"],
            }
        }
        second_profiles = {
            "minimal_analytics": {
                "profile_id": "minimal_analytics",
                "selected_fields": ["id", "display_name", "authorships"],
            }
        }

        with patch.object(slice_workbench, "_storage_profiles", return_value=first_profiles):
            first = slice_workbench._materialization_fingerprint(cfg, **kwargs)
        with patch.object(slice_workbench, "_storage_profiles", return_value=second_profiles):
            second = slice_workbench._materialization_fingerprint(cfg, **kwargs)

        self.assertNotEqual(first, second)

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

    def test_materialization_technical_payload_is_normalized_with_signatures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_plan = {
                "decision": {"status": "can_fetch", "can_execute": True, "reasons": [], "warnings": []},
                "estimate": {"estimate_count": 10, "estimate_signature": "estimate-ok", "download_signature": "download-ok"},
                "openalex_filter": "from_publication_date:2020-01-01",
                "filter_classes": {},
                "download_policy": {"user_controls_download_after_estimate": True},
                "limits": {},
            }
            with (
                patch.object(slice_workbench, "SLICES_DIR", tmp_path / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
                patch.object(slice_workbench.query_planner, "plan_slice", return_value=fake_plan),
            ):
                created = slice_workbench.create_slice(
                    {
                        "slice_id": "slice_payload",
                        "filter_mode": "all",
                        "accepted_download_signature": "old-download",
                        "unknown_legacy": "drop-me",
                    }
                )
                materialization = slice_workbench.create_materialization_plan(created["slice_id"])

        technical = materialization["technical_payload"]
        self.assertEqual(technical["accepted_estimate_signature"], "estimate-ok")
        self.assertEqual(technical["accepted_download_signature"], "download-ok")
        self.assertEqual(technical["download_policy"]["user_controls_download_after_estimate"], True)
        self.assertNotIn("unknown_legacy", technical)


if __name__ == "__main__":
    unittest.main()
