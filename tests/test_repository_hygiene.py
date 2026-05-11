from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAT = "lat" + "est"
LEG = "leg" + "acy"
COMP = "comp" + "atibility"
OLD_PROTO_LOWER = "m" + "vp"
OLD_PROTO_UPPER = "M" + "VP"


class RepositoryHygieneTests(unittest.TestCase):
    def test_current_contract_does_not_reintroduce_removed_markers(self) -> None:
        markers = (
            LEG,
            LAT,
            COMP,
            "allow_" + LAT,
            "implicit_" + LAT,
            "generated_" + "data",
            "author_" + "indices",
            "rating_" + "positions",
            "authors_" + "local_" + "metrics",
            "stats_" + "summary",
            "theory_" + "validation",
            "top1_" + "sensitivity",
            "fraction_" + "sensitivity",
            "PRIMARY_" + "ARTIFACTS",
            "data/" + "checksums",
            "bundle_" + "version",
            "report_" + "bundle_v",
            "scientometrics" + "_v",
            "findings_" + "version",
            "conclusion_" + "version",
            "openalex_" + OLD_PROTO_LOWER,
            OLD_PROTO_LOWER + "_protocol",
            OLD_PROTO_UPPER,
            OLD_PROTO_LOWER,
            "Backward-" + "comp" + "atible",
            "older " + "imports",
            "extra_" + "previous",
            "iupv_" + "n0",
            "iupv_" + "lambda",
        )
        files = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
        violations: list[str] = []
        for rel in files:
            if rel.startswith("apps/web/dist/"):
                continue
            for marker in markers:
                if marker in rel:
                    violations.append(f"{rel}: path contains {marker}")
            path = ROOT / rel
            if not path.exists():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for marker in markers:
                if marker in text:
                    violations.append(f"{rel}: {marker}")

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
