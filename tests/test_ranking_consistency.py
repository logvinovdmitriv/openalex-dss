from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openalex_dss.io_utils import read_csv_dicts, write_csv_dicts
from openalex_dss.ranking import build_ratings, sort_metric_rows


class RankingConsistencyTests(unittest.TestCase):
    def test_shared_ranking_rule_uses_c_p_author_tie_breakers(self) -> None:
        rows = [
            {"run_id": "base", "fraction_mode": "strict_authors_count", "author_id": "A3", "author_display_name": "C", "h": "5", "c": "20", "p": "9"},
            {"run_id": "base", "fraction_mode": "strict_authors_count", "author_id": "A2", "author_display_name": "B", "h": "5", "c": "40", "p": "2"},
            {"run_id": "base", "fraction_mode": "strict_authors_count", "author_id": "A1", "author_display_name": "A", "h": "5", "c": "40", "p": "7"},
            {"run_id": "base", "fraction_mode": "strict_authors_count", "author_id": "A4", "author_display_name": "D", "h": "4", "c": "99", "p": "99"},
        ]

        ranked = sort_metric_rows(rows, "h")
        self.assertEqual([row["author_id"] for row in ranked], ["A1", "A2", "A3", "A4"])

    def test_rating_csv_uses_same_tie_break_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "indices.csv"
            out = root / "ratings.csv"
            fields = ["run_id", "fraction_mode", "author_id", "author_display_name", "h", "c", "p"]
            write_csv_dicts(
                source,
                [
                    {"run_id": "base", "fraction_mode": "strict_authors_count", "author_id": "A2", "author_display_name": "B", "h": 5, "c": 40, "p": 2},
                    {"run_id": "base", "fraction_mode": "strict_authors_count", "author_id": "A1", "author_display_name": "A", "h": 5, "c": 40, "p": 7},
                ],
                fields,
            )

            build_ratings(source, out, metrics=("h",))
            rows = read_csv_dicts(out)

        self.assertEqual([row["author_id"] for row in rows], ["A1", "A2"])
        self.assertEqual([row["rank_competition"] for row in rows], ["1", "1"])
        self.assertEqual([row["position"] for row in rows], ["1", "2"])

    def test_optimized_rating_csv_uses_same_tie_break_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "indices.csv"
            out = root / "ratings.csv"
            fields = ["run_id", "fraction_mode", "author_id", "author_display_name", "h", "c", "p"]
            write_csv_dicts(
                source,
                [
                    {"run_id": "base", "fraction_mode": "strict_authors_count", "author_id": "A2", "author_display_name": "B", "h": 5, "c": 40, "p": 2},
                    {"run_id": "base", "fraction_mode": "strict_authors_count", "author_id": "A1", "author_display_name": "A", "h": 5, "c": 40, "p": 7},
                ],
                fields,
            )

            build_ratings(source, out, metrics=("h",), return_rows=False)
            rows = read_csv_dicts(out)

        self.assertEqual([row["author_id"] for row in rows], ["A1", "A2"])
        self.assertEqual([row["rank_competition"] for row in rows], ["1", "1"])
        self.assertEqual([row["position"] for row in rows], ["1", "2"])


if __name__ == "__main__":
    unittest.main()
