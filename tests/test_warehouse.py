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
from openalex_dss.io_utils import write_parquet_dicts  # noqa: E402


class WarehouseTests(unittest.TestCase):
    def test_count_rows_reuses_path_stat_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            table_path = Path(tmp) / "indices.csv"
            table_path.write_text("author_id,h\nA1,1\n", encoding="utf-8")
            warehouse._ROW_COUNT_CACHE.clear()
            with (
                patch.object(warehouse, "resolve_scoped_table_path", return_value=table_path),
                patch.object(warehouse, "_count_csv_rows", return_value=1) as count_csv_rows,
            ):
                first = warehouse.count_rows("indices", run_id="run_a")
                second = warehouse.count_rows("indices", run_id="run_a")

        self.assertEqual(first, 1)
        self.assertEqual(second, 1)
        self.assertEqual(count_csv_rows.call_count, 1)

    def test_empty_author_id_filter_returns_empty_rows(self) -> None:
        rows = [
            {"author_id": "https://openalex.org/A1", "h": 3},
            {"author_id": "https://openalex.org/A2", "h": 2},
        ]

        self.assertEqual(warehouse.filter_rows_by_author_ids(rows, None), rows)
        self.assertEqual(warehouse.filter_rows_by_author_ids(rows, set()), [])
        self.assertEqual(warehouse.filter_rows_by_author_ids(rows, ["https://openalex.org/A2"]), [rows[1]])

    def test_apply_data_selection_filters_sorts_and_limits_metric_rows(self) -> None:
        rows = [
            {"author_id": "A1", "h": 3, "p": 2},
            {"author_id": "A2", "h": 8, "p": 5},
            {"author_id": "A3", "h": 5, "p": 4},
        ]

        selected = warehouse.apply_data_selection(
            rows,
            data_filters={"p": {"min": "3"}, "work_type": {"contains": "article"}},
            data_sort="h",
            data_direction="asc",
            data_limit=1,
        )

        self.assertEqual([row["author_id"] for row in selected], ["A3"])

    def test_selected_index_rows_reads_precomputed_indices_without_slice_filters(self) -> None:
        with (
            patch.object(warehouse, "table_exists", return_value=True),
            patch.object(warehouse, "table_schema", return_value=["fraction_mode", "author_id", "author_display_name", "h"]),
            patch.object(
                warehouse,
                "query_table",
                return_value={
                    "rows": [{"fraction_mode": "integer", "author_id": "A1", "author_display_name": "Author One", "h": 3}],
                    "total": 1,
                    "limit": 1,
                },
            ) as query_table,
            patch.object(warehouse, "filtered_indices", return_value=[]) as filtered_indices,
        ):
            rows = warehouse.selected_index_rows("integer", {}, run_id="run_a", data_sort="h", data_limit=1)

        self.assertEqual(rows[0]["author_id"], "A1")
        filtered_indices.assert_not_called()
        query_table.assert_called_once_with(
            "indices",
            run_id="run_a",
            dump_id="",
            q="",
            fraction_mode="integer",
            data_filters={},
            sort="h",
            direction="desc",
            limit=1,
            select_fields={"author_id", "author_display_name", "h"},
        )

    def test_selected_index_rows_treats_filter_mode_all_as_unfiltered(self) -> None:
        with (
            patch.object(warehouse, "table_exists", return_value=True),
            patch.object(warehouse, "table_schema", return_value=["fraction_mode", "author_id", "h"]),
            patch.object(
                warehouse,
                "query_table",
                return_value={
                    "rows": [{"fraction_mode": "integer", "author_id": "A1", "h": 3}],
                    "total": 1,
                    "limit": 0,
                },
            ) as query_table,
            patch.object(warehouse, "filtered_indices", return_value=[]) as filtered_indices,
        ):
            rows = warehouse.selected_index_rows("integer", {"filter_mode": "all", "affiliation_mode": "historical"}, run_id="run_a")

        self.assertEqual(rows[0]["author_id"], "A1")
        filtered_indices.assert_not_called()
        query_table.assert_called_once()
        self.assertEqual(query_table.call_args.kwargs["limit"], 0)
        self.assertEqual(query_table.call_args.kwargs["select_fields"], {"author_id"})

    def test_selected_index_rows_limits_precomputed_columns_for_analytics(self) -> None:
        with (
            patch.object(warehouse, "table_exists", return_value=True),
            patch.object(warehouse, "table_schema", return_value=["fraction_mode", "author_id", "author_display_name", "h", "p", "c", "unused_blob"]),
            patch.object(
                warehouse,
                "query_table",
                return_value={
                    "rows": [{"author_id": "A1", "author_display_name": "Author One", "h": 3, "p": 2}],
                    "total": 1,
                    "limit": 0,
                },
            ) as query_table,
        ):
            rows = warehouse.selected_index_rows(
                "integer",
                {},
                run_id="run_a",
                select_fields={"h", "p"},
                custom_metric_defs=[{"id": "custom_test", "label": "Test", "expression": "h + pr_c"}],
            )

        self.assertEqual(rows[0]["author_id"], "A1")
        self.assertEqual(query_table.call_args.kwargs["select_fields"], {"author_id", "author_display_name", "h", "p", "c"})

    def test_selected_index_rows_sorts_custom_metric_before_limiting(self) -> None:
        source_rows = [
            {"author_id": "A1", "author_display_name": "Author One", "c": 1},
            {"author_id": "A2", "author_display_name": "Author Two", "c": 9},
        ]

        def fake_query_table(*_args: object, **kwargs: object) -> dict[str, object]:
            limit = int(kwargs.get("limit") or 0)
            rows = source_rows[:limit] if limit > 0 else source_rows
            return {"rows": rows, "total": len(source_rows), "limit": limit}

        with (
            patch.object(warehouse, "table_exists", return_value=True),
            patch.object(warehouse, "table_schema", return_value=["author_id", "author_display_name", "c"]),
            patch.object(warehouse, "query_table", side_effect=fake_query_table) as query_table,
        ):
            rows = warehouse.selected_index_rows(
                "integer",
                {},
                run_id="run_a",
                data_sort="custom_score",
                data_limit=1,
                custom_metric_defs=[{"id": "custom_score", "label": "Score", "expression": "c"}],
            )

        self.assertEqual([row["author_id"] for row in rows], ["A2"])
        self.assertEqual(query_table.call_args.kwargs["limit"], 0)

    def test_selected_index_rows_sorts_custom_metric_in_duckdb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "runs" / "run_custom"
            run_dir.mkdir(parents=True)
            (run_dir / "metric_run.json").write_text(json.dumps({"run_id": "run_custom", "dump_id": "dump_custom"}), encoding="utf-8")
            write_parquet_dicts(
                run_dir / "tables" / "indices.parquet",
                [
                    {"fraction_mode": "integer", "author_id": "A1", "author_display_name": "Author One", "p": 1, "c": 3, "h": 1},
                    {"fraction_mode": "integer", "author_id": "A2", "author_display_name": "Author Two", "p": 5, "c": 9, "h": 3},
                ],
                ["fraction_mode", "author_id", "author_display_name", "p", "c", "h"],
            )

            with (
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "WAREHOUSE", root / "warehouse.duckdb"),
            ):
                rows = warehouse.selected_index_rows(
                    "integer",
                    {},
                    run_id="run_custom",
                    data_sort="custom_weighted",
                    data_limit=1,
                    custom_metric_defs=[{"id": "custom_weighted", "label": "Weighted", "expression": "h + pr_c"}],
                )

        self.assertEqual([row["author_id"] for row in rows], ["A2"])
        self.assertIn("custom_weighted", rows[0])

    def test_selected_index_rows_recomputes_when_work_level_filters_are_present(self) -> None:
        source_rows = [{"author_id": "A1", "author_display_name": "Author One", "h": 3, "p": 1}]
        with (
            patch.object(warehouse, "table_exists", return_value=True),
            patch.object(warehouse, "query_table") as query_table,
            patch.object(warehouse, "filtered_indices", return_value=source_rows) as filtered_indices,
        ):
            rows = warehouse.selected_index_rows("integer", {"country_code": "RU"}, run_id="run_a")

        self.assertEqual(rows, source_rows)
        query_table.assert_not_called()
        filtered_indices.assert_called_once()

    def test_metric_ranking_with_empty_author_id_filter_returns_no_rows(self) -> None:
        rows = [
            {"author_id": "https://openalex.org/A1", "author_display_name": "Author One", "h": 3, "p": 4, "c": 10},
            {"author_id": "https://openalex.org/A2", "author_display_name": "Author Two", "h": 2, "p": 3, "c": 7},
        ]

        with (
            patch.object(warehouse, "filtered_indices", return_value=rows),
            patch.object(warehouse, "resolve_analysis_scope", return_value={"run_id": "run_a", "dump_id": "dump_a"}),
        ):
            ranking = warehouse.metric_ranking("integer", "h", run_id="run_a", author_ids=set())

        self.assertEqual(ranking["rows"], [])
        self.assertEqual(ranking["total"], 0)

    def test_filtered_indices_reads_scoped_parquet_when_csv_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dump_tables(root, "dump_a", "W1", "A1", "Author One", 12)
            _write_run_author_work(root, "run_a", "dump_a", "W1", "A1", "Author One", 12)

            with (
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "WAREHOUSE", root / "warehouse.duckdb"),
            ):
                rows = warehouse.filtered_indices("integer", {"country_code": "RU"}, run_id="run_a")

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["author_display_name"], "Author One")
            self.assertEqual(rows[0]["p"], 1)
            self.assertEqual(rows[0]["h"], 1)
            self.assertAlmostEqual(rows[0]["c_frac"], 12.0)

    def test_filtered_analytics_cache_hits_and_prunes_under_run_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dump_tables(root, "dump_a", "W1", "A1", "Author One", 12)
            _write_run_author_work(root, "run_a", "dump_a", "W1", "A1", "Author One", 12)

            with (
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "WAREHOUSE", root / "warehouse.duckdb"),
                patch.object(warehouse, "_ANALYTICS_CACHE_LIMIT", 1),
            ):
                first = warehouse.metric_ranking("integer", "h", {"country_code": "RU"}, run_id="run_a")
                second = warehouse.metric_ranking("integer", "h", {"country_code": "RU"}, run_id="run_a")
                cache_dirs = list((root / "runs" / "run_a" / "analytics" / "filtered").glob("*/manifest.json"))

            self.assertEqual(first["analytics_cache"]["status"], "miss")
            self.assertEqual(second["analytics_cache"]["status"], "hit")
            self.assertEqual(second["analytics_cache"]["rows"], 1)
            self.assertEqual(len(cache_dirs), 1)

    def test_run_scoped_metric_ranking_uses_requested_run_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dump_tables(root, "dump_a", "W_A", "A_A", "Author A", 5)
            _write_dump_tables(root, "dump_b", "W_B", "A_B", "Author B", 50)
            _write_run_author_work(root, "run_a", "dump_a", "W_A", "A_A", "Author A", 5)
            _write_run_author_work(root, "run_b", "dump_b", "W_B", "A_B", "Author B", 50)

            with (
                patch.object(warehouse, "DATA", root),
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

    def test_list_tables_does_not_synthesize_missing_run_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run_author_work(root, "run_a", "dump_a", "W_A", "A_A", "Author A", 5)

            with (
                patch.object(warehouse, "DATA", root),
            ):
                tables = warehouse.list_tables(run_id="run_a")

        self.assertEqual(tables["indices"]["scope"], "run")
        self.assertEqual(tables["indices"]["path"], "")
        self.assertEqual(tables["indices"]["resolved_path"], "")
        self.assertFalse(tables["indices"]["exists"])

    def test_list_tables_without_scope_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with (
                patch.object(warehouse, "DATA", root),
            ):
                tables = warehouse.list_tables()

        self.assertEqual(tables, {})

    def test_query_table_returns_resolved_dump_id_for_run_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dump_tables(root, "dump_a", "W_A", "A_A", "Author A", 5)
            _write_run_author_work(root, "run_a", "dump_a", "W_A", "A_A", "Author A", 5)

            with (
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "WAREHOUSE", root / "warehouse.duckdb"),
            ):
                table = warehouse.query_table("works", run_id="run_a")

        self.assertEqual(table["run_id"], "run_a")
        self.assertEqual(table["dump_id"], "dump_a")
        self.assertEqual(table["total"], 1)
        self.assertTrue(table["source_path"].endswith("tables/dump_a/works.parquet"))

    def test_query_registered_table_can_skip_exact_total(self) -> None:
        with warehouse.duckdb.connect(":memory:") as conn:
            conn.execute("CREATE TABLE indices(author_id VARCHAR, h INTEGER)")
            conn.executemany("INSERT INTO indices VALUES (?, ?)", [("A1", 1), ("A2", 2), ("A3", 3)])
            payload = warehouse._query_registered_table(
                conn,
                "indices",
                ["author_id", "h"],
                sort="h",
                direction="asc",
                limit=2,
                include_total=False,
            )

        self.assertIsNone(payload["total"])
        self.assertEqual(payload["total_exact"], False)
        self.assertEqual(payload["has_more"], True)
        self.assertEqual(payload["next_offset"], 2)
        self.assertEqual([row["author_id"] for row in payload["rows"]], ["A1", "A2"])

    def test_run_metric_params_do_not_fallback_to_global_passport_when_run_passport_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            global_passport = root / "passports" / "calculation_passport.json"
            global_passport.parent.mkdir(parents=True)
            global_passport.write_text(json.dumps({"lrdi": {"p0": 99, "lambda": 0.99, "analysis_year": 1999}}), encoding="utf-8")

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

            with (
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "WAREHOUSE", root / "warehouse.duckdb"),
            ):
                detail = warehouse.author_detail("https://openalex.org/A_A", run_id="run_a")

            self.assertEqual(detail["dump_id"], "dump_a")
            self.assertEqual([row["work_id"] for row in detail["works"]], ["https://openalex.org/W_A"])

    def test_topics_any_filter_uses_work_topics_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dump_tables(root, "dump_a", "W_A", "A_A", "Author A", 5)
            _write_run_author_work(root, "run_a", "dump_a", "W_A", "A_A", "Author A", 5)
            write_parquet_dicts(
                root / "tables" / "dump_a" / "work_topics.parquet",
                [
                    {
                        "work_id": "https://openalex.org/W_A",
                        "topic_id": "https://openalex.org/T9",
                        "topic_display_name": "Secondary topic",
                        "score": 0.6,
                        "subfield_id": "https://openalex.org/subfields/9999",
                        "field_id": "https://openalex.org/fields/99",
                        "domain_id": "https://openalex.org/domains/9",
                        "is_primary": False,
                    }
                ],
                ["work_id", "topic_id", "topic_display_name", "score", "subfield_id", "field_id", "domain_id", "is_primary"],
            )

            with (
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "WAREHOUSE", root / "warehouse.duckdb"),
            ):
                primary = warehouse.metric_ranking("integer", "h", {"filter_mode": "primary_topic", "subject_level": "subfield", "subject_id": "9999"}, run_id="run_a")
                topics_any = warehouse.metric_ranking("integer", "h", {"filter_mode": "topics_any", "subject_level": "subfield", "subject_id": "9999"}, run_id="run_a")

            self.assertEqual(primary["total"], 0)
            self.assertEqual(topics_any["total"], 1)
            self.assertEqual(topics_any["rows"][0]["author_display_name"], "Author A")

    def test_text_search_filter_uses_local_work_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dump_tables(root, "dump_a", "W_A", "A_A", "Author A", 5)
            _write_run_author_work(root, "run_a", "dump_a", "W_A", "A_A", "Author A", 5)

            with (
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "WAREHOUSE", root / "warehouse.duckdb"),
            ):
                matched = warehouse.metric_ranking("integer", "h", {"filter_mode": "search", "text_search_query": "Work W_A"}, run_id="run_a")
                missing = warehouse.metric_ranking("integer", "h", {"filter_mode": "search", "text_search_query": "no such title"}, run_id="run_a")

            self.assertEqual(matched["total"], 1)
            self.assertEqual(missing["total"], 0)

    def test_doi_filter_matches_normalized_local_work_doi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dump_tables(root, "dump_a", "W_A", "A_A", "Author A", 5)
            _write_run_author_work(root, "run_a", "dump_a", "W_A", "A_A", "Author A", 5)

            with (
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "WAREHOUSE", root / "warehouse.duckdb"),
            ):
                matched = warehouse.metric_ranking("integer", "h", {"doi": "doi:10.123/w_a"}, run_id="run_a")
                missing = warehouse.metric_ranking("integer", "h", {"doi": "10.999/missing"}, run_id="run_a")

            self.assertEqual(matched["total"], 1)
            self.assertEqual(missing["total"], 0)

    def test_current_affiliation_filter_is_not_silently_applied_to_historical_authorships(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dump_tables(root, "dump_a", "W_A", "A_A", "Author A", 5)
            _write_run_author_work(root, "run_a", "dump_a", "W_A", "A_A", "Author A", 5)

            with (
                patch.object(warehouse, "DATA", root),
                patch.object(warehouse, "WAREHOUSE", root / "warehouse.duckdb"),
            ):
                with self.assertRaises(ValueError) as raised:
                    warehouse.metric_ranking("integer", "h", {"affiliation_mode": "current", "country_code": "RU"}, run_id="run_a")

            self.assertIn("affiliation_mode=current", str(raised.exception))

def _write_dump_tables(root: Path, dump_id: str, work_id: str, author_id: str, author_name: str, citations: int) -> None:
    base = root / "tables" / dump_id
    write_parquet_dicts(
        base / "works.parquet",
        [
            {
                "work_id": f"https://openalex.org/{work_id}",
                "doi": f"https://doi.org/10.123/{work_id.lower()}",
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
            "doi",
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
