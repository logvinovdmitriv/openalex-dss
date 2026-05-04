from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from openalex_mvp.metrics import build_author_work_metrics, compute_indices
from openalex_mvp.normalize import normalize_raw
from openalex_mvp.theory import analyze_theory


class TheoryAnalysisTests(unittest.TestCase):
    def test_theory_analysis_writes_expected_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw.jsonl"
            raw.write_text(
                "\n".join(
                    [
                        json.dumps(_work("W1", "A1", 20, "2020-01-01"), ensure_ascii=False),
                        json.dumps(_work("W2", "A1", 5, "2020-01-02"), ensure_ascii=False),
                        json.dumps(_work("W3", "A2", 30, "2020-01-03"), ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            normalize_raw(raw, root / "works.csv", root / "auth.csv", root / "quality.json")
            build_author_work_metrics(root / "works.csv", root / "auth.csv", root / "awm.csv", ("strict_authors_count", "integer"))
            compute_indices(root / "awm.csv", root / "indices.csv")
            result = analyze_theory(
                root / "awm.csv",
                root / "indices.csv",
                root / "theory.json",
                root,
                default_mode="strict_authors_count",
            )
            self.assertTrue(result["iupv_property_checks"]["observed_within_0_100"])
            self.assertTrue(result["islv_property_checks"]["observed_within_0_100"])
            self.assertIn("strict_authors_count", result["top1_sensitivity"])
            self.assertTrue((root / "theory_top1_sensitivity.csv").is_file())
            self.assertTrue((root / "theory_fraction_mode_sensitivity.csv").is_file())


def _work(work_id: str, author_id: str, citations: int, date: str) -> dict:
    return {
        "id": f"https://openalex.org/{work_id}",
        "display_name": work_id,
        "publication_year": int(date[:4]),
        "publication_date": date,
        "type": "article",
        "cited_by_count": citations,
        "is_retracted": False,
        "is_paratext": False,
        "is_xpac": False,
        "primary_topic": {
            "id": "https://openalex.org/T1",
            "display_name": "Topic",
            "subfield": {"id": "https://openalex.org/subfields/2604", "display_name": "Applied Mathematics"},
            "field": {"id": "https://openalex.org/fields/26"},
            "domain": {"id": "https://openalex.org/domains/3"},
        },
        "authorships": [
            {
                "author_position": "first",
                "author": {"id": f"https://openalex.org/{author_id}", "display_name": author_id, "orcid": None},
                "institutions": [],
                "countries": [],
                "is_corresponding": False,
                "raw_author_name": author_id,
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
