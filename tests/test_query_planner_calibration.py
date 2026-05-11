from __future__ import annotations

import json
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

from app.services import query_planner  # noqa: E402


class QueryPlannerCalibrationTests(unittest.TestCase):
    def test_estimate_calibration_records_archive_and_download_base_separately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            download_base = tmp_path / "raw" / "slice"
            download_base.mkdir(parents=True)
            raw = download_base / "works.jsonl.gz"
            raw.write_bytes(b"a" * 100)
            (download_base / "page_000001.jsonl.gz").write_bytes(b"b" * 50)
            data_root = tmp_path / "data"

            estimate = {
                "estimated_raw_bytes": 80,
                "estimated_selected_api_bytes": 80,
                "estimated_cli_metadata_bytes": 200,
                "byte_estimate": {
                    "final_raw_jsonl_gz": {"p90_bytes": 100},
                    "parquet_tables": {"p90_bytes": 120},
                    "cli_temp_files_peak": {"p90_bytes": 300},
                    "recommended_free_space": {"bytes": 600},
                },
                "estimate_signature": "estimate",
                "download_signature": "download",
            }
            manifest = {
                "slice_id": "slice",
                "dump_id": "dump",
                "source_mode": "openalex_api",
                "raw_jsonl": str(raw),
                "bytes_written": 100,
                "records_expected": 2,
                "records_downloaded": 2,
                "storage_plan": {"download_base_dir": str(download_base)},
            }

            with patch.object(query_planner, "DATA", data_root):
                query_planner.record_estimate_calibration(manifest, estimate)
                log_path = data_root / "cache" / "estimate_calibration" / "download_estimate_calibration.jsonl"
                record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])

            self.assertEqual(record["schema"], "download_estimate_calibration_v2")
            self.assertEqual(record["actual_raw_package_bytes"], 100)
            self.assertEqual(record["actual_download_base_bytes"], 150)
            self.assertEqual(record["actual_bytes"], 150)
            self.assertEqual(record["estimated_selected_api_bytes"], 80)
            self.assertEqual(record["estimated_full_metadata_bytes"], 200)
            self.assertEqual(record["estimated_final_raw_jsonl_gz_bytes"], 100)
            self.assertEqual(record["estimated_parquet_tables_bytes"], 120)
            self.assertEqual(record["estimated_cli_temp_peak_bytes"], 300)
            self.assertEqual(record["estimated_recommended_free_space_bytes"], 600)


if __name__ == "__main__":
    unittest.main()
