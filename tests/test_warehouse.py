from __future__ import annotations

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

from app.services import warehouse  # noqa: E402
from openalex_mvp.io_utils import write_parquet_dicts  # noqa: E402


class WarehouseTests(unittest.TestCase):
    def test_filtered_author_indices_reads_parquet_when_csv_latest_view_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_paths = {
                "works": root / "csv" / "works_flat.csv",
                "authorships": root / "csv" / "authorships_flat.csv",
                "work_topics": root / "csv" / "work_topics_flat.csv",
                "author_work": root / "csv" / "author_work_metrics.csv",
                "indices": root / "csv" / "author_indices.csv",
                "authors_local_metrics": root / "csv" / "author_indices.csv",
                "author_profiles": root / "csv" / "author_profiles_flat.csv",
                "authors_preview": root / "csv" / "author_profiles_flat.csv",
                "ratings": root / "csv" / "rating_positions.csv",
            }
            parquet_paths = {
                "works": root / "parquet" / "works_flat.parquet",
                "authorships": root / "parquet" / "authorships_flat.parquet",
                "work_topics": root / "parquet" / "work_topics_flat.parquet",
                "author_work": root / "parquet" / "author_work_metrics.parquet",
                "indices": root / "parquet" / "author_indices.parquet",
                "authors_local_metrics": root / "parquet" / "author_indices.parquet",
                "author_profiles": root / "parquet" / "author_profiles_flat.parquet",
                "authors_preview": root / "parquet" / "author_profiles_flat.parquet",
                "ratings": root / "parquet" / "rating_positions.parquet",
            }
            write_parquet_dicts(
                parquet_paths["works"],
                [
                    {
                        "work_id": "https://openalex.org/W1",
                        "publication_date": "2024-01-01",
                        "publication_year": 2024,
                        "type": "article",
                        "cited_by_count": 12,
                        "primary_topic_display_name": "Software Engineering",
                        "primary_topic_id": "https://openalex.org/T1",
                        "primary_subfield_short_id": "1706",
                        "primary_subfield_id": "https://openalex.org/subfields/1706",
                        "primary_field_id": "https://openalex.org/fields/17",
                    }
                ],
                [
                    "work_id",
                    "publication_date",
                    "publication_year",
                    "type",
                    "cited_by_count",
                    "primary_topic_display_name",
                    "primary_topic_id",
                    "primary_subfield_short_id",
                    "primary_subfield_id",
                    "primary_field_id",
                ],
            )
            write_parquet_dicts(
                parquet_paths["authorships"],
                [
                    {
                        "work_id": "https://openalex.org/W1",
                        "author_id": "https://openalex.org/A1",
                        "country_codes_csv": "RU",
                        "institution_ids_csv": "https://openalex.org/I1",
                    }
                ],
                ["work_id", "author_id", "country_codes_csv", "institution_ids_csv"],
            )
            write_parquet_dicts(
                parquet_paths["author_work"],
                [
                    {
                        "fraction_mode": "integer",
                        "author_id": "https://openalex.org/A1",
                        "author_display_name": "Author One",
                        "work_id": "https://openalex.org/W1",
                        "publication_year": 2024,
                        "cited_by_count": 12,
                        "authors_count_used": 1,
                        "credit_weight": 1.0,
                        "cited_credit": 12.0,
                        "single_authored_flag": True,
                        "qf_any": False,
                        "qf_authorship_truncated": False,
                    }
                ],
                [
                    "fraction_mode",
                    "author_id",
                    "author_display_name",
                    "work_id",
                    "publication_year",
                    "cited_by_count",
                    "authors_count_used",
                    "credit_weight",
                    "cited_credit",
                    "single_authored_flag",
                    "qf_any",
                    "qf_authorship_truncated",
                ],
            )

            with (
                patch.object(warehouse, "TABLE_FILES", csv_paths),
                patch.object(warehouse, "PARQUET_TABLE_FILES", parquet_paths),
                patch.object(warehouse, "WAREHOUSE", root / "warehouse.duckdb"),
            ):
                rows = warehouse.filtered_author_indices("integer", {"country_code": "RU"})

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["author_display_name"], "Author One")
            self.assertEqual(rows[0]["p"], 1)
            self.assertEqual(rows[0]["h"], 1)
            self.assertAlmostEqual(rows[0]["c_frac"], 12.0)


if __name__ == "__main__":
    unittest.main()
