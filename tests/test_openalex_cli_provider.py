from __future__ import annotations

import gzip
import json
import sys
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

from app.providers import openalex_cli_provider  # noqa: E402
from app.providers.openalex_cli_provider import _pack_work_json_files  # noqa: E402
from openalex_dss.config import load_config, replace_config  # noqa: E402
from openalex_dss.io_utils import read_jsonl  # noqa: E402
from openalex_dss.openalex import cli_download_signature, corpus_signature  # noqa: E402


class OpenAlexCliProviderTests(unittest.TestCase):
    def test_pack_work_files_accepts_json_jsonl_gz_arrays_and_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = root / "files"
            files.mkdir()
            (files / "one.json").write_text(json.dumps(_work("W1")), encoding="utf-8")
            (files / "array.json").write_text(json.dumps([_work("W2"), {"id": "https://openalex.org/A1"}]), encoding="utf-8")
            (files / "results.json").write_text(json.dumps({"results": [_work("W3")]}), encoding="utf-8")
            (files / "lines.jsonl").write_text(json.dumps(_work("W4")) + "\n", encoding="utf-8")
            with gzip.open(files / "lines.jsonl.gz", "wt", encoding="utf-8") as handle:
                handle.write(json.dumps(_work("W5")) + "\n")

            raw = root / "works.jsonl.gz"
            records, manifest = _pack_work_json_files(files, raw)

            self.assertEqual(records, 5)
            self.assertEqual(len(read_jsonl(raw)), 5)
            self.assertEqual(sum(item["records"] for item in manifest), 5)

    def test_pack_work_files_fails_on_malformed_json_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = root / "files"
            files.mkdir()
            (files / "broken.json").write_text("{not-json", encoding="utf-8")

            with self.assertRaises(ValueError):
                _pack_work_json_files(files, root / "works.jsonl.gz")

    def test_pack_work_files_writes_failed_manifest_before_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = root / "files"
            files.mkdir()
            (files / "broken.json").write_text("{not-json", encoding="utf-8")
            manifest_path = root / "files_manifest.json"

            with self.assertRaises(ValueError):
                _pack_work_json_files(files, root / "works.jsonl.gz", manifest_path=manifest_path)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["files"][0]["status"], "failed")

    def test_remote_cli_download_omits_api_key_when_blank(self) -> None:
        cfg = replace_config(
            load_config(ROOT / "config/slice.yaml"),
            slice_name="cli_without_key",
            filter_mode="primary_topic",
            entity_level="subfield",
            entity_id_short="1706",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            commands: list[list[str]] = []

            def fake_run(command: list[str], **_: object) -> SimpleNamespace:
                if command[1:] == ["--version"]:
                    return SimpleNamespace(stdout="openalex 0.test", stderr="", returncode=0)
                return SimpleNamespace(stdout="", stderr="", returncode=0)

            def fake_cli_download(command: list[str], *, files_dir: Path, **_: object) -> SimpleNamespace:
                commands.append(command)
                files_dir.mkdir(parents=True, exist_ok=True)
                (files_dir / "W1.json").write_text(json.dumps(_work("W1")), encoding="utf-8")
                return SimpleNamespace(returncode=0)

            with (
                patch.object(openalex_cli_provider, "cli_status", return_value={"available": True, "executable": "/tmp/openalex"}),
                patch.object(openalex_cli_provider.subprocess, "run", side_effect=fake_run),
                patch.object(openalex_cli_provider, "_run_cli_download", side_effect=fake_cli_download),
            ):
                manifest = openalex_cli_provider.download_works_metadata(
                    cfg,
                    api_key="",
                    out_dir=root / "raw",
                    estimate={
                        "estimate_signature": corpus_signature(cfg),
                        "download_signature": cli_download_signature(cfg),
                        "estimate_count": 1,
                    },
                )

        self.assertFalse(manifest["used_api_key"])
        self.assertNotIn("--api-key", commands[0])

    def test_cli_dump_without_accepted_signatures_is_not_final_analysis_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = replace_config(
                load_config(ROOT / "config/slice.yaml"),
                slice_name="cli_no_accept",
                filter_mode="primary_topic",
                entity_level="subfield",
                entity_id_short="1706",
            )

            commands: list[list[str]] = []

            def fake_run(command: list[str], **_: object) -> SimpleNamespace:
                if command[1:] == ["--version"]:
                    return SimpleNamespace(stdout="openalex 0.test", stderr="", returncode=0)
                return SimpleNamespace(stdout="", stderr="", returncode=0)

            def fake_cli_download(command: list[str], *, files_dir: Path, **_: object) -> SimpleNamespace:
                commands.append(command)
                files_dir.mkdir(parents=True, exist_ok=True)
                (files_dir / "W1.json").write_text(json.dumps(_work("W1")), encoding="utf-8")
                return SimpleNamespace(returncode=0)

            with (
                patch.object(openalex_cli_provider, "cli_status", return_value={"available": True, "executable": "/tmp/openalex"}),
                patch.object(openalex_cli_provider.subprocess, "run", side_effect=fake_run),
                patch.object(openalex_cli_provider, "_run_cli_download", side_effect=fake_cli_download),
            ):
                manifest = openalex_cli_provider.download_works_metadata(
                    cfg,
                    api_key="test-key",
                    out_dir=root / "raw",
                    estimate={
                        "estimate_signature": corpus_signature(cfg),
                        "download_signature": cli_download_signature(cfg),
                        "estimate_count": 1,
                    },
                )

            self.assertFalse(manifest["allowed_for_final_analysis"])
            self.assertTrue(manifest["used_api_key"])
            self.assertFalse(manifest["signatures"]["accepted_estimate_signature_verified"])
            self.assertFalse(manifest["signatures"]["download_signature_verified"])
            self.assertIn("--api-key", commands[0])

    def test_cancelled_cli_download_packs_partial_dump(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = replace_config(
                load_config(ROOT / "config/slice.yaml"),
                slice_name="cli_partial",
                filter_mode="primary_topic",
                entity_level="subfield",
                entity_id_short="1706",
            )

            def fake_run(command: list[str], **_: object) -> SimpleNamespace:
                if command[1:] == ["--version"]:
                    return SimpleNamespace(stdout="openalex 0.test", stderr="", returncode=0)
                return SimpleNamespace(stdout="", stderr="", returncode=0)

            def fake_cli_download(command: list[str], *, files_dir: Path, **_: object) -> tuple[SimpleNamespace, str]:
                files_dir.mkdir(parents=True, exist_ok=True)
                (files_dir / "W1.json").write_text(json.dumps(_work("W1")), encoding="utf-8")
                return SimpleNamespace(returncode=-15), "user_cancelled"

            with (
                patch.object(openalex_cli_provider, "cli_status", return_value={"available": True, "executable": "/tmp/openalex"}),
                patch.object(openalex_cli_provider.subprocess, "run", side_effect=fake_run),
                patch.object(openalex_cli_provider, "_run_cli_download", side_effect=fake_cli_download),
            ):
                manifest = openalex_cli_provider.download_works_metadata(
                    cfg,
                    api_key="",
                    out_dir=root / "raw",
                    estimate={
                        "estimate_signature": corpus_signature(cfg),
                        "download_signature": cli_download_signature(cfg),
                        "estimate_count": 10,
                    },
                )

        self.assertEqual(manifest["stop_reason"], "user_cancelled")
        self.assertEqual(manifest["scientific_completeness"], "partial")
        self.assertFalse(manifest["allowed_for_final_analysis"])
        self.assertTrue(manifest["usable_for_exploratory_analysis"])

    def test_malformed_cli_output_writes_failed_dump_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = replace_config(
                load_config(ROOT / "config/slice.yaml"),
                slice_name="cli_broken",
                filter_mode="primary_topic",
                entity_level="subfield",
                entity_id_short="1706",
            )

            def fake_run(command: list[str], **_: object) -> SimpleNamespace:
                if command[1:] == ["--version"]:
                    return SimpleNamespace(stdout="openalex 0.test", stderr="", returncode=0)
                return SimpleNamespace(stdout="", stderr="", returncode=0)

            def fake_cli_download(command: list[str], *, files_dir: Path, **_: object) -> SimpleNamespace:
                files_dir.mkdir(parents=True, exist_ok=True)
                (files_dir / "broken.json").write_text("{not-json", encoding="utf-8")
                return SimpleNamespace(returncode=0)

            with (
                patch.object(openalex_cli_provider, "cli_status", return_value={"available": True, "executable": "/tmp/openalex"}),
                patch.object(openalex_cli_provider.subprocess, "run", side_effect=fake_run),
                patch.object(openalex_cli_provider, "_run_cli_download", side_effect=fake_cli_download),
            ):
                with self.assertRaises(ValueError):
                    openalex_cli_provider.download_works_metadata(
                        cfg,
                        api_key="test-key",
                        out_dir=root / "raw",
                        estimate={
                            "estimate_signature": corpus_signature(cfg),
                            "download_signature": cli_download_signature(cfg),
                            "estimate_count": 1,
                        },
                    )

            failed = json.loads((root / "raw/dump_manifest_failed.json").read_text(encoding="utf-8"))
            self.assertEqual(failed["stop_reason"], "cli_pack_failed")
            self.assertFalse(failed["allowed_for_final_analysis"])


def _work(short_id: str) -> dict[str, object]:
    return {"id": f"https://openalex.org/{short_id}", "display_name": short_id}


if __name__ == "__main__":
    unittest.main()
