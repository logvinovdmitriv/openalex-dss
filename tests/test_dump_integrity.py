from __future__ import annotations

import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps/api"
SRC = ROOT / "src"
for path in (API, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services import dump_integrity  # noqa: E402
from openalex_dss.io_utils import sha256_file  # noqa: E402


class DumpIntegrityTests(unittest.TestCase):
    def test_manifest_validation_rejects_record_count_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "works.jsonl.gz"
            with gzip.open(raw, "wt", encoding="utf-8") as handle:
                handle.write(json.dumps({"id": "https://openalex.org/W1"}) + "\n")
            manifest = {
                "raw_jsonl": str(raw),
                "raw_jsonl_sha256": sha256_file(raw),
                "records_downloaded": 1,
                "records_expected": 2,
                "scientific_completeness": "complete",
                "allowed_for_final_analysis": True,
            }

            checked = dump_integrity.manifest_with_integrity(manifest)

        self.assertFalse(checked["allowed_for_final_analysis"])
        self.assertEqual(checked["scientific_completeness"], "partial_integrity_failed")
        self.assertIn("records_expected_mismatch", checked["integrity_validation"]["errors"])

    def test_manifest_validation_rejects_broken_gzip_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "works.jsonl.gz"
            with gzip.open(raw, "wt", encoding="utf-8") as handle:
                handle.write("{broken\n")

            result = dump_integrity.validate_dump_manifest(
                {
                    "raw_jsonl": str(raw),
                    "records_downloaded": 1,
                    "records_expected": 1,
                    "scientific_completeness": "complete",
                }
            )

        self.assertEqual(result["status"], "failed")
        self.assertIn("raw_jsonl_parse_errors", result["errors"])


if __name__ == "__main__":
    unittest.main()
