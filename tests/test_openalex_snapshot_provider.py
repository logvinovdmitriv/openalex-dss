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

from app.providers import openalex_snapshot_provider  # noqa: E402
from openalex_dss.config import load_config, replace_config  # noqa: E402
from openalex_dss.openalex import corpus_signature, snapshot_download_signature  # noqa: E402


class OpenAlexSnapshotProviderTests(unittest.TestCase):
    def test_snapshot_scan_reports_parse_errors_and_blocks_final(self) -> None:
        cfg = replace_config(
            load_config(ROOT / "config/slice.yaml"),
            slice_name="snapshot_parse_error",
            filter_mode="primary_topic",
            entity_level="subfield",
            entity_id_short="2604",
            work_type="article",
            from_publication_date="2020-01-01",
            to_publication_date="2024-12-31",
        )
        work = {
            "id": "https://openalex.org/W1",
            "publication_date": "2021-01-01",
            "type": "article",
            "is_retracted": False,
            "is_paratext": False,
            "is_xpac": False,
            "primary_topic": {"subfield": {"id": "https://openalex.org/subfields/2604"}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            with gzip.open(snapshot / "part.jsonl.gz", "wt", encoding="utf-8") as handle:
                handle.write(json.dumps(work) + "\n")
                handle.write("{broken json\n")
            manifest = openalex_snapshot_provider.scan_snapshot_partitions(
                cfg,
                snapshot_dir=snapshot,
                out_dir=root / "out",
                estimate={
                    "estimate_count": 1,
                    "accepted_estimate_signature": corpus_signature(cfg),
                    "accepted_download_signature": snapshot_download_signature(cfg),
                },
            )
            self.assertTrue(Path(manifest["snapshot_partition_manifest"]).is_file())

        self.assertEqual(manifest["snapshot_parse_error_count"], 1)
        self.assertFalse(manifest["allowed_for_final_analysis"])
        self.assertEqual(manifest["scientific_completeness"], "partial")


if __name__ == "__main__":
    unittest.main()
