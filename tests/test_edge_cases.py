from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _path  # noqa: F401
from openalex_mvp.config import load_config, replace_config
from openalex_mvp.metrics import build_author_work_metrics, compute_indices
from openalex_mvp.normalize import normalize_raw
from openalex_mvp.openalex import build_filter, fetch_works_slice_dump
from openalex_mvp.ranking import build_ratings
from openalex_mvp.stats import top_n_overlap


class EdgeCaseTests(unittest.TestCase):
    def test_top_n_overlap_uses_available_denominator(self) -> None:
        a = {"a1": 1, "a2": 2}
        b = {"a1": 1, "a2": 2}
        self.assertEqual(top_n_overlap(a, b, 20), 1.0)

    def test_null_author_excluded_and_strict_fraction_not_renormalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw.jsonl"
            raw.write_text(json.dumps(_work_with_null_author(), ensure_ascii=False) + "\n", encoding="utf-8")

            normalize_raw(raw, root / "works.csv", root / "auth.csv", root / "quality.json")
            mart = build_author_work_metrics(
                root / "works.csv",
                root / "auth.csv",
                root / "awm.csv",
                ("strict_authors_count", "renorm_valid_authors", "integer"),
            )
            strict = [row for row in mart if row["fraction_mode"] == "strict_authors_count"]
            renorm = [row for row in mart if row["fraction_mode"] == "renorm_valid_authors"]
            self.assertEqual(len(strict), 1)
            self.assertAlmostEqual(strict[0]["credit_weight"], 0.5)
            self.assertAlmostEqual(strict[0]["omitted_author_fraction"], 0.5)
            self.assertAlmostEqual(renorm[0]["credit_weight"], 1.0)

    def test_pipeline_smoke_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw.jsonl"
            raw.write_text(
                "\n".join(
                    [
                        json.dumps(_work("W1", "A1", 12), ensure_ascii=False),
                        json.dumps(_work("W2", "A1", 5), ensure_ascii=False),
                        json.dumps(_work("W3", "A2", 20), ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            normalize_raw(raw, root / "works.csv", root / "auth.csv", root / "quality.json")
            build_author_work_metrics(root / "works.csv", root / "auth.csv", root / "awm.csv", ("integer",))
            indices = compute_indices(root / "awm.csv", root / "indices.csv")
            ratings = build_ratings(root / "indices.csv", root / "ratings.csv")
            self.assertEqual(len(indices), 2)
            a1 = next(row for row in indices if row["author_id"] == "https://openalex.org/A1")
            self.assertEqual(a1["p"], 2)
            self.assertAlmostEqual(a1["cpp"], 8.5)
            self.assertEqual(a1["i10"], 1)
            self.assertAlmostEqual(a1["m_local"], 2.0)
            self.assertAlmostEqual(a1["top1_share"], 12 / 17)
            self.assertEqual(a1["f5"], 2.0)
            self.assertEqual(a1["fm5"], 2.0)
            self.assertAlmostEqual(a1["iupv"], 100.0 * (0.5 ** (1.0 / 3.0)))
            self.assertGreater(a1["islv"], 0.0)
            self.assertTrue(ratings)

    def test_topic_filter_keeps_openalex_t_prefix_and_no_hidden_date_filters(self) -> None:
        cfg = replace_config(
            load_config(Path(__file__).resolve().parents[1] / "config/slice.yaml"),
            entity_level="topic",
            entity_id_short="T10201",
            entity_id_full="https://openalex.org/T10201",
            entity_display_name="Speech Recognition and Synthesis",
            from_publication_date="",
            to_publication_date="",
            work_type="",
        )
        query = build_filter(cfg)
        self.assertIn("primary_topic.id:T10201", query)
        self.assertNotIn("primary_topic.id:10201", query)
        self.assertNotIn("from_publication_date", query)
        self.assertNotIn("type:article", query)

    def test_openalex_filter_accepts_mvp_work_type_or(self) -> None:
        cfg = replace_config(
            load_config(Path(__file__).resolve().parents[1] / "config/slice.yaml"),
            work_type="article|review|conference-paper",
        )
        query = build_filter(cfg)
        self.assertIn("type:article|review|conference-paper", query)

    def test_compact_slice_dump_writes_passport_and_checksum_without_network(self) -> None:
        cfg = replace_config(
            load_config(Path(__file__).resolve().parents[1] / "config/slice.yaml"),
            max_works=10,
        )
        with tempfile.TemporaryDirectory() as tmp, patch("openalex_mvp.openalex._get_json") as get_json:
            get_json.return_value = {
                "meta": {"count": 2, "next_cursor": "next"},
                "results": [_work("W1", "A1", 12), _work("W2", "A2", 5)],
            }
            passport = fetch_works_slice_dump(cfg, tmp, max_records=1, max_bytes=100_000)
            raw_path = Path(passport["raw_jsonl"])
            self.assertEqual(passport["records_downloaded"], 1)
            self.assertEqual(passport["stop_reason"], "max_records")
            self.assertTrue(raw_path.exists())
            self.assertEqual(len(passport["raw_jsonl_sha256"]), 64)
            self.assertNotIn("api_key", passport["openalex_request"])


def _work(work_id: str, author_id: str, citations: int) -> dict:
    return {
        "id": f"https://openalex.org/{work_id}",
        "display_name": work_id,
        "publication_year": 2020,
        "publication_date": "2020-01-01",
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


def _work_with_null_author() -> dict:
    work = _work("WNULL", "A1", 10)
    work["authorships"].append(
        {
            "author_position": "last",
            "author": {"id": None, "display_name": "Unknown", "orcid": None},
            "institutions": [],
            "countries": [],
            "is_corresponding": False,
            "raw_author_name": "Unknown",
        }
    )
    return work


if __name__ == "__main__":
    unittest.main()
