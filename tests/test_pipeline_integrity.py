from __future__ import annotations

import sys
import json
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

from app.services import jobs, metadata_store, pipeline  # noqa: E402


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

    def test_run_table_path_uses_sanitized_run_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archived = root / "runabc" / "tables" / "works.csv"
            archived.parent.mkdir(parents=True)
            archived.write_text("work_id\nW1\n", encoding="utf-8")

            with patch.object(jobs, "RUNS_DIR", root):
                resolved = jobs._run_table_path("run/abc", "works")

        self.assertEqual(resolved, archived)

    def test_cli_origin_fetch_meta_keeps_dump_manifest_context(self) -> None:
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
                patch.object(pipeline, "_materialize_dump_tables", return_value={"works": raw, "authorships": raw, "work_topics": raw}),
                patch.object(pipeline, "_run_compute", return_value={"input_tables": {}, "input_table_checksums": {}}),
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

            fetch_meta = json.loads((root / "data/passports/fetch_meta.json").read_text(encoding="utf-8"))
            self.assertEqual(fetch_meta["source_type"], "openalex_cli_dump_import")
            self.assertEqual(fetch_meta["dump_id"], "dump_ctx")
            self.assertEqual(fetch_meta["openalex_filter"], "primary_topic.subfield.id:1706")
            self.assertEqual(fetch_meta["accepted_download_signature"], "download-ok")
            self.assertEqual(fetch_meta["analysis_eligibility"]["status"], "blocked_not_for_final_analysis")

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
        self.assertEqual(result["analysis_eligibility"]["allowed_for_final_analysis"], True)

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

    def test_recalculate_uses_requested_dump_tables_not_latest_view(self) -> None:
        captured: dict[str, object] = {}

        def fake_author_work_metrics(works_path: object, authorships_path: object, *args: object, **kwargs: object) -> list[dict[str, object]]:
            captured["works_path"] = works_path
            captured["authorships_path"] = authorships_path
            return []

        def fake_build_passports(*args: object, **kwargs: object) -> dict[str, object]:
            captured["passport_input_tables"] = kwargs.get("input_tables")
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dump_a = root / "tables" / "dump_A"
            dump_b = root / "tables" / "dump_B"
            latest = root / "parquet"
            for base in (dump_a, dump_b, latest):
                base.mkdir(parents=True)
                for table in ("works", "authorships", "work_topics"):
                    (base / f"{table}.parquet").write_text(f"{base.name}:{table}", encoding="utf-8")

            with (
                patch.object(pipeline, "DATA", root),
                patch.object(pipeline, "build_author_work_metrics", side_effect=fake_author_work_metrics),
                patch.object(pipeline, "compute_indices", return_value=[]),
                patch.object(pipeline, "build_ratings", return_value=[]),
                patch.object(pipeline, "analyze_stats", return_value={}),
                patch.object(pipeline, "analyze_theory", return_value={}),
                patch.object(pipeline, "_publish_latest_view", return_value=None),
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
        self.assertIn("works", captured["passport_input_tables"])
        self.assertEqual(captured["passport_input_tables"]["works"]["path"], str(dump_a / "works.parquet"))

    def test_pipeline_summary_includes_analysis_eligibility(self) -> None:
        captured: dict[str, object] = {}
        eligibility = {"status": "final", "allowed_for_final_analysis": True}

        def fake_write_json(path: object, doc: dict[str, object]) -> None:
            captured.update(doc)

        with patch.object(pipeline, "write_json", side_effect=fake_write_json):
            pipeline._write_pipeline_summary(
                "recalculate",
                pipeline._cfg({"entity_level": "subfield", "entity_id_short": "1706", "entity_display_name": "Computer Science Applications"}),
                {"analysis_eligibility": eligibility},
            )

        self.assertEqual(captured["analysis_eligibility"], eligibility)

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
