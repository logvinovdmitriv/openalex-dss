from __future__ import annotations

import os
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
    def test_subject_ids_accept_openalex_urls_but_store_short_ids(self) -> None:
        cfg = author_slice.config_from_payload(
            {
                "filter_mode": "primary_topic",
                "entity_level": "topic",
                "entity_id_short": "https://openalex.org/T10260",
                "entity_display_name": "Software Engineering Research",
            }
        )

        self.assertEqual(cfg.entity_id_short, "T10260")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with (
                patch.object(slice_workbench, "SLICES_DIR", tmp_path / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
            ):
                doc = slice_workbench.create_slice(
                    {
                        "filter_mode": "primary_topic",
                        "entity_level": "topic",
                        "entity_id_short": "https://openalex.org/T10260",
                        "entity_display_name": "Software Engineering Research",
                    }
                )

                self.assertEqual(doc["technical_payload"]["entity_id_short"], "T10260")
                self.assertEqual(doc["technical_payload"]["entity_id_full"], "https://openalex.org/T10260")

    def test_delete_slice_removes_definition_and_plans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
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
                created = slice_workbench.create_slice({"slice_id": "slice_delete", "filter_mode": "all"})
                plan = slice_workbench.create_materialization_plan(created["slice_id"])

                deleted = slice_workbench.delete_slice(created["slice_id"])

                self.assertTrue(deleted["deleted"])
                self.assertEqual(deleted["deleted_materializations"], 1)
                with self.assertRaises(KeyError):
                    slice_workbench.get_slice(created["slice_id"])
                with self.assertRaises(KeyError):
                    slice_workbench.get_materialization_plan(plan["materialization_id"])

    def test_delete_dump_removes_local_slice_artifacts_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            raw_dir = data / "raw/openalex_cli/slice_delete"
            raw_dir.mkdir(parents=True)
            raw_jsonl = raw_dir / "works.jsonl.gz"
            raw_jsonl.write_text("data", encoding="utf-8")
            (data / "dumps/dump_delete").mkdir(parents=True)
            (data / "tables/dump_delete").mkdir(parents=True)
            run_dir = data / "runs/run_delete"
            run_dir.mkdir(parents=True)
            (run_dir / "metric_run.json").write_text('{"dump_id": "dump_delete"}', encoding="utf-8")
            plans_dir = root / "plans"
            plans_dir.mkdir()
            (plans_dir / "mat_delete.json").write_text('{"materialization_id": "mat_delete", "dump_id": "dump_delete"}', encoding="utf-8")
            dump = {"dump_id": "dump_delete", "raw_jsonl": str(raw_jsonl)}
            with (
                patch.object(slice_workbench, "DATA", data),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", plans_dir),
                patch.object(slice_workbench.metadata_store, "get_slice_dump_by_dump_id", return_value=dump),
                patch.object(slice_workbench.metadata_store, "delete_slice_dump_by_dump_id", return_value={"deleted": 1, "dumps": [dump]}) as delete_metadata,
                patch.object(slice_workbench.artifact_context, "read_active_context", return_value={"active_dump_id": "dump_delete"}),
                patch.object(slice_workbench.artifact_context, "write_active_context") as write_context,
            ):
                deleted = slice_workbench.delete_dump("dump_delete")

            self.assertTrue(deleted["deleted"])
            self.assertFalse((data / "dumps/dump_delete").exists())
            self.assertFalse((data / "tables/dump_delete").exists())
            self.assertFalse(run_dir.exists())
            self.assertFalse(raw_dir.exists())
            self.assertFalse((plans_dir / "mat_delete.json").exists())
            delete_metadata.assert_called_once_with("dump_delete")
            write_context.assert_called_once()

    def test_select_dump_writes_active_context(self) -> None:
        dump = {
            "dump_id": "dump_select",
            "slice_id": "slice_select",
            "allowed_for_final_analysis": True,
            "scientific_completeness": "complete",
        }
        with (
            patch.object(slice_workbench.metadata_store, "get_slice_dump_by_dump_id", return_value=dump),
            patch.object(slice_workbench, "_recent_run_for_dump", return_value="run_select"),
            patch.object(slice_workbench.artifact_context, "write_active_context", return_value={"active_dump_id": "dump_select"}) as write_context,
        ):
            result = slice_workbench.select_dump("dump_select")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["associated_run_id"], "run_select")
        self.assertEqual(result["active_context"]["active_dump_id"], "dump_select")
        write_context.assert_called_once_with(
            run_id="run_select",
            dump_id="dump_select",
            source="selected_local_slice",
            extra={
                "slice_id": "slice_select",
                "associated_run_id": "run_select",
                "allowed_for_final_analysis": True,
                "scientific_completeness": "complete",
            },
        )

    def test_select_dump_accepts_short_checksum_id(self) -> None:
        dump = {
            "dump_id": "dump_abc123",
            "slice_id": "slice_short",
            "allowed_for_final_analysis": True,
            "scientific_completeness": "complete",
        }

        def fake_get_dump(value: str) -> dict[str, object] | None:
            return dump if value == "dump_abc123" else None

        with (
            patch.object(slice_workbench.metadata_store, "get_slice_dump_by_dump_id", side_effect=fake_get_dump),
            patch.object(slice_workbench, "_recent_run_for_dump", return_value="run_short"),
            patch.object(slice_workbench.artifact_context, "write_active_context", return_value={"active_dump_id": "dump_abc123"}) as write_context,
        ):
            result = slice_workbench.select_dump("abc123")

        self.assertEqual(result["dump"]["dump_id"], "dump_abc123")
        self.assertEqual(result["associated_run_id"], "run_short")
        write_context.assert_called_once()
        self.assertEqual(write_context.call_args.kwargs["run_id"], "run_short")
        self.assertEqual(write_context.call_args.kwargs["dump_id"], "dump_abc123")

    def test_list_dumps_includes_filesystem_manifests_when_metadata_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            dump_dir = data / "dumps/dump_disk"
            dump_dir.mkdir(parents=True)
            raw_jsonl = data / "raw/openalex_cli/slice_disk/works.jsonl.gz"
            raw_jsonl.parent.mkdir(parents=True)
            raw_jsonl.write_text("payload", encoding="utf-8")
            (dump_dir / "dump_manifest.json").write_text(
                """{
                  "dump_id": "dump_disk",
                  "slice_id": "slice_disk",
                  "raw_jsonl": "%s",
                  "records_downloaded": 42,
                  "bytes_written": 7,
                  "created_at_utc": "2026-05-08T08:39:23Z",
                  "scientific_completeness": "complete",
                  "allowed_for_final_analysis": true,
                  "openalex_request": {"filter": "publication_year:2026"},
                  "signatures": {"estimate_signature": "estimate", "download_signature": "download"}
                }
                """
                % str(raw_jsonl),
                encoding="utf-8",
            )

            with (
                patch.object(slice_workbench, "DATA", data),
                patch.object(slice_workbench.metadata_store, "list_slice_dumps", return_value=[]),
            ):
                result = slice_workbench.list_dumps()

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["dumps"][0]["dump_id"], "dump_disk")
        self.assertEqual(result["dumps"][0]["records_downloaded"], 42)
        self.assertEqual(result["dumps"][0]["source"], "filesystem")
        self.assertEqual(result["dumps"][0]["health"]["status"], "needs_repair")

    def test_repair_dump_starts_worker_from_existing_raw_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            raw_jsonl = data / "raw/openalex_cli/slice_disk/works.jsonl.gz"
            raw_jsonl.parent.mkdir(parents=True)
            raw_jsonl.write_text("payload", encoding="utf-8")
            dump = {
                "dump_id": "dump_repair",
                "slice_id": "slice_disk",
                "raw_jsonl": str(raw_jsonl),
                "records_downloaded": 42,
                "scientific_completeness": "partial",
                "allowed_for_final_analysis": False,
            }

            captured: dict[str, object] = {}

            def fake_create_run(action: str, payload: dict[str, object], autostart: bool = False) -> dict[str, object]:
                captured["action"] = action
                captured["payload"] = payload
                captured["autostart"] = autostart
                return {"run_id": "run_repair", "status": "queued", "payload": payload}

            with (
                patch.object(slice_workbench, "DATA", data),
                patch.object(slice_workbench.metadata_store, "get_slice_dump_by_dump_id", return_value=dump),
                patch.object(slice_workbench.jobs, "create_run", side_effect=fake_create_run),
                patch.object(slice_workbench.jobs, "start_run", return_value={"run_id": "run_repair", "status": "running"}),
                patch.object(slice_workbench.jobs, "get_run", return_value={"run_id": "run_repair", "status": "running"}),
            ):
                result = slice_workbench.repair_dump("dump_repair")

        self.assertEqual(result["status"], "queued")
        self.assertEqual(captured["action"], "repair_dump")
        self.assertEqual(captured["payload"]["source_path"], str(raw_jsonl))
        self.assertFalse(captured["autostart"])

    def test_list_dumps_marks_unpacked_cli_files_as_repairable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            files_dir = data / "raw/openalex_cli/slice_disk/run_disk/files"
            files_dir.mkdir(parents=True)
            (files_dir / "part.json").write_text('{"id": "https://openalex.org/W1"}', encoding="utf-8")

            with (
                patch.object(slice_workbench, "DATA", data),
                patch.object(slice_workbench.metadata_store, "list_slice_dumps", return_value=[]),
            ):
                result = slice_workbench.list_dumps()

        self.assertEqual(result["total"], 1)
        dump = result["dumps"][0]
        self.assertTrue(dump["dump_id"].startswith("dump_pending_"))
        self.assertEqual(dump["health"]["status"], "needs_repair")
        self.assertTrue(dump["health"]["repairable"])
        self.assertEqual(dump["health"]["files_seen"], 1)
        self.assertEqual(dump["cli_files_dir"], str(files_dir))

    def test_downloaded_files_snapshot_uses_files_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            files_dir = Path(tmp) / "files"
            files_dir.mkdir()
            manifest = Path(tmp) / "files_manifest.json"
            manifest.write_text(
                """{
                  "files": [
                    {"path": "a.json.gz", "bytes": 10, "records": 2},
                    {"path": "b.json.gz", "bytes": 15, "records": 3}
                  ],
                  "status": "ok"
                }""",
                encoding="utf-8",
            )

            snapshot = slice_workbench._downloaded_files_snapshot(files_dir, manifest)

        self.assertEqual(snapshot, {"files_seen": 2, "bytes_written": 25})

    def test_repair_dump_can_start_from_unpacked_cli_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            files_dir = data / "raw/openalex_cli/slice_disk/run_disk/files"
            files_dir.mkdir(parents=True)
            (files_dir / "part.json").write_text('{"id": "https://openalex.org/W1"}', encoding="utf-8")
            dump = {
                "dump_id": "dump_pending_abc",
                "slice_id": "slice_disk",
                "raw_jsonl": str(files_dir.parent / "works.jsonl.gz"),
                "cli_files_dir": str(files_dir),
                "records_downloaded": 0,
                "scientific_completeness": "partial",
                "allowed_for_final_analysis": False,
            }

            captured: dict[str, object] = {}

            def fake_create_run(action: str, payload: dict[str, object], autostart: bool = False) -> dict[str, object]:
                captured["action"] = action
                captured["payload"] = payload
                captured["autostart"] = autostart
                return {"run_id": "run_repair", "status": "queued", "payload": payload}

            with (
                patch.object(slice_workbench, "DATA", data),
                patch.object(slice_workbench.metadata_store, "get_slice_dump_by_dump_id", return_value=dump),
                patch.object(slice_workbench.jobs, "create_run", side_effect=fake_create_run),
                patch.object(slice_workbench.jobs, "start_run", return_value={"run_id": "run_repair", "status": "running"}),
                patch.object(slice_workbench.jobs, "get_run", return_value={"run_id": "run_repair", "status": "running"}),
            ):
                result = slice_workbench.repair_dump("dump_pending_abc")

        self.assertEqual(result["status"], "queued")
        self.assertEqual(captured["action"], "repair_dump")
        self.assertEqual(captured["payload"]["dump_manifest"]["cli_files_dir"], str(files_dir))
        self.assertFalse(captured["autostart"])

    def test_select_dump_uses_filesystem_manifest_when_metadata_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            dump_dir = data / "dumps/dump_disk"
            dump_dir.mkdir(parents=True)
            (dump_dir / "dump_manifest.json").write_text(
                """{
                  "dump_id": "dump_disk",
                  "slice_id": "slice_disk",
                  "records_downloaded": 42,
                  "allowed_for_final_analysis": true,
                  "scientific_completeness": "complete"
                }
                """,
                encoding="utf-8",
            )

            with (
                patch.object(slice_workbench, "DATA", data),
                patch.object(slice_workbench.metadata_store, "get_slice_dump_by_dump_id", return_value=None),
                patch.object(slice_workbench.metadata_store, "list_slice_dumps", return_value=[]),
                patch.object(slice_workbench, "_recent_run_for_dump", return_value=""),
                patch.object(slice_workbench.artifact_context, "write_active_context", return_value={"active_dump_id": "dump_disk"}) as write_context,
            ):
                result = slice_workbench.select_dump("dump_disk")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["dump"]["dump_id"], "dump_disk")
        write_context.assert_called_once()
        self.assertEqual(write_context.call_args.kwargs["dump_id"], "dump_disk")

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
            ) as list_tables,
            patch.object(slice_workbench.warehouse, "read_json_doc", return_value=quality) as read_json_doc,
            patch.object(slice_workbench.artifact_context, "read_active_context", return_value=active_context),
            patch.object(slice_workbench, "list_slices", return_value={"slices": [{"slice_id": "slice_a", "state": "ready"}], "total": 1}),
            patch.object(slice_workbench, "list_materialization_plans", return_value={"materializations": []}),
            patch.object(slice_workbench, "list_dumps", return_value={"dumps": [{"dump_id": "dump_a"}], "total": 1}),
        ):
            summary = slice_workbench.workbench_summary()

        list_tables.assert_called_once_with(run_id="run_a", dump_id="dump_a")
        read_json_doc.assert_called_once_with("quality", run_id="run_a")
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

    def test_workbench_summary_without_active_context_does_not_expose_unscoped_table_counts(self) -> None:
        with (
            patch.object(
                slice_workbench.warehouse,
                "list_tables",
                return_value={"indices": {"rows": 99}, "ratings": {"rows": 99}},
            ) as list_tables,
            patch.object(slice_workbench.warehouse, "read_json_doc", return_value={"quality_counts": {"stale": 99}}) as read_json_doc,
            patch.object(slice_workbench.artifact_context, "read_active_context", return_value={}),
            patch.object(slice_workbench, "list_slices", return_value={"slices": [], "total": 0}),
            patch.object(slice_workbench, "list_materialization_plans", return_value={"materializations": []}),
            patch.object(slice_workbench, "list_dumps", return_value={"dumps": [], "total": 0}),
        ):
            summary = slice_workbench.workbench_summary()

        list_tables.assert_not_called()
        read_json_doc.assert_not_called()
        self.assertEqual(summary["tables"], {})
        self.assertEqual(summary["quality"], {})
        self.assertEqual(summary["workflow"]["active_stage"], "idle")
        self.assertEqual(summary["workflow"]["quality_summary"]["authors_indexed"], 0)

    def test_workbench_summary_with_dump_only_active_context_does_not_read_unscoped_quality(self) -> None:
        active_context = {"active_dump_id": "dump_a"}
        with (
            patch.object(slice_workbench.warehouse, "list_tables", return_value={"works": {"rows": 3}}) as list_tables,
            patch.object(slice_workbench.warehouse, "read_json_doc", return_value={"quality_counts": {"stale": 99}}) as read_json_doc,
            patch.object(slice_workbench.artifact_context, "read_active_context", return_value=active_context),
            patch.object(slice_workbench, "list_slices", return_value={"slices": [], "total": 0}),
            patch.object(slice_workbench, "list_materialization_plans", return_value={"materializations": []}),
            patch.object(slice_workbench, "list_dumps", return_value={"dumps": [{"dump_id": "dump_a"}], "total": 1}),
        ):
            summary = slice_workbench.workbench_summary()

        list_tables.assert_called_once_with(run_id="", dump_id="dump_a")
        read_json_doc.assert_not_called()
        self.assertEqual(summary["quality"], {})

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

    def test_workbench_summary_prefers_ready_active_tables_over_stale_materialization(self) -> None:
        active_context = {"active_run_id": "run_a", "active_dump_id": "dump_a"}
        with (
            patch.object(
                slice_workbench.warehouse,
                "list_tables",
                return_value={"works": {"rows": 3}, "authorships": {"rows": 4}, "indices": {"rows": 2}},
            ),
            patch.object(slice_workbench.warehouse, "read_json_doc", return_value={}),
            patch.object(slice_workbench.artifact_context, "read_active_context", return_value=active_context),
            patch.object(slice_workbench, "list_slices", return_value={"slices": [{"slice_id": "slice_a", "state": "ready"}], "total": 1}),
            patch.object(
                slice_workbench,
                "list_materialization_plans",
                return_value={"materializations": [{"materialization_id": "mat_a", "state": "materializing"}]},
            ),
            patch.object(slice_workbench, "list_dumps", return_value={"dumps": [{"dump_id": "dump_a"}], "total": 1}),
        ):
            summary = slice_workbench.workbench_summary()

        self.assertEqual(summary["workflow"]["active_stage"], "analyzed")

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
                    {"storage_profile_id": "minimal_analytics", "download_policy": payload["download_policy"], "download_dir": "custom_slices"},
                )
                self.assertEqual(materialization["source_strategy"], "openalex_cli")
                self.assertEqual(materialization["download_dir"], "custom_slices")
                self.assertEqual(materialization["technical_payload"]["download_dir"], "custom_slices")
                self.assertEqual(materialization["download_policy"]["complete_slice_required"], True)
                self.assertEqual(materialization["download_policy"]["user_controls_download_after_estimate"], True)
                self.assertEqual(materialization["state"], "planned")
                self.assertIn("runs/{run_id}/tables/indices.csv", materialization["outputs"])
                self.assertIn("runs/{run_id}/tables/indices.parquet", materialization["outputs"])
                self.assertIn("runs/{run_id}/tables/ratings.csv", materialization["outputs"])
                self.assertIn("runs/{run_id}/tables/ratings.parquet", materialization["outputs"])
                self.assertIn("runs/{run_id}/reports/report_{report_scope_hash}.json", materialization["outputs"])

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

    def test_run_materialization_updates_download_dir_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = {
                "materialization_id": "mat_download_dir",
                "slice_id": "slice_missing_ok",
                "state": "planned",
                "technical_payload": {
                    "entity_level": "subfield",
                    "entity_id_short": "1706",
                    "entity_display_name": "Computer Science Applications",
                    "filter_mode": "primary_topic",
                    "from_publication_date": "2020-01-01",
                    "to_publication_date": "2025-12-31",
                },
                "estimated": {},
                "accepted_estimate_signature": "estimate",
                "accepted_download_signature": "download",
            }
            captured: dict[str, object] = {}
            with (
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
                patch.object(slice_workbench.jobs, "create_run", side_effect=lambda action, payload, autostart=False: captured.update({"action": action, "payload": payload}) or {"run_id": "run_download_dir"}),
                patch.object(slice_workbench.jobs, "start_run", return_value=None),
                patch.object(slice_workbench.jobs, "get_run", return_value={"run_id": "run_download_dir", "status": "queued"}),
            ):
                slice_workbench._write_materialization(plan)
                slice_workbench.run_materialization("mat_download_dir", {"download_dir": "custom_slices", "api_key": "test-key"})

                updated = slice_workbench.get_materialization_plan("mat_download_dir")
        self.assertEqual(updated["download_dir"], "custom_slices")
        self.assertEqual(updated["technical_payload"]["download_dir"], "custom_slices")
        self.assertEqual((captured["payload"] or {})["download_dir"], "custom_slices")

    def test_run_materialization_requires_openalex_key_before_creating_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = {
                "materialization_id": "mat_requires_key",
                "slice_id": "slice_requires_key",
                "state": "planned",
                "technical_payload": {
                    "entity_level": "subfield",
                    "entity_id_short": "1706",
                    "entity_display_name": "Computer Science Applications",
                    "filter_mode": "primary_topic",
                    "from_publication_date": "2020-01-01",
                    "to_publication_date": "2025-12-31",
                },
                "estimated": {},
                "accepted_estimate_signature": "estimate",
                "accepted_download_signature": "download",
            }
            with (
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
                patch.object(slice_workbench.jobs, "create_run") as create_run,
                patch.dict(os.environ, {"OPENALEX_API_KEY": ""}, clear=False),
            ):
                slice_workbench._write_materialization(plan)
                with self.assertRaisesRegex(ValueError, "ключ OpenAlex"):
                    slice_workbench.run_materialization("mat_requires_key", {})
                create_run.assert_not_called()

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
                patch.dict("os.environ", {"OPENALEX_API_KEY": "test-key"}),
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
                patch.dict("os.environ", {"OPENALEX_API_KEY": "test-key"}),
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

    def test_materialization_plan_reuses_current_estimate_without_api_replan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = {
                "slice_id": "slice_reuse_estimate",
                "entity_level": "subfield",
                "entity_id_short": "1706",
                "entity_display_name": "Computer Science Applications",
            }
            cfg = author_slice.config_from_payload({**payload, "workflow_mode": "strict_works"})
            fake_plan = {
                "decision": {"status": "can_fetch", "can_execute": True, "reasons": [], "warnings": []},
                "estimate": {
                    "estimate_count": 10,
                    "estimate_signature": slice_workbench.corpus_signature(cfg),
                    "download_signature": slice_workbench.cli_download_signature(cfg),
                },
                "openalex_filter": "primary_topic.subfield.id:1706",
                "filter_classes": {},
                "download_policy": {"complete_slice_required": True, "allow_incomplete_preview": False, "user_controls_download_after_estimate": True},
                "limits": {},
            }
            with (
                patch.object(slice_workbench, "SLICES_DIR", tmp_path / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
                patch.object(slice_workbench.query_planner, "plan_slice", return_value=fake_plan) as plan_slice,
            ):
                created = slice_workbench.create_slice(payload)
                slice_workbench.estimate_slice(created["slice_id"])
                materialization = slice_workbench.create_materialization_plan(created["slice_id"])

            self.assertEqual(plan_slice.call_count, 1)
            self.assertEqual(materialization["technical_payload"]["query_plan"]["estimate"]["estimate_count"], 10)

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
                        "unknown_extra": "drop-me",
                    }
                )
                materialization = slice_workbench.create_materialization_plan(created["slice_id"])

        technical = materialization["technical_payload"]
        self.assertEqual(technical["accepted_estimate_signature"], "estimate-ok")
        self.assertEqual(technical["accepted_download_signature"], "download-ok")
        self.assertEqual(technical["download_policy"]["user_controls_download_after_estimate"], True)
        self.assertNotIn("unknown_extra", technical)


if __name__ == "__main__":
    unittest.main()
