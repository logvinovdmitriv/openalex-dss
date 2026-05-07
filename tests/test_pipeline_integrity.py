from __future__ import annotations

import sys
import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps/api"
SRC = ROOT / "src"
for path in (API, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services import artifact_context, cohorts, jobs, materialization_jobs, metadata_store, pipeline, reports, warehouse  # noqa: E402


class PipelineIntegrityTests(unittest.TestCase):
    def test_accepted_download_signature_mismatch_blocks_download(self) -> None:
        fake_plan = {
            "decision": {"status": "can_fetch", "can_execute": True, "reasons": []},
            "estimate": {
                "estimate_signature": "estimate-ok",
                "download_signature": "download-current",
            },
        }
        payload = {
            "entity_level": "subfield",
            "entity_id_short": "1706",
            "entity_display_name": "Computer Science Applications",
            "filter_mode": "primary_topic",
            "from_publication_date": "2020-01-01",
            "to_publication_date": "2025-12-31",
            "accepted_estimate_signature": "estimate-ok",
            "accepted_download_signature": "download-old",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(pipeline, "DATA", Path(tmp)),
                patch.object(pipeline.query_planner, "plan_slice", return_value=fake_plan),
            ):
                with self.assertRaises(ValueError) as raised:
                    pipeline.fetch_slice_dump(payload, require_accepted_signatures=True)
        self.assertIn("Способ загрузки", str(raised.exception))

    def test_build_from_openalex_requires_accepted_signatures(self) -> None:
        fake_plan = {
            "decision": {"status": "can_fetch", "can_execute": True, "reasons": []},
            "estimate": {
                "estimate_signature": "estimate-ok",
                "download_signature": "download-current",
            },
        }
        payload = {
            "entity_level": "subfield",
            "entity_id_short": "1706",
            "entity_display_name": "Computer Science Applications",
            "filter_mode": "primary_topic",
            "from_publication_date": "2020-01-01",
            "to_publication_date": "2025-12-31",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(pipeline, "DATA", Path(tmp)),
                patch.object(pipeline.query_planner, "plan_slice", return_value=fake_plan),
            ):
                with self.assertRaises(ValueError) as raised:
                    pipeline.fetch_slice_dump(payload, require_accepted_signatures=True)
        self.assertIn("подпись оценки", str(raised.exception))

    def test_fetch_slice_dump_requires_signatures_by_default(self) -> None:
        fake_plan = {
            "decision": {"status": "can_fetch", "can_execute": True, "reasons": []},
            "estimate": {
                "estimate_signature": "estimate-ok",
                "download_signature": "download-current",
            },
        }
        payload = {
            "entity_level": "subfield",
            "entity_id_short": "1706",
            "entity_display_name": "Computer Science Applications",
            "filter_mode": "primary_topic",
            "from_publication_date": "2020-01-01",
            "to_publication_date": "2025-12-31",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.dict("os.environ", {}, clear=True),
                patch.object(pipeline, "DATA", Path(tmp)),
                patch.object(pipeline.query_planner, "plan_slice", return_value=fake_plan),
            ):
                with self.assertRaises(ValueError) as raised:
                    pipeline.fetch_slice_dump(payload)
        self.assertIn("подпись оценки", str(raised.exception))

    def test_direct_build_run_rejects_missing_accepted_signatures(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                jobs.create_run("build_from_openalex", {})

    def test_direct_fetch_run_rejects_missing_accepted_signatures(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                jobs.create_run("fetch_slice_dump", {})

    def test_create_run_rejects_unsupported_actions_before_queueing(self) -> None:
        for action in ("plan", "unknown"):
            with self.assertRaises(ValueError) as raised:
                jobs.create_run(action, {"filter_mode": "all"}, autostart=False)

            self.assertIn(f"Unsupported run action: {action}", str(raised.exception))

    def test_create_run_accepts_supported_analysis_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(jobs, "RUNS_DIR", Path(tmp) / "runs"):
                run = jobs.create_run("recalculate", {"dump_id": "dump_a"}, autostart=False)

        self.assertEqual(run["action"], "recalculate")
        self.assertEqual(run["payload"]["dump_id"], "dump_a")
        self.assertEqual(run["status"], "queued")
        self.assertEqual(run["artifacts"], {})

    def test_local_file_import_is_not_a_job_action(self) -> None:
        self.assertEqual(materialization_jobs.SUPPORTED_MATERIALIZATION_ACTIONS, {"fetch_slice_dump", "build_from_openalex"})

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(jobs, "RUNS_DIR", Path(tmp) / "runs"):
                with self.assertRaises(ValueError) as raised:
                    jobs.create_run("local_file_import", {"source_path": "/tmp/works.jsonl.gz"}, autostart=False)

        self.assertIn("Unsupported run action: local_file_import", str(raised.exception))

    def test_job_artifact_links_are_fetch_result_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            raw = data / "raw/openalex_cli/slice_a/works.jsonl.gz"
            manifest = raw.with_name("dump_manifest.json")
            files_manifest = raw.with_name("files_manifest.json")
            result = {
                "dump": {
                    "raw_jsonl": str(raw),
                    "files_manifest": str(files_manifest),
                }
            }
            with patch.object(jobs, "DATA", data):
                links = jobs._artifact_links("fetch_slice_dump", "run_fetch", result)

        self.assertEqual(links["raw_jsonl"], "raw/openalex_cli/slice_a/works.jsonl.gz")
        self.assertEqual(links["dump_manifest"], "raw/openalex_cli/slice_a/dump_manifest.json")
        self.assertEqual(links["files_manifest"], "raw/openalex_cli/slice_a/files_manifest.json")
        self.assertNotIn("indices", links)
        self.assertNotIn("report_bundle", links)

    def test_job_artifact_links_use_completed_run_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            result = {
                "archive": {
                    "run_dir": str(data / "runs/run_a"),
                    "copied": {
                        "passports/slice_passport.json": str(data / "runs/run_a/passports/slice_passport.json"),
                        "tables/indices.csv": str(data / "runs/run_a/tables/indices.csv"),
                    },
                }
            }
            with patch.object(jobs, "DATA", data):
                links = jobs._artifact_links("recalculate", "run_a", result)

        self.assertEqual(links["slice_passport"], "runs/run_a/passports/slice_passport.json")
        self.assertEqual(links["indices"], "runs/run_a/tables/indices.csv")
        self.assertEqual(links["ratings"], "runs/run_a/tables/ratings.csv")
        self.assertEqual(links["report_bundle"], "runs/run_a/reports")

    def test_cli_origin_fetch_meta_keeps_dump_manifest_context(self) -> None:
        captured: dict[str, object] = {}

        def fake_run_compute(*args: object, **kwargs: object) -> dict[str, object]:
            captured["extra_primary_artifacts"] = kwargs["extra_primary_artifacts"]
            return {"input_tables": {}, "input_table_checksums": {}}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "works.jsonl"
            raw.write_text(json.dumps(_work("W1")) + "\n", encoding="utf-8")
            profile = {"path": str(raw), "bytes": raw.stat().st_size, "sha256": "raw-sha"}
            dump_manifest = {
                "dump_id": "dump_ctx",
                "raw_jsonl": str(raw),
                "raw_jsonl_sha256": "raw-sha",
                "used_api_key": True,
                "openalex_request": {"filter": "primary_topic.subfield.id:1706"},
                "signatures": {
                    "accepted_estimate_signature": "estimate-ok",
                    "accepted_download_signature": "download-ok",
                },
            }

            with (
                patch.object(pipeline, "DATA", root / "data"),
                patch.object(pipeline, "resolve_safe_path", return_value=raw),
                patch.object(pipeline, "file_profile", return_value=profile),
                patch.object(pipeline, "_run_compute", side_effect=fake_run_compute),
                patch.object(pipeline, "_archive_run_artifacts", return_value={}),
                patch.object(pipeline, "_write_pipeline_summary", return_value=None),
            ):
                pipeline.import_local_file(
                    {
                        "source_path": str(raw),
                        "dump_id": "dump_ctx",
                        "dump_manifest": dump_manifest,
                        "entity_level": "subfield",
                        "entity_id_short": "1706",
                        "entity_display_name": "Computer Science Applications",
                    }
                )

            dump_manifest_path = root / "data/dumps/dump_ctx/dump_manifest.json"
            fetch_meta = json.loads((root / "data/dumps/dump_ctx/fetch_meta.json").read_text(encoding="utf-8"))
            scoped_manifest = json.loads(dump_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(fetch_meta["source_type"], "openalex_cli_dump_import")
            self.assertEqual(fetch_meta["dump_id"], "dump_ctx")
            self.assertEqual(fetch_meta["dump_manifest_path"], str(dump_manifest_path))
            self.assertEqual(fetch_meta["openalex_filter"], "primary_topic.subfield.id:1706")
            self.assertEqual(fetch_meta["accepted_download_signature"], "download-ok")
            self.assertEqual(fetch_meta["analysis_eligibility"]["status"], "blocked_not_for_final_analysis")
            self.assertEqual(scoped_manifest["dump_id"], "dump_ctx")
            self.assertEqual(captured["extra_primary_artifacts"]["dump/dump_manifest.json"], dump_manifest_path)
            self.assertFalse((root / "data/passports/fetch_meta.json").exists())

    def test_import_local_file_normalizes_dump_tables_under_dump_scope(self) -> None:
        captured: dict[str, object] = {}

        def fake_run_compute(*args: object, **kwargs: object) -> dict[str, object]:
            captured["input_tables"] = kwargs["input_tables"]
            captured["extra_primary_artifacts"] = kwargs["extra_primary_artifacts"]
            return {"input_tables": {}, "input_table_checksums": {}, "passport_outputs": {}}

        def fake_archive(_cfg: object, payload: dict[str, object]) -> dict[str, object]:
            captured["archive_payload"] = payload
            return {"run_id": "run_dump_scope", "dump_id": "dump_scope"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "works.jsonl"
            raw.write_text(json.dumps(_work("W1")) + "\n", encoding="utf-8")
            profile = {"path": str(raw), "bytes": raw.stat().st_size, "sha256": "raw-sha"}
            stale_manifest = root / "data" / "dumps" / "dump_scope" / "dump_manifest.json"
            stale_manifest.parent.mkdir(parents=True)
            stale_manifest.write_text(json.dumps({"dump_id": "stale_dump"}), encoding="utf-8")

            with (
                patch.object(pipeline, "DATA", root / "data"),
                patch.object(pipeline, "resolve_safe_path", return_value=raw),
                patch.object(pipeline, "file_profile", return_value=profile),
                patch.object(pipeline, "_run_compute", side_effect=fake_run_compute),
                patch.object(pipeline, "_archive_run_artifacts", side_effect=fake_archive),
                patch.object(pipeline, "_write_pipeline_summary", return_value=None),
                patch.object(pipeline.reports, "build_report_bundle", return_value={}),
            ):
                result = pipeline.import_local_file(
                    {
                        "source_path": str(raw),
                        "run_id": "run_dump_scope",
                        "dump_id": "dump_scope",
                        "entity_level": "subfield",
                        "entity_id_short": "1706",
                        "entity_display_name": "Computer Science Applications",
                    }
                )

            data = root / "data"
            dump_dir = data / "dumps" / "dump_scope"
            tables_dir = data / "tables" / "dump_scope"

            self.assertTrue((dump_dir / "normalized" / "works_flat.csv").is_file())
            self.assertTrue((dump_dir / "normalized" / "authorships_flat.csv").is_file())
            self.assertTrue((dump_dir / "normalized" / "work_topics_flat.csv").is_file())
            self.assertTrue((dump_dir / "parquet" / "works_flat.parquet").is_file())
            self.assertTrue((tables_dir / "works.parquet").is_file())
            self.assertTrue((tables_dir / "authorships.parquet").is_file())
            self.assertTrue((tables_dir / "work_topics.parquet").is_file())
            self.assertTrue((dump_dir / "quality_report.json").is_file())
            self.assertTrue((dump_dir / "fetch_meta.json").is_file())
            self.assertFalse((data / "normalized" / "works_flat.csv").exists())
            self.assertFalse((data / "parquet" / "works_flat.parquet").exists())
            self.assertFalse((data / "passports" / "fetch_meta.json").exists())
            self.assertFalse((data / "passports" / "pipeline_summary.json").exists())
            self.assertFalse((data / "results").exists())
            self.assertEqual(Path(captured["input_tables"]["works"]), tables_dir / "works.parquet")
            self.assertEqual(captured["archive_payload"]["fetch_meta"], str(dump_dir / "fetch_meta.json"))
            self.assertEqual(captured["archive_payload"]["quality_report"], str(dump_dir / "quality_report.json"))
            self.assertEqual(captured["extra_primary_artifacts"]["dump/fetch_meta.json"], dump_dir / "fetch_meta.json")
            self.assertEqual(captured["extra_primary_artifacts"]["dump/quality_report.json"], dump_dir / "quality_report.json")
            self.assertNotIn("dump/dump_manifest.json", captured["extra_primary_artifacts"])
            self.assertFalse((dump_dir / "dump_manifest.json").exists())
            self.assertEqual(result["fetch_meta"], str(dump_dir / "fetch_meta.json"))
            self.assertEqual(result["quality_report"], str(dump_dir / "quality_report.json"))

    def test_build_blocks_ineligible_dump_without_dev_override(self) -> None:
        dump = {
            "dump_id": "dump_bad",
            "raw_jsonl": "/tmp/works.jsonl.gz",
            "allowed_for_final_analysis": False,
            "records_downloaded": 10,
            "signatures": {},
        }
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(pipeline, "fetch_slice_dump", return_value={"status": "ok", "dump": dump}),
        ):
            with self.assertRaises(ValueError) as raised:
                jobs._dispatch("run_blocked", "build_from_openalex", {"accepted_estimate_signature": "e", "accepted_download_signature": "d"})
        self.assertIn("не допущен", str(raised.exception))

    def test_dev_unchecked_build_marks_report_not_final(self) -> None:
        dump = {
            "dump_id": "dump_dev",
            "raw_jsonl": "/tmp/works.jsonl.gz",
            "allowed_for_final_analysis": False,
            "records_downloaded": 10,
            "signatures": {},
        }
        captured: dict[str, object] = {}

        def fake_import(payload: dict[str, object]) -> dict[str, object]:
            captured.update(payload)
            return {"status": "ok", "mode": "import_local_file"}

        with (
            patch.dict("os.environ", {"OPENALEX_DSS_ALLOW_UNCHECKED_DOWNLOAD": "1"}, clear=True),
            patch.object(pipeline, "fetch_slice_dump", return_value={"status": "ok", "dump": dump}),
            patch.object(pipeline, "import_local_file", side_effect=fake_import),
            patch.object(jobs, "update_progress", return_value=None),
        ):
            result = jobs._dispatch("run_dev", "build_from_openalex", {})

        self.assertEqual(result["analysis_eligibility"]["status"], "dev_only_not_for_final_analysis")
        self.assertEqual(captured["analysis_eligibility"]["status"], "dev_only_not_for_final_analysis")
        self.assertEqual(captured["active_context_source"], "materialization")

    def test_jobs_dispatch_delegates_analysis_actions_to_analysis_jobs(self) -> None:
        with patch.object(jobs.analysis_jobs, "recalculate", return_value={"status": "ok"}) as recalculate:
            result = jobs._dispatch("run_analysis", "recalculate", {"dump_id": "dump_a", "unknown_extra": "drop-me"})

        self.assertEqual(result, {"status": "ok"})
        recalculate.assert_called_once()
        self.assertEqual(recalculate.call_args.args[0], "run_analysis")
        self.assertEqual(recalculate.call_args.args[1]["dump_id"], "dump_a")
        self.assertNotIn("unknown_extra", recalculate.call_args.args[1])

    def test_jobs_dispatch_delegates_materialization_actions_to_materialization_jobs(self) -> None:
        with patch.object(jobs.materialization_jobs, "dispatch", return_value={"status": "ok"}) as dispatch:
            result = jobs._dispatch(
                "run_materialization",
                "build_from_openalex",
                {"accepted_estimate_signature": "estimate", "accepted_download_signature": "download", "unknown_extra": "drop-me"},
            )

        self.assertEqual(result, {"status": "ok"})
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.args[0], "run_materialization")
        self.assertEqual(dispatch.call_args.args[1], "build_from_openalex")
        self.assertEqual(dispatch.call_args.args[2]["accepted_download_signature"], "download")
        self.assertNotIn("unknown_extra", dispatch.call_args.args[2])
        self.assertIn("download_progress_callback", dispatch.call_args.kwargs)
        self.assertIn("update_progress_callback", dispatch.call_args.kwargs)

    def test_internal_plan_job_action_is_not_supported(self) -> None:
        with self.assertRaises(ValueError) as raised:
            jobs._dispatch("run_plan", "plan", {"filter_mode": "all"})

        self.assertIn("Unsupported run action: plan", str(raised.exception))

    def test_materialization_lifecycle_hooks_delegate_to_slice_workbench(self) -> None:
        result = {"status": "ok"}
        payload = {"materialization_id": "mat_a"}
        with (
            patch("app.services.slice_workbench.mark_materialization_run_completed") as completed,
            patch("app.services.slice_workbench.mark_materialization_run_failed") as failed,
        ):
            materialization_jobs.mark_completed("run_mat", "build_from_openalex", result, payload)
            materialization_jobs.mark_failed("run_mat", "fetch_slice_dump", "boom", payload)
            materialization_jobs.mark_completed("run_analysis", "recalculate", result, payload)
            materialization_jobs.mark_failed("run_analysis", "recalculate", "boom", payload)

        completed.assert_called_once_with("run_mat", result, materialization_id="mat_a")
        failed.assert_called_once_with("run_mat", "boom", materialization_id="mat_a")

    def test_recalculate_recovers_analysis_eligibility_from_dump_manifest(self) -> None:
        captured: dict[str, object] = {}

        def fake_run_compute(*args: object, **kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {"input_tables": {}, "input_table_checksums": {}}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dump_dir = root / "dumps" / "dump_recalc"
            dump_dir.mkdir(parents=True)
            (dump_dir / "dump_manifest.json").write_text(
                json.dumps(
                    {
                        "dump_id": "dump_recalc",
                        "allowed_for_final_analysis": True,
                        "records_downloaded": 5,
                        "scientific_completeness": "complete",
                        "signatures": {
                            "estimate_signature_verified": True,
                            "accepted_estimate_signature_verified": True,
                            "download_signature_verified": True,
                            "compatible": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (dump_dir / "fetch_meta.json").write_text("{}", encoding="utf-8")
            (dump_dir / "quality_report.json").write_text("{}", encoding="utf-8")
            with (
                patch.object(pipeline, "DATA", root),
                patch.object(pipeline, "resolve_dump_tables", return_value={"works": root / "works.parquet", "authorships": root / "authorships.parquet", "work_topics": root / "work_topics.parquet"}),
                patch.object(pipeline, "_run_compute", side_effect=fake_run_compute),
                patch.object(pipeline, "_archive_run_artifacts", return_value={}),
                patch.object(pipeline, "_write_pipeline_summary", return_value=None),
            ):
                result = pipeline.recalculate(
                    {
                        "dump_id": "dump_recalc",
                        "entity_level": "subfield",
                        "entity_id_short": "1706",
                        "entity_display_name": "Computer Science Applications",
                    }
                )

        self.assertEqual(captured["analysis_eligibility"]["status"], "final")
        self.assertEqual(captured["extra_primary_artifacts"]["dump/fetch_meta.json"], dump_dir / "fetch_meta.json")
        self.assertEqual(captured["extra_primary_artifacts"]["dump/quality_report.json"], dump_dir / "quality_report.json")
        self.assertEqual(captured["extra_primary_artifacts"]["dump/dump_manifest.json"], dump_dir / "dump_manifest.json")
        self.assertEqual(result["analysis_eligibility"]["allowed_for_final_analysis"], True)

    def test_recalculate_omits_missing_dump_provenance_from_checksums(self) -> None:
        captured: dict[str, object] = {}

        def fake_run_compute(*args: object, **kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {"input_tables": {}, "input_table_checksums": {}}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(pipeline, "DATA", root),
                patch.object(pipeline, "resolve_dump_tables", return_value={"works": root / "works.parquet", "authorships": root / "authorships.parquet", "work_topics": root / "work_topics.parquet"}),
                patch.object(pipeline, "_run_compute", side_effect=fake_run_compute),
                patch.object(pipeline, "_archive_run_artifacts", return_value={}),
                patch.object(pipeline, "_write_pipeline_summary", return_value=None),
            ):
                pipeline.recalculate(
                    {
                        "dump_id": "dump_without_provenance",
                        "entity_level": "subfield",
                        "entity_id_short": "1706",
                        "entity_display_name": "Computer Science Applications",
                    }
                )

        self.assertEqual(captured["extra_primary_artifacts"], {})

    def test_recalculate_requires_dump_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(pipeline, "DATA", Path(tmp)):
                with self.assertRaises(FileNotFoundError):
                    pipeline.recalculate(
                        {
                            "dump_id": "missing_dump",
                            "entity_level": "subfield",
                            "entity_id_short": "1706",
                            "entity_display_name": "Computer Science Applications",
                        }
                    )

    def test_recalculate_uses_requested_dump_tables_not_global_fallback(self) -> None:
        captured: dict[str, object] = {}

        def fake_author_work_metrics(works_path: object, authorships_path: object, *args: object, **kwargs: object) -> list[dict[str, object]]:
            captured["works_path"] = works_path
            captured["authorships_path"] = authorships_path
            return []

        def fake_build_passports(*args: object, **kwargs: object) -> dict[str, object]:
            run_id = str(kwargs["run_id"])
            out = pipeline.DATA / "runs" / run_id / "passports"
            captured["passport_out_dir"] = out
            captured["passport_input_tables"] = kwargs.get("input_tables")
            captured["passport_primary_artifacts"] = kwargs.get("primary_artifacts")
            out.mkdir(parents=True, exist_ok=True)
            (out / "slice_passport.json").write_text("{}", encoding="utf-8")
            (out / "calculation_passport.json").write_text("{}", encoding="utf-8")
            (out / "checksums.json").write_text("{}", encoding="utf-8")
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dump_a = root / "tables" / "dump_A"
            dump_b = root / "tables" / "dump_B"
            global_parquet = root / "parquet"
            for base in (dump_a, dump_b, global_parquet):
                base.mkdir(parents=True)
                for table in ("works", "authorships", "work_topics"):
                    (base / f"{table}.parquet").write_text(f"{base.name}:{table}", encoding="utf-8")

            with (
                patch.object(pipeline, "DATA", root),
                patch.object(pipeline, "build_author_work_metrics", side_effect=fake_author_work_metrics),
                patch.object(pipeline, "compute_indices", return_value=[]),
                patch.object(pipeline, "build_ratings", return_value=[]),
                patch.object(pipeline, "build_passports", side_effect=fake_build_passports),
                patch.object(pipeline.reports, "build_report_bundle", return_value={}),
                patch.object(pipeline, "_archive_run_artifacts", return_value={}),
                patch.object(pipeline, "_write_pipeline_summary", return_value=None),
            ):
                pipeline.recalculate(
                    {
                        "dump_id": "dump_A",
                        "run_id": "run_A",
                        "analysis_eligibility": {"status": "final", "allowed_for_final_analysis": True},
                        "entity_level": "subfield",
                        "entity_id_short": "1706",
                        "entity_display_name": "Computer Science Applications",
                    }
                )

        self.assertEqual(Path(captured["works_path"]), dump_a / "works.parquet")
        self.assertEqual(Path(captured["authorships_path"]), dump_a / "authorships.parquet")
        self.assertEqual(Path(captured["passport_out_dir"]), root / "runs" / "run_A" / "passports")
        self.assertIn("works", captured["passport_input_tables"])
        self.assertEqual(captured["passport_input_tables"]["works"]["path"], str(dump_a / "works.parquet"))
        self.assertEqual(captured["passport_primary_artifacts"]["dump/tables/works.parquet"]["path"], str(dump_a / "works.parquet"))
        self.assertEqual(Path(captured["passport_primary_artifacts"]["run/tables/indices.csv"]), root / "runs" / "run_A" / "tables" / "indices.csv")

    def test_run_compute_includes_extra_primary_artifacts_in_scoped_checksums(self) -> None:
        captured: dict[str, object] = {}

        def fake_build_passports(*args: object, **kwargs: object) -> dict[str, object]:
            captured["primary_artifacts"] = kwargs.get("primary_artifacts")
            out = pipeline.DATA / "runs" / str(kwargs["run_id"]) / "passports"
            out.mkdir(parents=True, exist_ok=True)
            for filename in ("slice_passport.json", "calculation_passport.json", "checksums.json"):
                (out / filename).write_text("{}", encoding="utf-8")
            return {}

        cfg = SimpleNamespace(
            fraction_modes=("integer",),
            lrdi_p0=5,
            lrdi_lambda=0.15,
            analysis_year=2026,
            fraction_mode_default="integer",
            slice_name="slice_extra_primary",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "inputs"
            input_dir.mkdir()
            input_tables = {}
            for name in ("works", "authorships", "work_topics"):
                path = input_dir / f"{name}.parquet"
                path.write_text(f"{name}", encoding="utf-8")
                input_tables[name] = path
            fetch_meta = root / "dumps" / "dump_extra" / "fetch_meta.json"
            quality = root / "dumps" / "dump_extra" / "quality_report.json"
            fetch_meta.parent.mkdir(parents=True)
            fetch_meta.write_text("{}", encoding="utf-8")
            quality.write_text("{}", encoding="utf-8")

            with (
                patch.object(pipeline, "DATA", root),
                patch.object(pipeline, "build_author_work_metrics", side_effect=lambda *_args, **_kwargs: Path(_args[2]).write_text("author_work\n", encoding="utf-8")),
                patch.object(pipeline, "compute_indices", side_effect=lambda _source, target, *_args: Path(target).write_text("indices\n", encoding="utf-8")),
                patch.object(pipeline, "build_ratings", side_effect=lambda _source, target: Path(target).write_text("ratings\n", encoding="utf-8")),
                patch.object(pipeline, "build_passports", side_effect=fake_build_passports),
                patch.dict("os.environ", {}, clear=True),
            ):
                pipeline._run_compute(
                    cfg,
                    run_id="run_extra",
                    dump_id="dump_extra",
                    input_tables=input_tables,
                    extra_primary_artifacts={
                        "dump/fetch_meta.json": fetch_meta,
                        "dump/quality_report.json": quality,
                    },
                )

        self.assertEqual(captured["primary_artifacts"]["dump/fetch_meta.json"], fetch_meta)
        self.assertEqual(captured["primary_artifacts"]["dump/quality_report.json"], quality)
        self.assertIn("run/tables/indices.csv", captured["primary_artifacts"])

    def test_run_compute_writes_scoped_outputs_without_global_fallback(self) -> None:
        cfg = SimpleNamespace(
            fraction_modes=("integer",),
            lrdi_p0=5,
            lrdi_lambda=0.15,
            analysis_year=2026,
            fraction_mode_default="integer",
            slice_name="slice_scoped_outputs",
        )

        def fake_build_passports(*args: object, **_kwargs: object) -> dict[str, object]:
            out = pipeline.DATA / "runs" / str(_kwargs["run_id"]) / "passports"
            out.mkdir(parents=True, exist_ok=True)
            for filename in ("slice_passport.json", "calculation_passport.json", "checksums.json"):
                (out / filename).write_text("{}", encoding="utf-8")
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "inputs"
            input_dir.mkdir()
            input_tables = {}
            for name in ("works", "authorships", "work_topics"):
                path = input_dir / f"{name}.parquet"
                path.write_text(f"{name}", encoding="utf-8")
                input_tables[name] = path

            with (
                patch.object(pipeline, "DATA", root),
                patch.object(pipeline, "build_author_work_metrics", side_effect=lambda *_args, **_kwargs: Path(_args[2]).write_text("author_work\n", encoding="utf-8")),
                patch.object(pipeline, "compute_indices", side_effect=lambda _source, target, *_args: Path(target).write_text("indices\n", encoding="utf-8")),
                patch.object(pipeline, "build_ratings", side_effect=lambda _source, target: Path(target).write_text("ratings\n", encoding="utf-8")),
                patch.object(pipeline, "build_passports", side_effect=fake_build_passports),
                patch.dict("os.environ", {}, clear=True),
            ):
                result = pipeline._run_compute(cfg, run_id="run_scoped", dump_id="dump_scoped", input_tables=input_tables)

            self.assertTrue((root / "runs" / "run_scoped" / "tables" / "indices.csv").is_file())
            self.assertTrue((root / "runs" / "run_scoped" / "passports" / "checksums.json").is_file())
            self.assertEqual(result["passport_outputs"]["checksums"], str(root / "runs" / "run_scoped" / "passports" / "checksums.json"))

    def test_recalculate_writes_pipeline_summary_before_archive_and_report(self) -> None:
        events: list[str] = []

        def fake_run_compute(*args: object, **kwargs: object) -> dict[str, object]:
            events.append("compute")
            return {"input_tables": {}, "input_table_checksums": {}}

        def fake_summary(*args: object, **kwargs: object) -> None:
            events.append("summary")

        def fake_archive(*args: object, **kwargs: object) -> dict[str, object]:
            events.append("archive")
            self.assertEqual(events, ["compute", "summary", "archive"])
            return {"run_id": "run_order", "dump_id": "dump_order"}

        def fake_report(*args: object, **kwargs: object) -> dict[str, object]:
            events.append("report")
            self.assertEqual(events, ["compute", "summary", "archive", "report"])
            return {"status": "ok"}

        with (
            patch.object(pipeline, "resolve_dump_tables", return_value={"works": Path("works.parquet"), "authorships": Path("authorships.parquet"), "work_topics": Path("work_topics.parquet")}),
            patch.object(pipeline, "_run_compute", side_effect=fake_run_compute),
            patch.object(pipeline, "_write_pipeline_summary", side_effect=fake_summary),
            patch.object(pipeline, "_archive_run_artifacts", side_effect=fake_archive),
            patch.object(pipeline.reports, "build_report_bundle", side_effect=fake_report),
        ):
            pipeline.recalculate(
                {
                    "run_id": "run_order",
                    "dump_id": "dump_order",
                    "analysis_eligibility": {"status": "final", "allowed_for_final_analysis": True},
                    "entity_level": "subfield",
                    "entity_id_short": "1706",
                    "entity_display_name": "Computer Science Applications",
                }
            )

        self.assertEqual(events, ["compute", "summary", "archive", "report"])

    def test_jobs_dispatch_passes_current_run_id_to_analysis_action(self) -> None:
        captured: dict[str, dict[str, object]] = {}

        def fake_recalculate(payload: dict[str, object]) -> dict[str, object]:
            captured["recalculate"] = payload
            return {"status": "ok"}

        with patch.object(pipeline, "recalculate", side_effect=fake_recalculate):
            jobs._dispatch("run_scope", "recalculate", {"dump_id": "dump_scope", "unknown_extra": "drop-me"})

        self.assertEqual(captured["recalculate"]["run_id"], "run_scope")
        self.assertEqual(captured["recalculate"]["dump_id"], "dump_scope")
        self.assertNotIn("unknown_extra", captured["recalculate"])

    def test_archive_does_not_overwrite_existing_dump_manifest_on_recalculate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dump_dir = root / "dumps" / "dump_keep"
            dump_dir.mkdir(parents=True)
            original = {"dump_id": "dump_keep", "source_mode": "openalex_cli", "raw_jsonl_sha256": "original-sha"}
            (dump_dir / "dump_manifest.json").write_text(json.dumps(original), encoding="utf-8")
            cfg = SimpleNamespace(slice_name="slice_keep")

            with patch.object(pipeline, "DATA", root):
                archive = pipeline._archive_run_artifacts(
                    cfg,
                    {
                        "run_id": "run_recalc",
                        "dump_id": "dump_keep",
                        "analysis_eligibility": {"status": "final", "allowed_for_final_analysis": True},
                        "input_tables": {},
                        "input_table_checksums": {},
                    },
                )

            kept = json.loads((dump_dir / "dump_manifest.json").read_text(encoding="utf-8"))
            recovered_path = dump_dir / "dump_manifest_recovered.json"

        self.assertEqual(kept, original)
        self.assertFalse(recovered_path.exists())
        self.assertEqual(archive["dump_id"], "dump_keep")

    def test_active_context_helper_roundtrips_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            written = artifact_context.write_active_context(
                run_id="run_active",
                dump_id="dump_active",
                source="test",
                data_dir=root,
                extra={"note": "ok"},
            )
            read_back = artifact_context.read_active_context(data_dir=root)

        self.assertEqual(written["active_run_id"], "run_active")
        self.assertEqual(read_back["active_dump_id"], "dump_active")
        self.assertEqual(read_back["source"], "test")
        self.assertEqual(read_back["note"], "ok")
        self.assertIn("updated_at_utc", read_back)

    def test_archive_writes_active_context_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = SimpleNamespace(slice_name="slice_active")
            with patch.object(pipeline, "DATA", root):
                archive = pipeline._archive_run_artifacts(
                    cfg,
                    {
                        "run_id": "run_active",
                        "dump_id": "dump_active",
                        "active_context_source": "test_archive",
                        "analysis_eligibility": {
                            "status": "dev_only_not_for_final_analysis",
                            "allowed_for_final_analysis": False,
                        },
                        "input_tables": {},
                        "input_table_checksums": {},
                    },
                )
                active = artifact_context.read_active_context(data_dir=root)

        self.assertEqual(archive["active_context"]["active_run_id"], "run_active")
        self.assertEqual(active["active_run_id"], "run_active")
        self.assertEqual(active["active_dump_id"], "dump_active")
        self.assertEqual(active["source"], "test_archive")
        self.assertEqual(active["run_dir"], str(root / "runs" / "run_active"))
        self.assertEqual(active["analysis_eligibility_status"], "dev_only_not_for_final_analysis")
        self.assertEqual(active["allowed_for_final_analysis"], False)

    def test_archive_uses_scoped_outputs_without_global_table_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            global_tables = root / "global"
            global_tables.mkdir()
            global_author_work = global_tables / "author_work.parquet"
            global_author_work.write_text("global author_work", encoding="utf-8")
            global_passports = root / "passports"
            global_passports.mkdir()
            (global_passports / "slice_passport.json").write_text(json.dumps({"source": "global"}), encoding="utf-8")
            (global_passports / "calculation_passport.json").write_text(json.dumps({"source": "global"}), encoding="utf-8")
            (global_passports / "checksums.json").write_text(json.dumps({"source": "global"}), encoding="utf-8")

            scoped_inputs = root / "scoped_inputs"
            scoped_outputs = root / "scoped_outputs"
            scoped_inputs.mkdir()
            (scoped_outputs / "tables").mkdir(parents=True)
            input_tables: dict[str, dict[str, object]] = {}
            for name in ("works", "authorships", "work_topics"):
                path = scoped_inputs / f"{name}.parquet"
                path.write_text(f"scoped {name}", encoding="utf-8")
                input_tables[name] = {"path": str(path), "sha256": f"{name}-sha", "bytes": path.stat().st_size}

            run_table_outputs: dict[str, str] = {}
            for name in ("author_work", "indices", "ratings"):
                path = scoped_outputs / "tables" / f"{name}.csv"
                path.write_text(f"{name}\nscoped\n", encoding="utf-8")
                run_table_outputs[name] = str(path)

            cfg = SimpleNamespace(slice_name="slice_scoped")
            with patch.object(pipeline, "DATA", root):
                archive = pipeline._archive_run_artifacts(
                    cfg,
                    {
                        "run_id": "run_scoped",
                        "dump_id": "dump_scoped",
                        "input_tables": input_tables,
                        "input_table_checksums": {"works": "works-sha"},
                        "run_table_outputs": run_table_outputs,
                    },
                )

            run_dir = root / "runs" / "run_scoped"
            dump_tables = root / "tables" / "dump_scoped"
            manifest = json.loads((run_dir / "metric_run.json").read_text(encoding="utf-8"))

            self.assertEqual((run_dir / "tables" / "author_work.csv").read_text(encoding="utf-8"), "author_work\nscoped\n")
            self.assertEqual((run_dir / "tables" / "indices.csv").read_text(encoding="utf-8"), "indices\nscoped\n")
            self.assertFalse((run_dir / "results").exists())
            self.assertEqual((dump_tables / "works.parquet").read_text(encoding="utf-8"), "scoped works")
            self.assertFalse((dump_tables / "author_work.parquet").exists())
            self.assertFalse((run_dir / "passports" / "slice_passport.json").exists())
            self.assertFalse((run_dir / "passports" / "calculation_passport.json").exists())
            self.assertFalse((run_dir / "passports" / "checksums.json").exists())
            self.assertIn("tables/author_work.csv", archive["copied"])
            self.assertIn("tables_by_dump/works.parquet", archive["copied"])
            self.assertNotIn("tables_by_dump/author_work.parquet", archive["copied"])
            self.assertEqual(manifest["run_table_outputs"]["indices"], run_table_outputs["indices"])
            self.assertNotIn("run_result_outputs", manifest)
            self.assertEqual(archive["active_context"]["active_run_id"], "run_scoped")

    def test_archive_records_direct_run_passport_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_passports = root / "runs" / "run_passports" / "passports"
            run_passports.mkdir(parents=True)
            passport_outputs: dict[str, str] = {}
            for name, filename in {
                "slice_passport": "slice_passport.json",
                "calculation_passport": "calculation_passport.json",
                "checksums": "checksums.json",
            }.items():
                path = run_passports / filename
                path.write_text(json.dumps({"name": name}), encoding="utf-8")
                passport_outputs[name] = str(path)

            cfg = SimpleNamespace(slice_name="slice_passports")
            with patch.object(pipeline, "DATA", root):
                archive = pipeline._archive_run_artifacts(
                    cfg,
                    {
                        "run_id": "run_passports",
                        "dump_id": "dump_passports",
                        "input_tables": {},
                        "input_table_checksums": {},
                        "passport_outputs": passport_outputs,
                    },
                )
                manifest = json.loads((root / "runs" / "run_passports" / "metric_run.json").read_text(encoding="utf-8"))

            self.assertEqual(archive["copied"]["passports/slice_passport.json"], str(run_passports / "slice_passport.json"))
            self.assertEqual(archive["copied"]["passports/calculation_passport.json"], str(run_passports / "calculation_passport.json"))
            self.assertEqual(archive["copied"]["passports/checksums.json"], str(run_passports / "checksums.json"))
            self.assertEqual(manifest["passport_outputs"]["slice_passport"], passport_outputs["slice_passport"])

    def test_archive_copies_fetch_meta_from_scoped_dump_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dump_dir = root / "dumps" / "dump_fetch"
            dump_dir.mkdir(parents=True)
            stale = root / "passports" / "fetch_meta.json"
            stale.parent.mkdir(parents=True)
            stale.write_text(json.dumps({"source": "stale"}), encoding="utf-8")
            scoped = dump_dir / "fetch_meta.json"
            scoped.write_text(json.dumps({"source": "scoped"}), encoding="utf-8")

            cfg = SimpleNamespace(slice_name="slice_fetch")
            with patch.object(pipeline, "DATA", root):
                archive = pipeline._archive_run_artifacts(
                    cfg,
                    {
                        "run_id": "run_fetch",
                        "dump_id": "dump_fetch",
                        "fetch_meta": str(scoped),
                        "input_tables": {},
                        "input_table_checksums": {},
                    },
                )

            run_fetch_meta = root / "runs" / "run_fetch" / "passports" / "fetch_meta.json"
            self.assertEqual(json.loads(run_fetch_meta.read_text(encoding="utf-8"))["source"], "scoped")
            self.assertEqual(archive["copied"]["passports/fetch_meta.json"], str(run_fetch_meta))

    def test_archive_preserves_unknown_active_context_eligibility_as_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = SimpleNamespace(slice_name="slice_unknown")
            with patch.object(pipeline, "DATA", root):
                archive = pipeline._archive_run_artifacts(
                    cfg,
                    {
                        "run_id": "run_unknown",
                        "dump_id": "dump_unknown",
                        "input_tables": {},
                        "input_table_checksums": {},
                    },
                )

        self.assertIsNone(archive["active_context"]["analysis_eligibility_status"])
        self.assertIsNone(archive["active_context"]["allowed_for_final_analysis"])

    def test_run_scoped_report_does_not_fallback_to_global_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            global_quality = root / "passports" / "quality_report.json"
            global_quality.parent.mkdir(parents=True)
            global_quality.write_text(json.dumps({"quality_counts": {"global_only": 1}}), encoding="utf-8")

            with (
                patch.object(reports, "DATA", root),
                patch.object(warehouse, "DATA", root),
            ):
                bundle = reports.build_report_bundle(run_id="run_missing", dump_id="dump_missing")

        self.assertEqual(bundle["status"], "incomplete_run_artifacts")
        self.assertEqual(bundle["schema"], "report_bundle")
        self.assertIn("pipeline", bundle["missing_artifacts"])
        self.assertIn("quality", bundle["missing_artifacts"])
        self.assertNotIn("quality_report", bundle)

    def test_report_bundle_json_rebuilds_instead_of_reading_cached_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "runs" / "run_a"
            run_dir.mkdir(parents=True)
            (run_dir / "metric_run.json").write_text(json.dumps({"run_id": "run_a", "dump_id": "dump_a"}), encoding="utf-8")
            scope = reports._report_scope(
                run_id="run_a",
                dump_id="dump_a",
                filters={},
                cohort_id="",
                cohort_checksum="",
                cohort_n_authors=0,
                metric="islv",
                fraction_mode="strict_authors_count",
                limit=50,
            )
            report_path = run_dir / "reports" / f"report_{scope['report_scope_hash']}.json"
            report_path.parent.mkdir(parents=True)
            report_path.write_text(json.dumps({"status": "ok", "run_id": "run_a", "dump_id": "dump_b"}), encoding="utf-8")
            rebuilt = {"schema": "report_bundle", "status": "ok", "run_id": "run_a", "dump_id": "dump_a", "rebuilt": True}

            with (
                patch.object(reports, "DATA", root),
                patch.object(reports, "build_report_bundle", return_value=rebuilt) as build,
            ):
                payload = reports.report_bundle_json(run_id="run_a")

        self.assertTrue(payload["rebuilt"])
        build.assert_called_once()

    def test_report_bundle_json_ignores_existing_report_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = reports._report_scope(
                run_id="run_a",
                dump_id="dump_a",
                filters={"country_code": "RU"},
                cohort_id="",
                cohort_checksum="",
                cohort_n_authors=0,
                metric="h",
                fraction_mode="integer",
                limit=50,
            )
            cached_path = root / "runs" / "run_a" / "reports" / f"report_{scope['report_scope_hash']}.json"
            cached_path.parent.mkdir(parents=True)
            cached_path.write_text(
                json.dumps({
                    "schema": "report_bundle",
                    "status": "ok",
                    "run_id": "run_a",
                    "dump_id": "dump_a",
                    "report_scope": scope,
                    "exports": {},
                }),
                encoding="utf-8",
            )
            rebuilt = {"schema": "report_bundle", "status": "ok", "run_id": "run_a", "dump_id": "dump_a", "rebuilt": True}

            with (
                patch.object(reports, "DATA", root),
                patch.object(warehouse, "resolve_analysis_scope", return_value={"run_id": "run_a", "dump_id": "dump_a"}),
                patch.object(reports, "build_report_bundle", return_value=rebuilt) as build,
            ):
                payload = reports.report_bundle_json(
                    run_id="run_a",
                    dump_id="dump_a",
                    metric="h",
                    fraction_mode="integer",
                    filters={"country_code": "RU"},
                )

        self.assertTrue(payload["rebuilt"])
        build.assert_called_once()

    def test_report_build_forwards_filters_to_metric_ranking_and_scopes_cache(self) -> None:
        captured: dict[str, object] = {}

        def fake_ranking(fraction_mode: str, metric: str, filters: dict[str, str], **kwargs: object) -> dict[str, object]:
            captured["fraction_mode"] = fraction_mode
            captured["metric"] = metric
            captured["filters"] = filters
            captured["kwargs"] = kwargs
            return {"fields": ["author_id", "h"], "rows": [{"author_id": "https://openalex.org/A1", "h": 3}], "total": 1, "dump_id": "dump_a"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(reports, "DATA", root),
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "resolve_analysis_scope", return_value={"run_id": "run_a", "dump_id": "dump_a"}),
                patch.object(reports, "_run_report_artifacts", return_value={
                    "pipeline": {"current_slice": {"slice_id": "slice_a"}},
                    "quality": {"raw_works": 1},
                    "checksums": {"sha256_manifest": "checksums.json"},
                    "slice_passport": {"slice_id": "slice_a"},
                    "calculation_passport": {"dump_id": "dump_a"},
                }),
                patch.object(warehouse, "metric_ranking", side_effect=fake_ranking),
                patch.object(warehouse, "metric_distribution", return_value={"rows": [], "dump_id": "dump_a"}),
                patch.object(warehouse, "read_json_doc", return_value={}),
                patch.object(warehouse, "count_rows", return_value=1),
            ):
                first = reports.build_report_bundle(
                    metric="h",
                    fraction_mode="integer",
                    run_id="run_a",
                    dump_id="dump_a",
                    filters={"country_code": "RU", "filter_mode": "keyword", "keyword_id": "https://openalex.org/K1"},
                    limit=25,
                )
                second = reports.build_report_bundle(
                    metric="h",
                    fraction_mode="integer",
                    run_id="run_a",
                    dump_id="dump_a",
                    filters={"country_code": "DE", "filter_mode": "keyword", "keyword_id": "https://openalex.org/K1"},
                    limit=25,
                )

        self.assertEqual(captured["filters"], {"country_code": "DE", "filter_mode": "keyword", "keyword_id": "https://openalex.org/K1"})
        self.assertEqual(captured["kwargs"], {"limit": 25, "max_limit": 500, "run_id": "run_a", "dump_id": "dump_a", "author_ids": None})
        self.assertNotEqual(first["report_scope"]["report_scope_hash"], second["report_scope"]["report_scope_hash"])
        self.assertIn("country_code=RU", first["exports"]["ranking_csv"])

    def test_report_with_cohort_id_limits_rank_table_to_cohort_authors(self) -> None:
        captured: dict[str, object] = {}

        def fake_ranking(fraction_mode: str, metric: str, filters: dict[str, str], **kwargs: object) -> dict[str, object]:
            captured["filters"] = filters
            captured["kwargs"] = kwargs
            return {"fields": ["author_id", "h"], "rows": [{"author_id": "https://openalex.org/A2", "h": 4}], "total": 1, "dump_id": "dump_a"}

        cohort_ctx = {
            "cohort": {"cohort_id": "cohort_a", "checksum": "sha-a", "n_authors": 1, "source": "top_n", "metric": "h", "fraction_mode": "integer"},
            "author_ids": {"https://openalex.org/A2"},
            "run_id": "run_a",
            "dump_id": "dump_a",
            "fraction_mode": "integer",
            "filters": {"country_code": "RU"},
            "analysis_filters": {"country_code": "RU"},
            "membership_filters": {"country_code": "RU"},
            "filter_policy": "membership",
            "resolved_filter_mode": "membership_filters",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(reports, "DATA", root),
                patch.object(warehouse, "DATA", root),
                patch.object(reports.cohorts, "resolve_cohort_context", return_value=cohort_ctx),
                patch.object(warehouse, "resolve_analysis_scope", return_value={"run_id": "run_a", "dump_id": "dump_a"}),
                patch.object(reports, "_run_report_artifacts", return_value={
                    "pipeline": {"current_slice": {"slice_id": "slice_a"}},
                    "quality": {"raw_works": 1},
                    "checksums": {"sha256_manifest": "checksums.json"},
                    "slice_passport": {"slice_id": "slice_a"},
                    "calculation_passport": {"dump_id": "dump_a"},
                }),
                patch.object(warehouse, "metric_ranking", side_effect=fake_ranking),
                patch.object(warehouse, "metric_distribution", return_value={"rows": [], "dump_id": "dump_a"}),
                patch.object(warehouse, "read_json_doc", return_value={}),
                patch.object(warehouse, "count_rows", return_value=1),
            ):
                bundle = reports.build_report_bundle(metric="h", fraction_mode="integer", run_id="run_a", dump_id="dump_a", cohort_id="cohort_a")

        self.assertEqual(captured["filters"], {"country_code": "RU"})
        self.assertEqual(captured["kwargs"]["author_ids"], {"https://openalex.org/A2"})
        self.assertEqual(bundle["cohort"]["checksum"], "sha-a")
        self.assertEqual(bundle["report_scope"]["cohort_checksum"], "sha-a")
        self.assertEqual(bundle["cohort_context"]["membership_filters"], {"country_code": "RU"})
        self.assertEqual(bundle["cohort_context"]["analysis_filters"], {"country_code": "RU"})

    def test_report_with_cohort_policy_none_keeps_empty_analysis_context(self) -> None:
        cohort = {
            "cohort_id": "cohort_a",
            "run_id": "run_a",
            "dump_id": "dump_a",
            "fraction_mode": "integer",
            "filters": {"country_code": "RU"},
            "author_ids": ["https://openalex.org/A2"],
            "checksum": "sha-a",
            "n_authors": 1,
            "source": "top_n",
            "metric": "h",
        }
        captured: dict[str, object] = {}

        def fake_ranking(fraction_mode: str, metric: str, filters: dict[str, str], **kwargs: object) -> dict[str, object]:
            captured["filters"] = filters
            captured["kwargs"] = kwargs
            return {"fields": ["author_id", "h"], "rows": [], "total": 0, "dump_id": "dump_a"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(cohorts, "COHORTS_DIR", root / "cohorts"),
                patch.object(reports, "DATA", root),
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "resolve_analysis_scope", return_value={"run_id": "run_a", "dump_id": "dump_a"}),
                patch.object(reports, "_run_report_artifacts", return_value={
                    "pipeline": {"current_slice": {"slice_id": "slice_a"}},
                    "quality": {"raw_works": 1},
                    "checksums": {"sha256_manifest": "checksums.json"},
                    "slice_passport": {"slice_id": "slice_a"},
                    "calculation_passport": {"dump_id": "dump_a"},
                }),
                patch.object(warehouse, "metric_ranking", side_effect=fake_ranking),
                patch.object(warehouse, "metric_distribution", return_value={"rows": [], "n": 0, "dump_id": "dump_a"}),
                patch.object(warehouse, "read_json_doc", return_value={}),
                patch.object(warehouse, "count_rows", return_value=1),
            ):
                cohorts._write(cohort)
                bundle = reports.build_report_bundle(
                    metric="h",
                    fraction_mode="integer",
                    run_id="run_a",
                    dump_id="dump_a",
                    filters={"country_code": "DE"},
                    cohort_id="cohort_a",
                    cohort_filter_policy="none",
                )

        self.assertEqual(bundle["schema"], "report_bundle")
        self.assertEqual(captured["filters"], {})
        self.assertEqual(bundle["filters"], {})
        self.assertEqual(bundle["report_scope"]["schema"], "report_scope")
        self.assertEqual(bundle["report_scope"]["filters"], {})
        self.assertEqual(bundle["report_scope"]["cohort_filter_policy"], "none")
        self.assertEqual(bundle["report_scope"]["cohort_membership_filters"], {"country_code": "RU"})
        self.assertEqual(bundle["cohort_context"]["analysis_filters"], {})
        self.assertEqual(bundle["cohort_context"]["membership_filters"], {"country_code": "RU"})
        self.assertEqual(bundle["cohort_context"]["filter_policy"], "none")
        self.assertEqual(bundle["cohort_context"]["resolved_filter_mode"], "no_analysis_filters")

    def test_report_with_cohort_policy_current_empty_filters_keeps_empty_analysis_context(self) -> None:
        cohort = {
            "cohort_id": "cohort_a",
            "run_id": "run_a",
            "dump_id": "dump_a",
            "fraction_mode": "integer",
            "filters": {"country_code": "RU"},
            "author_ids": ["https://openalex.org/A2"],
            "checksum": "sha-a",
            "n_authors": 1,
            "source": "top_n",
            "metric": "h",
        }
        captured: dict[str, object] = {}

        def fake_ranking(fraction_mode: str, metric: str, filters: dict[str, str], **kwargs: object) -> dict[str, object]:
            captured["filters"] = filters
            return {"fields": ["author_id", "h"], "rows": [], "total": 0, "dump_id": "dump_a"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(cohorts, "COHORTS_DIR", root / "cohorts"),
                patch.object(reports, "DATA", root),
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "resolve_analysis_scope", return_value={"run_id": "run_a", "dump_id": "dump_a"}),
                patch.object(reports, "_run_report_artifacts", return_value={
                    "pipeline": {"current_slice": {"slice_id": "slice_a"}},
                    "quality": {"raw_works": 1},
                    "checksums": {"sha256_manifest": "checksums.json"},
                    "slice_passport": {"slice_id": "slice_a"},
                    "calculation_passport": {"dump_id": "dump_a"},
                }),
                patch.object(warehouse, "metric_ranking", side_effect=fake_ranking),
                patch.object(warehouse, "metric_distribution", return_value={"rows": [], "n": 0, "dump_id": "dump_a"}),
                patch.object(warehouse, "read_json_doc", return_value={}),
                patch.object(warehouse, "count_rows", return_value=1),
            ):
                cohorts._write(cohort)
                bundle = reports.build_report_bundle(
                    metric="h",
                    fraction_mode="integer",
                    run_id="run_a",
                    dump_id="dump_a",
                    filters={},
                    cohort_id="cohort_a",
                    cohort_filter_policy="current",
                )

        self.assertEqual(captured["filters"], {})
        self.assertEqual(bundle["filters"], {})
        self.assertEqual(bundle["report_scope"]["cohort_filter_policy"], "current")
        self.assertEqual(bundle["report_scope"]["cohort_membership_filters"], {"country_code": "RU"})
        self.assertEqual(bundle["cohort_context"]["analysis_filters"], {})
        self.assertEqual(bundle["cohort_context"]["membership_filters"], {"country_code": "RU"})
        self.assertEqual(bundle["cohort_context"]["filter_policy"], "current")
        self.assertEqual(bundle["cohort_context"]["resolved_filter_mode"], "no_analysis_filters")

    def test_report_bundle_includes_scientometric_analysis_and_exports(self) -> None:
        captured: dict[str, object] = {}

        def fake_scientometrics(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {
                "schema": "scientometric_analysis",
                "scope": {
                    "run_id": kwargs["run_id"],
                    "dump_id": kwargs["dump_id"],
                    "baseline_metric": kwargs["baseline_metric"],
                    "rank_top_n": kwargs["top_n"],
                },
                "findings": [
                    {
                        "id": "heavy_tail:c",
                        "type": "heavy_tail_distribution",
                        "metric": "c",
                        "severity": "high",
                        "evidence": {"skewness": 2.5},
                        "text": "Метрика C имеет тяжелый хвост.",
                        "recommendation": "Использовать log1p.",
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(reports, "DATA", root),
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "resolve_analysis_scope", return_value={"run_id": "run_a", "dump_id": "dump_a"}),
                patch.object(reports, "_run_report_artifacts", return_value={
                    "pipeline": {"current_slice": {"slice_id": "slice_a"}},
                    "quality": {"raw_works": 1},
                    "checksums": {"sha256_manifest": "checksums.json"},
                    "slice_passport": {"slice_id": "slice_a"},
                    "calculation_passport": {"dump_id": "dump_a"},
                }),
                patch.object(warehouse, "metric_ranking", return_value={"fields": ["author_id", "h"], "rows": [], "total": 0, "dump_id": "dump_a"}),
                patch.object(warehouse, "metric_distribution", return_value={"rows": [], "dump_id": "dump_a"}),
                patch.object(warehouse, "read_json_doc", return_value={}),
                patch.object(warehouse, "count_rows", return_value=1),
                patch.object(reports.scientometrics, "build_scientometric_analysis", side_effect=fake_scientometrics),
            ):
                bundle = reports.build_report_bundle(
                    metric="h",
                    fraction_mode="integer",
                    run_id="run_a",
                    dump_id="dump_a",
                    filters={"country_code": "RU"},
                    scientometric_metrics="h,g,islv",
                    baseline_metric="g",
                    rank_top_n=25,
                )

        self.assertEqual(bundle["scientometric_analysis"]["schema"], "scientometric_analysis")
        self.assertEqual(bundle["scientometric_analysis"]["findings"][0]["id"], "heavy_tail:c")
        self.assertEqual(bundle["schema"], "report_bundle")
        self.assertEqual(bundle["report_scope"]["schema"], "report_scope")
        self.assertIn("checksums", bundle)
        self.assertIn("scientometrics_findings_csv", bundle["exports"])
        self.assertIn("scientometrics_conclusion_md", bundle["exports"])
        self.assertNotIn("statistics", bundle)
        self.assertNotIn("stability_" + "report", bundle)
        self.assertNotIn("metric_" + "summary", bundle)
        self.assertNotIn("run_" + "global_" + "stats", bundle)
        self.assertNotIn("top_" + "overlap", bundle)
        self.assertEqual(captured["metrics"], ["h", "g", "islv"])
        self.assertEqual(captured["baseline_metric"], "g")
        self.assertEqual(captured["top_n"], 25)
        self.assertEqual(captured["filters"], {"country_code": "RU"})
        self.assertEqual(bundle["report_scope"]["scientometric_metrics"], ["h", "g", "islv"])
        self.assertEqual(bundle["report_scope"]["scientometric_analysis_schema"], reports.scientometrics.SCIENTOMETRIC_ANALYSIS_SCHEMA)
        self.assertEqual(bundle["report_scope"]["scientometric_findings_schema"], reports.scientometrics.SCIENTOMETRIC_FINDINGS_SCHEMA)
        self.assertEqual(bundle["report_scope"]["scientometric_conclusion_schema"], reports.scientometrics.SCIENTOMETRIC_CONCLUSION_SCHEMA)
        self.assertEqual(bundle["report_scope"]["baseline_metric"], "g")
        self.assertEqual(bundle["report_scope"]["rank_top_n"], 25)
        self.assertIn("metrics=h%2Cg%2Cislv", bundle["exports"]["scientometrics_json"])
        self.assertIn("baseline_metric=g", bundle["exports"]["scientometrics_correlations_csv"])
        self.assertIn("top_n=25", bundle["exports"]["scientometrics_rank_shifts_csv"])
        self.assertIn("largest-rank-shifts.csv", bundle["exports"]["scientometrics_largest_rank_shifts_csv"])
        self.assertIn("top-outliers.csv", bundle["exports"]["scientometrics_top_outliers_csv"])
        self.assertIn("findings.csv", bundle["exports"]["scientometrics_findings_csv"])
        self.assertIn("conclusion.md", bundle["exports"]["scientometrics_conclusion_md"])
        self.assertIn("/local-data/preview.csv", bundle["exports"]["local_indices_csv"])
        self.assertIn("kind=indices", bundle["exports"]["local_indices_csv"])
        self.assertIn("kind=works", bundle["exports"]["local_works_csv"])
        self.assertIn("kind=authorships", bundle["exports"]["local_authorships_csv"])
        self.assertIn("kind=work_topics", bundle["exports"]["local_work_topics_csv"])
        self.assertEqual(bundle["export_notes"]["scientometrics_rank_shifts_csv"], "Contains all rank deltas for every author present in both baseline and comparison metric ranks.")
        self.assertEqual(bundle["export_notes"]["scientometrics_findings_csv"], "Contains structured interpretation findings with evidence JSON for the selected scientometric analysis scope.")
        self.assertEqual(bundle["export_notes"]["scientometrics_conclusion_md"], "Contains the deterministic conclusion draft rendered as Markdown for the selected scientometric analysis scope.")

    def test_local_data_report_exports_require_explicit_scope(self) -> None:
        self.assertEqual(reports._local_data_csv_exports(), {})

        run_exports = reports._local_data_csv_exports(run_id="run_a")
        self.assertIn("run_id=run_a", run_exports["local_indices_csv"])
        self.assertIn("kind=work_topics", run_exports["local_work_topics_csv"])

        dump_exports = reports._local_data_csv_exports(dump_id="dump_a")
        self.assertIn("dump_id=dump_a", dump_exports["local_works_csv"])

    def test_empty_cohort_report_has_empty_rank_table(self) -> None:
        cohort_ctx = {
            "cohort": {"cohort_id": "cohort_empty", "checksum": "empty-sha", "n_authors": 0, "source": "manual", "metric": "h", "fraction_mode": "integer"},
            "author_ids": set(),
            "run_id": "run_a",
            "dump_id": "dump_a",
            "fraction_mode": "integer",
            "filters": {},
        }
        rows = [
            {"author_id": "https://openalex.org/A1", "author_display_name": "Author One", "h": 3, "p": 4, "c": 10},
            {"author_id": "https://openalex.org/A2", "author_display_name": "Author Two", "h": 2, "p": 3, "c": 7},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(reports, "DATA", root),
                patch.object(warehouse, "DATA", root),
                patch.object(reports.cohorts, "resolve_cohort_context", return_value=cohort_ctx),
                patch.object(warehouse, "resolve_analysis_scope", return_value={"run_id": "run_a", "dump_id": "dump_a"}),
                patch.object(reports, "_run_report_artifacts", return_value={
                    "pipeline": {"current_slice": {"slice_id": "slice_a"}},
                    "quality": {"raw_works": 1},
                    "checksums": {"sha256_manifest": "checksums.json"},
                    "slice_passport": {"slice_id": "slice_a"},
                    "calculation_passport": {"dump_id": "dump_a"},
                }),
                patch.object(warehouse, "filtered_indices", return_value=rows),
                patch.object(warehouse, "count_rows", return_value=1),
            ):
                bundle = reports.build_report_bundle(metric="h", fraction_mode="integer", run_id="run_a", dump_id="dump_a", cohort_id="cohort_empty")

        self.assertEqual(bundle["rank_table"]["rows"], [])
        self.assertEqual(bundle["rank_table"]["total"], 0)
        self.assertEqual(bundle["distribution"]["n"], 0)

    def test_cohort_author_metrics_export_uses_analysis_filters_and_context(self) -> None:
        cohort_ctx = {
            "cohort": {"cohort_id": "cohort_a", "checksum": "sha-a", "n_authors": 1, "source": "top_n", "metric": "h", "fraction_mode": "integer", "filters": {"country_code": "RU"}},
            "author_ids": {"https://openalex.org/A2"},
            "run_id": "run_a",
            "dump_id": "dump_a",
            "fraction_mode": "integer",
            "filters": {"country_code": "DE"},
            "analysis_filters": {"country_code": "DE"},
            "membership_filters": {"country_code": "RU"},
            "filter_policy": "current",
            "filter_mode": "analysis_override",
        }
        rows = [
            {"author_id": "https://openalex.org/A1", "author_display_name": "Author One", "h": 3, "p": 4, "c": 10, "islv": 10},
            {"author_id": "https://openalex.org/A2", "author_display_name": "Author Two", "h": 2, "p": 3, "c": 7, "islv": 20},
        ]
        captured: dict[str, object] = {}

        def fake_filtered(fraction_mode: str, filters: dict[str, str], **kwargs: object) -> list[dict[str, object]]:
            captured["fraction_mode"] = fraction_mode
            captured["filters"] = filters
            captured["kwargs"] = kwargs
            return rows

        with (
            patch.object(cohorts, "resolve_cohort_context", return_value=cohort_ctx),
                patch.object(warehouse, "filtered_indices", side_effect=fake_filtered),
            ):
            payload = cohorts.cohort_author_metrics("cohort_a", run_id="run_a", dump_id="dump_a", fraction_mode="integer", filters={"country_code": "DE"}, metric="islv")
            csv_data = cohorts.cohort_author_metrics_csv("cohort_a", run_id="run_a", dump_id="dump_a", fraction_mode="integer", filters={"country_code": "DE"}, metric="islv")

        self.assertEqual(captured["filters"], {"country_code": "DE"})
        self.assertEqual(captured["kwargs"], {"run_id": "run_a", "dump_id": "dump_a"})
        self.assertEqual(payload["sort_metric"], "islv")
        self.assertEqual(payload["rows"], [rows[1]])
        self.assertEqual(payload["cohort_context"]["filter_mode"], "analysis_override")
        self.assertEqual(payload["cohort_context"]["membership_filters"], {"country_code": "RU"})
        self.assertIn("Author Two", csv_data)
        self.assertNotIn("Author One", csv_data)

    def test_cohort_statistics_uses_analysis_scope(self) -> None:
        cohort_ctx = {
            "cohort": {"cohort_id": "cohort_a", "checksum": "sha-a", "n_authors": 1, "source": "top_n", "metric": "h", "fraction_mode": "integer", "filters": {"country_code": "RU"}},
            "author_ids": {"https://openalex.org/A2"},
            "run_id": "run_a",
            "dump_id": "dump_a",
            "fraction_mode": "integer",
            "filters": {"country_code": "DE"},
            "analysis_filters": {"country_code": "DE"},
            "membership_filters": {"country_code": "RU"},
            "filter_policy": "current",
            "filter_mode": "analysis_override",
        }
        rows = [
            {"author_id": "https://openalex.org/A1", "author_display_name": "Author One", "h": 3, "p": 4, "c": 10, "c_frac": 10, "cpp": 2, "i10": 1, "g": 3, "m_local": 1, "top1_share": 0.5, "islv": 10, "iupv": 20, "lrdi": 30},
            {"author_id": "https://openalex.org/A2", "author_display_name": "Author Two", "h": 2, "p": 3, "c": 7, "c_frac": 7, "cpp": 2.3, "i10": 0, "g": 2, "m_local": 1, "top1_share": 0.4, "islv": 20, "iupv": 30, "lrdi": 40},
        ]
        captured: dict[str, object] = {}

        def fake_filtered(fraction_mode: str, filters: dict[str, str], **kwargs: object) -> list[dict[str, object]]:
            captured["fraction_mode"] = fraction_mode
            captured["filters"] = filters
            captured["kwargs"] = kwargs
            return rows

        with (
            patch.object(cohorts, "resolve_cohort_context", return_value=cohort_ctx),
            patch.object(warehouse, "filtered_indices", side_effect=fake_filtered),
        ):
            stats = cohorts.cohort_statistics("cohort_a", run_id="run_a", dump_id="dump_a", fraction_mode="integer", filters={"country_code": "DE"})

        self.assertEqual(captured["filters"], {"country_code": "DE"})
        self.assertEqual(captured["kwargs"], {"run_id": "run_a", "dump_id": "dump_a"})
        self.assertEqual(stats["cohort_context"]["filter_mode"], "analysis_override")
        self.assertEqual(stats["cohort_context"]["filter_policy"], "current")
        self.assertEqual(stats["n_rows"], 1)
        self.assertEqual(stats["descriptive"]["h"]["mean"], 2.0)

    def test_report_scope_hash_changes_when_cohort_checksum_changes(self) -> None:
        first = reports._report_scope(run_id="run_a", dump_id="dump_a", filters={}, cohort_id="cohort_a", cohort_checksum="sha-a", cohort_n_authors=1, metric="h", fraction_mode="integer", limit=50)
        second = reports._report_scope(run_id="run_a", dump_id="dump_a", filters={}, cohort_id="cohort_a", cohort_checksum="sha-b", cohort_n_authors=1, metric="h", fraction_mode="integer", limit=50)
        third = reports._report_scope(
            run_id="run_a",
            dump_id="dump_a",
            filters={},
            cohort_id="cohort_a",
            cohort_checksum="sha-a",
            cohort_n_authors=1,
            cohort_membership_filters={"country_code": "RU"},
            metric="h",
            fraction_mode="integer",
            limit=50,
        )
        fourth = reports._report_scope(
            run_id="run_a",
            dump_id="dump_a",
            filters={},
            cohort_id="cohort_a",
            cohort_checksum="sha-a",
            cohort_n_authors=1,
            metric="h",
            fraction_mode="integer",
            limit=50,
            cohort_filter_policy="none",
        )
        self.assertNotEqual(first["report_scope_hash"], second["report_scope_hash"])
        self.assertNotEqual(first["report_scope_hash"], third["report_scope_hash"])
        self.assertNotEqual(first["report_scope_hash"], fourth["report_scope_hash"])
        self.assertEqual(third["cohort_membership_filters"], {"country_code": "RU"})
        self.assertEqual(fourth["cohort_filter_policy"], "none")

    def test_report_scope_hash_changes_when_scientometric_params_change(self) -> None:
        base = reports._report_scope(run_id="run_a", dump_id="dump_a", filters={}, cohort_id="", cohort_checksum="", cohort_n_authors=0, metric="h", fraction_mode="integer", limit=50, scientometric_metrics=["h", "g"], baseline_metric="h", rank_top_n=20)
        other_baseline = reports._report_scope(run_id="run_a", dump_id="dump_a", filters={}, cohort_id="", cohort_checksum="", cohort_n_authors=0, metric="h", fraction_mode="integer", limit=50, scientometric_metrics=["h", "g"], baseline_metric="g", rank_top_n=20)
        other_top_n = reports._report_scope(run_id="run_a", dump_id="dump_a", filters={}, cohort_id="", cohort_checksum="", cohort_n_authors=0, metric="h", fraction_mode="integer", limit=50, scientometric_metrics=["h", "g"], baseline_metric="h", rank_top_n=50)
        other_metrics = reports._report_scope(run_id="run_a", dump_id="dump_a", filters={}, cohort_id="", cohort_checksum="", cohort_n_authors=0, metric="h", fraction_mode="integer", limit=50, scientometric_metrics=["h", "g", "islv"], baseline_metric="h", rank_top_n=20)

        self.assertEqual(base["schema"], "report_scope")
        self.assertNotEqual(base["report_scope_hash"], other_baseline["report_scope_hash"])
        self.assertNotEqual(base["report_scope_hash"], other_top_n["report_scope_hash"])
        self.assertNotEqual(base["report_scope_hash"], other_metrics["report_scope_hash"])

    def test_report_build_requires_explicit_run_or_dump_for_final_report(self) -> None:
        bundle = reports.build_report_bundle(metric="h", fraction_mode="integer", filters={"country_code": "RU"})
        self.assertEqual(bundle["status"], "preview_not_reproducible")
        self.assertEqual(bundle["schema"], "report_bundle")
        self.assertNotIn("local_indices_csv", bundle.get("exports") or {})
        dump_only = reports.build_report_bundle(metric="h", fraction_mode="integer", dump_id="dump_a")
        self.assertEqual(dump_only["status"], "preview_not_reproducible")
        self.assertEqual(dump_only["schema"], "report_bundle")
        self.assertNotIn("local_indices_csv", dump_only.get("exports") or {})

    def test_report_bundle_json_without_run_does_not_return_global_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = reports._report_scope(
                run_id="",
                dump_id="",
                filters={"country_code": "RU"},
                cohort_id="",
                cohort_checksum="",
                cohort_n_authors=0,
                metric="h",
                fraction_mode="integer",
                limit=50,
            )
            cached_path = root / "results" / f"report_bundle_{scope['report_scope_hash']}.json"
            cached_path.parent.mkdir(parents=True)
            cached_path.write_text(json.dumps({"status": "ok", "dump_id": "stale"}), encoding="utf-8")

            with patch.object(reports, "DATA", root):
                payload = reports.report_bundle_json(metric="h", fraction_mode="integer", filters={"country_code": "RU"})

        self.assertEqual(payload["status"], "preview_not_reproducible")
        self.assertEqual(payload["dump_id"], "")

    def test_manual_cohort_requires_run_scope(self) -> None:
        with self.assertRaises(ValueError) as raised:
            cohorts.create_cohort({"source": "manual", "author_ids": ["https://openalex.org/A1"]})
        self.assertIn("run_id", str(raised.exception))

    def test_metric_filter_cohort_uses_all_matching_authors_not_top_n(self) -> None:
        rows = [
            {"author_id": f"https://openalex.org/A{idx}", "p": idx, "h": idx % 3, "islv": float(idx)}
            for idx in range(1, 8)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(warehouse, "resolve_analysis_scope", return_value={"run_id": "run_a", "dump_id": "dump_a"}),
                patch.object(warehouse, "filtered_indices", return_value=rows),
                patch.object(cohorts, "COHORTS_DIR", Path(tmp)),
            ):
                cohort = cohorts.create_cohort(
                    {
                        "source": "metric_filter",
                        "run_id": "run_a",
                        "dump_id": "dump_a",
                        "metric": "islv",
                        "fraction_mode": "integer",
                        "top_n": 2,
                        "min_publications": 3,
                        "min_h": 1,
                        "min_metric_value": 4,
                    }
                )

        self.assertEqual(cohort["source"], "metric_filter")
        self.assertIsNone(cohort["top_n"])
        self.assertEqual(cohort["author_ids"], ["https://openalex.org/A4", "https://openalex.org/A5", "https://openalex.org/A7"])
        self.assertEqual(cohort["n_authors"], 3)

    def test_resolve_cohort_context_filter_policy_is_explicit(self) -> None:
        cohort = {
            "cohort_id": "cohort_a",
            "run_id": "run_a",
            "dump_id": "dump_a",
            "fraction_mode": "integer",
            "filters": {"country_code": "RU"},
            "author_ids": ["https://openalex.org/A1"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(cohorts, "COHORTS_DIR", Path(tmp)):
                cohorts._write(cohort)

                default_ctx = cohorts.resolve_cohort_context("cohort_a", filters={"country_code": "DE"})
                membership = cohorts.resolve_cohort_context("cohort_a", filters={"country_code": "DE"}, filter_policy="membership")
                current = cohorts.resolve_cohort_context("cohort_a", filters={"country_code": "DE"}, filter_policy="current")
                current_empty = cohorts.resolve_cohort_context("cohort_a", filters={}, filter_policy="current")
                none = cohorts.resolve_cohort_context("cohort_a", filters={"country_code": "DE"}, filter_policy="none")
                current_empty_summary = cohorts.cohort_context_summary(current_empty)
                none_summary = cohorts.cohort_context_summary(none)
                with self.assertRaises(ValueError):
                    cohorts.resolve_cohort_context("cohort_a", filter_policy="surprise")

        self.assertEqual(default_ctx["filters"], {"country_code": "RU"})
        self.assertEqual(default_ctx["filter_policy"], "membership")
        self.assertEqual(membership["filters"], {"country_code": "RU"})
        self.assertEqual(membership["filter_policy"], "membership")
        self.assertEqual(membership["resolved_filter_mode"], "membership_filters")
        self.assertEqual(current["filters"], {"country_code": "DE"})
        self.assertEqual(current["filter_policy"], "current")
        self.assertEqual(current["resolved_filter_mode"], "analysis_override")
        self.assertEqual(current_empty["filters"], {})
        self.assertEqual(current_empty["resolved_filter_mode"], "no_analysis_filters")
        self.assertEqual(current_empty_summary["analysis_filters"], {})
        self.assertEqual(current_empty_summary["membership_filters"], {"country_code": "RU"})
        self.assertEqual(current_empty_summary["filter_policy"], "current")
        self.assertEqual(current_empty_summary["resolved_filter_mode"], "no_analysis_filters")
        self.assertEqual(none["filters"], {})
        self.assertEqual(none["filter_policy"], "none")
        self.assertEqual(none_summary["analysis_filters"], {})
        self.assertEqual(none_summary["membership_filters"], {"country_code": "RU"})
        self.assertEqual(none_summary["filter_policy"], "none")
        self.assertEqual(none_summary["resolved_filter_mode"], "no_analysis_filters")

    def test_cohort_filters_keep_slice_analysis_contract_fields(self) -> None:
        filters = cohorts._filters(
            {
                "filter_mode": "search",
                "keyword_id": "https://openalex.org/K1",
                "keyword_display_name": "decision support",
                "text_search_query": "ergodesign",
                "author_id": "https://openalex.org/A1",
                "author_display_name": "Author One",
                "author_orcid": "0000-0000-0000-0001",
                "doi": "10.123/example",
                "affiliation_mode": "historical",
                "source_id": "https://openalex.org/S1",
                "source_display_name": "Journal One",
            }
        )

        self.assertEqual(filters["filter_mode"], "search")
        self.assertEqual(filters["keyword_id"], "https://openalex.org/K1")
        self.assertEqual(filters["keyword_display_name"], "decision support")
        self.assertEqual(filters["text_search_query"], "ergodesign")
        self.assertEqual(filters["author_id"], "https://openalex.org/A1")
        self.assertEqual(filters["author_display_name"], "Author One")
        self.assertEqual(filters["author_orcid"], "0000-0000-0000-0001")
        self.assertEqual(filters["doi"], "10.123/example")
        self.assertEqual(filters["affiliation_mode"], "historical")
        self.assertEqual(filters["source_id"], "https://openalex.org/S1")
        self.assertEqual(filters["source_display_name"], "Journal One")

    def test_pipeline_summary_includes_analysis_eligibility(self) -> None:
        eligibility = {"status": "final", "allowed_for_final_analysis": True}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            global_summary = root / "passports" / "pipeline_summary.json"
            with patch.object(pipeline, "DATA", root):
                pipeline._write_pipeline_summary(
                    "recalculate",
                    pipeline._cfg({"entity_level": "subfield", "entity_id_short": "1706", "entity_display_name": "Computer Science Applications"}),
                    {"run_id": "run_summary", "analysis_eligibility": eligibility},
                )

            run_summary = root / "runs" / "run_summary" / "passports" / "pipeline_summary.json"
            captured = json.loads(run_summary.read_text(encoding="utf-8"))

        self.assertEqual(captured["analysis_eligibility"], eligibility)
        self.assertFalse(global_summary.exists())

    def test_pipeline_summary_without_run_does_not_write_global_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            global_summary = root / "passports" / "pipeline_summary.json"
            with patch.object(pipeline, "DATA", root):
                pipeline._write_pipeline_summary(
                    "fetch_slice_dump",
                    pipeline._cfg({"entity_level": "subfield", "entity_id_short": "1706", "entity_display_name": "Computer Science Applications"}),
                    {},
                )

        self.assertFalse(global_summary.exists())

    def test_final_local_import_requires_final_eligible_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "works.jsonl"
            raw.write_text(json.dumps(_work("W1")) + "\n", encoding="utf-8")
            profile = {"path": str(raw), "bytes": raw.stat().st_size, "sha256": "raw-sha"}

            with (
                patch.object(pipeline, "resolve_safe_path", return_value=raw),
                patch.object(pipeline, "file_profile", return_value=profile),
            ):
                with self.assertRaises(ValueError) as raised:
                    pipeline.import_local_file(
                        {
                            "source_path": str(raw),
                            "import_mode": "final_reproducible",
                            "entity_level": "subfield",
                            "entity_id_short": "1706",
                            "entity_display_name": "Computer Science Applications",
                        }
                    )

        self.assertIn("Финальный импорт", str(raised.exception))

    def test_slice_dump_catalog_indexes_final_eligibility_fields(self) -> None:
        passport = {
            "slice_id": "slice_catalog",
            "dump_id": "dump_catalog",
            "source_mode": "openalex_cli",
            "scientific_completeness": "complete",
            "allowed_for_final_analysis": True,
            "raw_jsonl": "/tmp/catalog.jsonl.gz",
            "records_expected": 12,
            "records_downloaded": 12,
            "bytes_written": 100,
            "raw_jsonl_sha256": "sha",
            "actual_vs_estimate_ratio": 1.2,
            "stop_reason": "cli_completed",
            "created_at_utc": "2026-01-01T00:00:00Z",
            "openalex_request": {"filter": "primary_topic.subfield.id:1706"},
            "signatures": {"estimate_signature": "estimate", "download_signature": "download"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(metadata_store, "DB_PATH", Path(tmp) / "metadata.sqlite"):
                metadata_store.record_slice_dump(passport)
                dumps = metadata_store.list_slice_dumps()

        self.assertEqual(dumps[0]["dump_id"], "dump_catalog")
        self.assertEqual(dumps[0]["source_mode"], "openalex_cli")
        self.assertEqual(dumps[0]["scientific_completeness"], "complete")
        self.assertEqual(dumps[0]["allowed_for_final_analysis"], True)
        self.assertEqual(dumps[0]["openalex_filter"], "primary_topic.subfield.id:1706")
        self.assertEqual(dumps[0]["estimate_signature"], "estimate")
        self.assertEqual(dumps[0]["download_signature"], "download")


def _work(short_id: str) -> dict[str, object]:
    return {
        "id": f"https://openalex.org/{short_id}",
        "display_name": short_id,
        "publication_year": 2020,
        "publication_date": "2020-01-01",
        "type": "article",
        "cited_by_count": 1,
        "authorships": [],
        "primary_topic": {},
    }


if __name__ == "__main__":
    unittest.main()
