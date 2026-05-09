from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import _path  # noqa: F401
from openalex_dss.config import load_config, replace_config
from openalex_dss.io_utils import read_table_dicts, write_parquet_dicts
from openalex_dss.metrics import build_author_work_metrics, compute_indices
from openalex_dss.normalize import normalize_raw
from openalex_dss.openalex import build_filter, download_consistency, estimate_works
from openalex_dss.passports import build_passports
from openalex_dss.ranking import build_ratings


class EdgeCaseTests(unittest.TestCase):
    def test_top_n_overlap_uses_available_denominator(self) -> None:
        a = {"a1": 1, "a2": 2}
        b = {"a1": 1, "a2": 2}
        self.assertEqual(_top_n_overlap(a, b, 20), 1.0)

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

    def test_optimized_metric_pipeline_writes_outputs_without_returning_rows(self) -> None:
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

            mart_rows = build_author_work_metrics(
                root / "works.csv",
                root / "auth.csv",
                root / "awm.csv",
                ("integer",),
                return_rows=False,
            )
            index_rows = compute_indices(root / "awm.csv", root / "indices.csv", return_rows=False)
            rating_rows = build_ratings(root / "indices.csv", root / "ratings.csv", metrics=("h",), return_rows=False)

            indices = read_table_dicts(root / "indices.csv")
            ratings = read_table_dicts(root / "ratings.csv")

        self.assertEqual(mart_rows, [])
        self.assertEqual(index_rows, [])
        self.assertEqual(rating_rows, [])
        self.assertEqual(len(indices), 2)
        self.assertEqual(len(ratings), 2)
        self.assertEqual([row["author_id"] for row in ratings], ["https://openalex.org/A1", "https://openalex.org/A2"])

    def test_optimized_indices_read_quoted_author_names_from_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            author_work = root / "author_work.csv"
            author_work.write_text(
                "\n".join(
                    [
                        "run_id,fraction_mode,work_id,author_id,author_display_name,publication_year,cited_by_count,authors_count_used,credit_weight,cited_credit,single_authored_flag,qf_any,qf_authorship_truncated,qf_null_omission,omitted_author_fraction",
                        'run_a,integer,W1,A1,"M.Ed., B.Ed., Independent Researcher",2026,1.0,1.0,1.0,1.0,true,false,false,false,',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            compute_indices(author_work, root / "indices.csv", return_rows=False)
            rows = read_table_dicts(root / "indices.csv")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["author_display_name"], "M.Ed., B.Ed., Independent Researcher")
        self.assertEqual(rows[0]["p"], "1")

    def test_parquet_writer_stabilizes_mixed_openalex_column_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parquet = root / "table.parquet"
            rows = [
                {"id": "W1", "score": 1, "metadata": {"source": "fixture"}},
                {"id": "W2", "score": 0.5, "metadata": ["unexpected", "shape"]},
            ]

            count = write_parquet_dicts(parquet, rows, ["id", "score", "metadata"])
            if count == 0:
                self.skipTest("polars is not installed")

            loaded = read_table_dicts(parquet)

        self.assertEqual(count, 2)
        self.assertEqual([row["id"] for row in loaded], ["W1", "W2"])
        self.assertEqual([row["score"] for row in loaded], [1.0, 0.5])
        self.assertEqual(loaded[0]["metadata"], '{"source": "fixture"}')

    def test_duckdb_table_expression_prefers_parquet_sibling_for_internal_reads(self) -> None:
        from openalex_dss.duckdb_io import table_expression

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "author_work.csv"
            parquet_path = root / "author_work.parquet"
            csv_path.write_text("broken csv placeholder", encoding="utf-8")
            parquet_path.write_text("parquet placeholder", encoding="utf-8")

            expression = table_expression(csv_path)

        self.assertIn("read_parquet", expression)
        self.assertIn("author_work.parquet", expression)

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

    def test_openalex_filter_accepts_pipe_separated_work_types(self) -> None:
        cfg = replace_config(
            load_config(Path(__file__).resolve().parents[1] / "config/slice.yaml"),
            work_type="article|review|conference-paper",
        )
        query = build_filter(cfg)
        self.assertIn("type:article|review|conference-paper", query)

    def test_estimate_works_uses_sample_and_facets_without_network(self) -> None:
        cfg = replace_config(load_config(Path(__file__).resolve().parents[1] / "config/slice.yaml"))
        with patch("openalex_dss.openalex._get_json") as get_json:
            get_json.side_effect = [
                {"meta": {"count": 2}, "results": [_work("W1", "A1", 12)]},
                {"meta": {"count": 2}, "results": [_work("W2", "A2", 5), _work("W3", "A3", 3)]},
                {"group_by": [{"key": "article", "key_display_name": "article", "count": 2}]},
                {"group_by": [{"key": "2020", "key_display_name": "2020", "count": 2}]},
                {"group_by": [{"key": "RU", "key_display_name": "Russia", "count": 2}]},
            ]
            estimate = estimate_works(cfg, sample_size=2)
            self.assertEqual(estimate["estimate_count"], 2)
            self.assertEqual(estimate["sample_size"], 2)
            self.assertIn("facets", estimate)
            self.assertEqual(estimate["facets"]["work_types"]["rows"][0]["key"], "article")
            called_params = [call.args[1] for call in get_json.call_args_list]
            self.assertTrue(all("per-page" not in params for params in called_params))
            self.assertTrue(all("has_abstract" not in params.get("select", "") for params in called_params))
            self.assertNotIn("sort", called_params[1])
            self.assertIn("sample", called_params[1])

    def test_estimate_works_maps_openalex_connectivity_failure_to_runtime_error(self) -> None:
        cfg = replace_config(load_config(Path(__file__).resolve().parents[1] / "config/slice.yaml"))
        with patch("openalex_dss.openalex.urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(RuntimeError) as raised:
                estimate_works(cfg, sample_size=2)

        self.assertIn("OpenAlex API is unavailable", str(raised.exception))

    def test_search_mode_is_not_cli_download_compatible(self) -> None:
        cfg = replace_config(
            load_config(Path(__file__).resolve().parents[1] / "config/slice.yaml"),
            filter_mode="search",
            text_search_query="ergonomics",
        )
        result = download_consistency(cfg)
        self.assertFalse(result["compatible"])
        self.assertIn("текстовый поиск", result["reasons"][0])

    def test_build_passports_requires_scoped_primary_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            cfg = replace_config(
                load_config(Path(__file__).resolve().parents[1] / "config/slice.yaml"),
                slice_name="slice_checksum",
            )
            raw_dir = data / "raw/openalex_cli/slice_checksum"
            raw_dir.mkdir(parents=True)
            raw_path = raw_dir / "works.jsonl.gz"
            raw_path.write_bytes(b"compressed-placeholder")
            (raw_dir / "dump_manifest.json").write_text("{}", encoding="utf-8")

            with patch.dict(os.environ, {"OPENALEX_DSS_DATA_DIR": str(data)}):
                with self.assertRaises(ValueError) as raised:
                    build_passports(cfg, Path(__file__).resolve().parents[1])

            self.assertIn("primary_artifacts is required", str(raised.exception))

    def test_build_passports_requires_run_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            artifact = root / "scoped" / "indices.csv"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("scoped indices", encoding="utf-8")
            cfg = replace_config(
                load_config(Path(__file__).resolve().parents[1] / "config/slice.yaml"),
                slice_name="slice_run_scope",
            )

            with patch.dict(os.environ, {"OPENALEX_DSS_DATA_DIR": str(data)}):
                with self.assertRaises(ValueError) as raised:
                    build_passports(
                        cfg,
                        Path(__file__).resolve().parents[1],
                        primary_artifacts={"run/tables/indices.csv": artifact},
                    )

            self.assertIn("run_id is required for run-scoped passport generation", str(raised.exception))

    def test_build_passports_can_checksum_scoped_primary_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            scoped = root / "scoped"
            scoped.mkdir()
            works = scoped / "works.parquet"
            indices = scoped / "indices.csv"
            global_indices = data / "runs" / "global" / "tables" / "indices.csv"
            global_indices.parent.mkdir(parents=True)
            works.write_text("scoped works", encoding="utf-8")
            indices.write_text("scoped indices", encoding="utf-8")
            global_indices.write_text("global indices", encoding="utf-8")
            cfg = replace_config(
                load_config(Path(__file__).resolve().parents[1] / "config/slice.yaml"),
                slice_name="slice_scoped_checksums",
            )

            with patch.dict(os.environ, {"OPENALEX_DSS_DATA_DIR": str(data)}):
                checksums = build_passports(
                    cfg,
                    Path(__file__).resolve().parents[1],
                    run_id="run_a",
                    primary_artifacts={
                        "dump/tables/works.parquet": {"path": str(works)},
                        "run/tables/indices.csv": str(indices),
                    },
                )

            primary = checksums["primary_artifacts"]
            self.assertIn("dump/tables/works.parquet", primary)
            self.assertIn("run/tables/indices.csv", primary)
            self.assertNotIn("data/runs/global/tables/indices.csv", primary)
            manifest = data / "runs/run_a/passports/sha256_manifest.txt"
            self.assertTrue(manifest.is_file())
            self.assertEqual(checksums["sha256_manifest"], "data/runs/run_a/passports/sha256_manifest.txt")
            self.assertFalse((data / "checksums/slice_scoped_checksums/sha256_manifest.txt").exists())
            self.assertTrue(any("scoped dump/run artifacts" in note for note in checksums["notes"]))


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


def _top_n_overlap(rank_a: dict[str, int], rank_b: dict[str, int], n: int) -> float:
    available = min(n, len(rank_a), len(rank_b))
    if available <= 0:
        return 0.0
    top_a = {author for author, _ in sorted(rank_a.items(), key=lambda item: item[1])[:available]}
    top_b = {author for author, _ in sorted(rank_b.items(), key=lambda item: item[1])[:available]}
    return len(top_a & top_b) / float(available)


if __name__ == "__main__":
    unittest.main()
