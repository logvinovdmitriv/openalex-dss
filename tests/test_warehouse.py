from __future__ import annotations

import sys
import json
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
                "ratings": root / "csv" / "rating_positions.csv",
            }
            parquet_paths = {
                "works": root / "parquet" / "works_flat.parquet",
                "authorships": root / "parquet" / "authorships_flat.parquet",
                "work_topics": root / "parquet" / "work_topics_flat.parquet",
                "author_work": root / "parquet" / "author_work_metrics.parquet",
                "indices": root / "parquet" / "author_indices.parquet",
                "authors_local_metrics": root / "parquet" / "author_indices.parquet",
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

    def test_run_scoped_metric_ranking_uses_requested_run_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dump_tables(root, "dump_a", "W_A", "A_A", "Author A", 5)
            _write_dump_tables(root, "dump_b", "W_B", "A_B", "Author B", 50)
            _write_run_author_work(root, "run_a", "dump_a", "W_A", "A_A", "Author A", 5)
            _write_run_author_work(root, "run_b", "dump_b", "W_B", "A_B", "Author B", 50)

            # Deliberately point latest-view at run_b-like data. A scoped query
            # for run_a must not leak this author into the result.
            latest_author_work = root / "latest" / "author_work.parquet"
            write_parquet_dicts(
                latest_author_work,
                [_author_work_row("W_B", "A_B", "Author B", 50)],
                _author_work_fields(),
            )
            parquet_paths = {
                "author_work": latest_author_work,
                "works": root / "missing" / "works.parquet",
                "authorships": root / "missing" / "authorships.parquet",
                "work_topics": root / "missing" / "work_topics.parquet",
                "indices": root / "missing" / "indices.parquet",
                "authors_local_metrics": root / "missing" / "indices.parquet",
                "ratings": root / "missing" / "ratings.parquet",
            }
            csv_paths = {name: path.with_suffix(".csv") for name, path in parquet_paths.items()}

            with (
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "TABLE_FILES", csv_paths),
                patch.object(warehouse, "PARQUET_TABLE_FILES", parquet_paths),
                patch.object(warehouse, "WAREHOUSE", root / "warehouse.duckdb"),
            ):
                ranking = warehouse.metric_ranking("integer", "h", run_id="run_a", limit=10)

            self.assertEqual(ranking["dump_id"], "dump_a")
            self.assertEqual([row["author_display_name"] for row in ranking["rows"]], ["Author A"])
            self.assertEqual(ranking["rows"][0]["h"], 1)
            self.assertEqual(ranking["metric_scope"], "filtered_recomputed")

    def test_analysis_scope_rejects_foreign_dump_for_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "runs" / "run_a"
            run_dir.mkdir(parents=True)
            (run_dir / "metric_run.json").write_text(json.dumps({"run_id": "run_a", "dump_id": "dump_a"}), encoding="utf-8")

            with patch.object(warehouse, "DATA", root):
                with self.assertRaises(ValueError) as raised:
                    warehouse.resolve_analysis_scope(run_id="run_a", dump_id="dump_b")

        self.assertIn("incompatible", str(raised.exception))

    def test_list_tables_does_not_show_latest_path_as_scoped_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run_author_work(root, "run_a", "dump_a", "W_A", "A_A", "Author A", 5)
            latest_indices = root / "latest" / "indices.parquet"
            write_parquet_dicts(latest_indices, [{"author_id": "latest", "h": 99}], ["author_id", "h"])
            parquet_paths = _latest_parquet_paths(root)
            parquet_paths["indices"] = latest_indices
            parquet_paths["authors_local_metrics"] = latest_indices

            with (
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "TABLE_FILES", _latest_csv_paths(root)),
                patch.object(warehouse, "PARQUET_TABLE_FILES", parquet_paths),
            ):
                tables = warehouse.list_tables(run_id="run_a")

        self.assertEqual(tables["indices"]["scope"], "run")
        self.assertEqual(tables["indices"]["path"], "")
        self.assertEqual(tables["indices"]["resolved_path"], "")
        self.assertTrue(tables["indices"]["latest_path"].endswith("indices.parquet"))
        self.assertFalse(tables["indices"]["uses_latest_fallback"])
        self.assertFalse(tables["indices"]["exists"])

    def test_query_table_returns_resolved_dump_id_for_run_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dump_tables(root, "dump_a", "W_A", "A_A", "Author A", 5)
            _write_run_author_work(root, "run_a", "dump_a", "W_A", "A_A", "Author A", 5)

            with (
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "TABLE_FILES", _latest_csv_paths(root)),
                patch.object(warehouse, "PARQUET_TABLE_FILES", _latest_parquet_paths(root)),
                patch.object(warehouse, "WAREHOUSE", root / "warehouse.duckdb"),
            ):
                table = warehouse.query_table("works", run_id="run_a")

        self.assertEqual(table["run_id"], "run_a")
        self.assertEqual(table["dump_id"], "dump_a")
        self.assertEqual(table["total"], 1)
        self.assertTrue(table["source_path"].endswith("tables/dump_a/works.parquet"))

    def test_run_metric_params_do_not_fallback_to_latest_when_run_passport_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            latest = root / "passports" / "calculation_passport.json"
            latest.parent.mkdir(parents=True)
            latest.write_text(json.dumps({"lrdi": {"p0": 99, "lambda": 0.99, "analysis_year": 1999}}), encoding="utf-8")

            with patch.object(warehouse, "DATA", root):
                params = warehouse._run_metric_params("run_without_passport")

        self.assertEqual(params["source"], "defaults_missing_run_calculation_passport")
        self.assertEqual(params["analysis_year"], 2026)
        self.assertEqual(params["lrdi_p0"], 5.0)

    def test_two_year_mean_citedness_metric_is_not_supported_until_defined(self) -> None:
        with self.assertRaises(ValueError):
            warehouse.metric_ranking("integer", "two_year_mean_citedness")

    def test_metric_ranking_allows_export_scale_limit_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_many_author_scope(root, "run_many", "dump_many", 250)
            with (
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "TABLE_FILES", _latest_csv_paths(root)),
                patch.object(warehouse, "PARQUET_TABLE_FILES", _latest_parquet_paths(root)),
                patch.object(warehouse, "WAREHOUSE", root / "warehouse.duckdb"),
            ):
                ranking = warehouse.metric_ranking("integer", "h", run_id="run_many", limit=250, max_limit=1000)

            self.assertEqual(ranking["total"], 250)
            self.assertEqual(len(ranking["rows"]), 250)

    def test_author_detail_is_run_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dump_tables(root, "dump_a", "W_A", "A_A", "Author A", 5)
            _write_dump_tables(root, "dump_b", "W_B", "A_B", "Author B", 50)
            _write_run_author_work(root, "run_a", "dump_a", "W_A", "A_A", "Author A", 5)
            _write_run_author_work(root, "run_b", "dump_b", "W_B", "A_B", "Author B", 50)
            latest_author_work = root / "latest" / "author_work.parquet"
            write_parquet_dicts(latest_author_work, [_author_work_row("W_B", "A_B", "Author B", 50)], _author_work_fields())
            parquet_paths = _latest_parquet_paths(root)
            parquet_paths["author_work"] = latest_author_work

            with (
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "TABLE_FILES", _latest_csv_paths(root)),
                patch.object(warehouse, "PARQUET_TABLE_FILES", parquet_paths),
                patch.object(warehouse, "WAREHOUSE", root / "warehouse.duckdb"),
            ):
                detail = warehouse.author_detail("https://openalex.org/A_A", run_id="run_a")

            self.assertEqual(detail["dump_id"], "dump_a")
            self.assertEqual([row["work_id"] for row in detail["works"]], ["https://openalex.org/W_A"])

def _write_dump_tables(root: Path, dump_id: str, work_id: str, author_id: str, author_name: str, citations: int) -> None:
    base = root / "tables" / dump_id
    write_parquet_dicts(
        base / "works.parquet",
        [
            {
                "work_id": f"https://openalex.org/{work_id}",
                "publication_date": "2024-01-01",
                "publication_year": 2024,
                "type": "article",
                "cited_by_count": citations,
                "display_name": f"Work {work_id}",
                "source_display_name": "",
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
            "display_name",
            "source_display_name",
            "primary_topic_display_name",
            "primary_topic_id",
            "primary_subfield_short_id",
            "primary_subfield_id",
            "primary_field_id",
        ],
    )
    write_parquet_dicts(
        base / "authorships.parquet",
        [
            {
                "work_id": f"https://openalex.org/{work_id}",
                "author_id": f"https://openalex.org/{author_id}",
                "author_display_name": author_name,
                "country_codes_csv": "RU",
                "institution_ids_csv": "https://openalex.org/I1",
            }
        ],
        ["work_id", "author_id", "author_display_name", "country_codes_csv", "institution_ids_csv"],
    )


def _write_run_author_work(root: Path, run_id: str, dump_id: str, work_id: str, author_id: str, author_name: str, citations: int) -> None:
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "metric_run.json").write_text(json.dumps({"run_id": run_id, "dump_id": dump_id, "input_dump_id": dump_id}), encoding="utf-8")
    write_parquet_dicts(run_dir / "tables" / "author_work.parquet", [_author_work_row(work_id, author_id, author_name, citations)], _author_work_fields())


def _write_many_author_scope(root: Path, run_id: str, dump_id: str, n: int) -> None:
    dump_dir = root / "tables" / dump_id
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "metric_run.json").write_text(json.dumps({"run_id": run_id, "dump_id": dump_id, "input_dump_id": dump_id}), encoding="utf-8")
    works = []
    authorships = []
    author_work = []
    for index in range(n):
        work_id = f"W{index}"
        author_id = f"A{index}"
        author_name = f"Author {index:03d}"
        citations = index + 1
        works.append(
            {
                "work_id": f"https://openalex.org/{work_id}",
                "publication_date": "2024-01-01",
                "publication_year": 2024,
                "type": "article",
                "cited_by_count": citations,
                "display_name": f"Work {index}",
                "source_display_name": "",
                "primary_topic_display_name": "Software Engineering",
                "primary_topic_id": "https://openalex.org/T1",
                "primary_subfield_short_id": "1706",
                "primary_subfield_id": "https://openalex.org/subfields/1706",
                "primary_field_id": "https://openalex.org/fields/17",
            }
        )
        authorships.append(
            {
                "work_id": f"https://openalex.org/{work_id}",
                "author_id": f"https://openalex.org/{author_id}",
                "author_display_name": author_name,
                "country_codes_csv": "RU",
                "institution_ids_csv": "https://openalex.org/I1",
            }
        )
        author_work.append(_author_work_row(work_id, author_id, author_name, citations))
    write_parquet_dicts(
        dump_dir / "works.parquet",
        works,
        [
            "work_id",
            "publication_date",
            "publication_year",
            "type",
            "cited_by_count",
            "display_name",
            "source_display_name",
            "primary_topic_display_name",
            "primary_topic_id",
            "primary_subfield_short_id",
            "primary_subfield_id",
            "primary_field_id",
        ],
    )
    write_parquet_dicts(dump_dir / "authorships.parquet", authorships, ["work_id", "author_id", "author_display_name", "country_codes_csv", "institution_ids_csv"])
    write_parquet_dicts(run_dir / "tables" / "author_work.parquet", author_work, _author_work_fields())


def _latest_parquet_paths(root: Path) -> dict[str, Path]:
    return {
        "author_work": root / "missing" / "author_work.parquet",
        "works": root / "missing" / "works.parquet",
        "authorships": root / "missing" / "authorships.parquet",
        "work_topics": root / "missing" / "work_topics.parquet",
        "indices": root / "missing" / "indices.parquet",
        "authors_local_metrics": root / "missing" / "indices.parquet",
        "ratings": root / "missing" / "ratings.parquet",
    }


def _latest_csv_paths(root: Path) -> dict[str, Path]:
    return {name: path.with_suffix(".csv") for name, path in _latest_parquet_paths(root).items()}


def _author_work_row(work_id: str, author_id: str, author_name: str, citations: int) -> dict[str, object]:
    return {
        "fraction_mode": "integer",
        "author_id": f"https://openalex.org/{author_id}",
        "author_display_name": author_name,
        "work_id": f"https://openalex.org/{work_id}",
        "publication_year": 2024,
        "cited_by_count": citations,
        "authors_count_used": 1,
        "credit_weight": 1.0,
        "cited_credit": float(citations),
        "single_authored_flag": True,
        "qf_any": False,
        "qf_authorship_truncated": False,
    }


def _author_work_fields() -> list[str]:
    return [
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
    ]


if __name__ == "__main__":
    unittest.main()
