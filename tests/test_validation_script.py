from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ValidationScriptTests(unittest.TestCase):
    def test_validate_scientometric_dss_script_runs_and_checks_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "validation-data"

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/validate_scientometric_dss.py"),
                    "--data-dir",
                    str(data_dir),
                    "--reset",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

            manifest = json.loads((data_dir / "validation/scientometric_validation_manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["status"], "ok")
            self.assertEqual(manifest["run_id"], "validation_scientometric")
            self.assertEqual(manifest["dump_id"], "validation_fixture_dump")
            self.assertEqual(manifest["cohort_id"], "cohort_validation")
            self.assertEqual(manifest["fraction_mode"], "integer")
            self.assertEqual(manifest["baseline_metric"], "h")
            self.assertEqual(manifest["rank_top_n"], 5)
            self.assertEqual(manifest["n_authors"], 5)
            self.assertFalse(manifest["analysis_eligibility"]["allowed_for_final_analysis"])
            self.assertIn("top_outliers_csv", manifest["artifacts"])
            for name, path in manifest["artifacts"].items():
                self.assertTrue(Path(path).is_file(), name)
                self.assertRegex(manifest["artifact_checksums"][name], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
