from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps/api"
SRC = ROOT / "src"
for path in (API, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.api.routes import local_data  # noqa: E402


class LocalDataRouteTests(unittest.TestCase):
    def test_local_data_summary_returns_only_whitelisted_kinds(self) -> None:
        with patch.object(
            local_data.warehouse,
            "list_tables",
            return_value={
                "works": {"rows": 2, "run_id": "run_a", "dump_id": "dump_a", "exists": True},
                "indices": {"rows": 3, "run_id": "run_a", "dump_id": "dump_a", "exists": True},
                "unknown_table": {"rows": 99, "run_id": "run_a", "dump_id": "dump_a"},
            },
        ):
            payload = local_data.local_data_summary(run_id="run_a")

        self.assertEqual(set(payload["tables"]), {"works", "authorships", "work_topics", "author_work", "indices", "ratings"})
        self.assertNotIn("unknown_table", payload["tables"])
        self.assertEqual(payload["tables"]["works"]["label"], "Работы")
        self.assertEqual(payload["tables"]["authorships"]["rows"], 0)
        self.assertEqual(payload["tables"]["authorships"]["exists"], False)
        self.assertEqual([item["kind"] for item in payload["kinds"]], ["indices", "works"])
        self.assertEqual(payload["run_id"], "run_a")
        self.assertEqual(payload["dump_id"], "dump_a")
        self.assertEqual(payload["scope_status"], "explicit_scope")
        self.assertEqual(payload["reproducible"], True)
        self.assertEqual(payload["warnings"], [])

    def test_local_data_summary_without_scope_requires_scope(self) -> None:
        with patch.object(local_data.warehouse, "list_tables") as list_tables:
            with self.assertRaises(local_data.HTTPException) as raised:
                local_data.local_data_summary()

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("run_id or dump_id is required", str(raised.exception.detail))
        list_tables.assert_not_called()

    def test_local_data_preview_queries_whitelisted_kind(self) -> None:
        with (
            patch.object(local_data.warehouse, "table_exists", return_value=True),
            patch.object(
                local_data.warehouse,
                "query_table",
                return_value={"table": "indices", "fields": ["author_id", "h"], "rows": [{"author_id": "A1", "h": 3}], "total": 1, "limit": 25, "offset": 0},
            ) as query_table,
        ):
            payload = local_data.local_data_preview(kind="indices", run_id="run_a", dump_id="dump_a", q="Author", limit=25, offset=0)

        self.assertEqual(payload["kind"], "indices")
        self.assertEqual(payload["label"], "Авторы и индексы")
        self.assertEqual(payload["scope_status"], "explicit_scope")
        self.assertEqual(payload["reproducible"], True)
        self.assertEqual(payload["warnings"], [])
        query_table.assert_called_once_with(
            "indices",
            run_id="run_a",
            dump_id="dump_a",
            q="Author",
            fraction_mode="",
            metric="",
            author_id="",
            work_id="",
            sort="",
            direction="desc",
            limit=25,
            offset=0,
        )

    def test_local_data_preview_zero_limit_uses_safe_preview_page(self) -> None:
        with (
            patch.object(local_data.warehouse, "table_exists", return_value=True),
            patch.object(
                local_data.warehouse,
                "query_table",
                return_value={"table": "indices", "fields": ["author_id"], "rows": [], "total": 10_000, "limit": 100, "offset": 0},
            ) as query_table,
        ):
            payload = local_data.local_data_preview(kind="indices", run_id="run_a", limit=0, offset=0)

        query_table.assert_called_once()
        self.assertEqual(query_table.call_args.kwargs["limit"], local_data.PREVIEW_DEFAULT_ROWS)
        self.assertEqual(payload["requested_limit"], 0)
        self.assertEqual(payload["preview_limit"], local_data.PREVIEW_DEFAULT_ROWS)
        self.assertEqual(payload["truncated_for_preview"], True)

    def test_local_data_preview_without_scope_requires_scope(self) -> None:
        with patch.object(
            local_data.warehouse,
            "query_table",
            return_value={"table": "indices", "fields": ["author_id", "h"], "rows": [], "total": 0, "limit": 25, "offset": 0},
        ) as query_table:
            with self.assertRaises(local_data.HTTPException) as raised:
                local_data.local_data_preview(kind="indices", limit=25, offset=0)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("run_id or dump_id is required", str(raised.exception.detail))
        query_table.assert_not_called()

    def test_local_data_preview_rejects_missing_table_in_selected_scope(self) -> None:
        with (
            patch.object(local_data.warehouse, "table_exists", return_value=False),
            patch.object(local_data.warehouse, "query_table") as query_table,
        ):
            with self.assertRaises(local_data.HTTPException) as raised:
                local_data.local_data_preview(kind="indices", run_id="run_a", dump_id="dump_a", limit=25, offset=0)

        self.assertEqual(raised.exception.status_code, 404)
        self.assertIn("отсутствует", str(raised.exception.detail))
        query_table.assert_not_called()

    def test_local_data_preview_rejects_unknown_kind(self) -> None:
        with self.assertRaises(local_data.HTTPException) as raised:
            local_data.local_data_preview(kind="unknown_table")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Unsupported local data kind", str(raised.exception.detail))

    def test_local_data_preview_csv_uses_whitelisted_kind(self) -> None:
        with (
            patch.object(local_data.warehouse, "table_exists", return_value=True),
            patch.object(local_data.warehouse, "export_table_csv", return_value="author_id,h\nA1,3\n") as export_table_csv,
        ):
            response = local_data.local_data_preview_csv(kind="indices", run_id="run_a", limit=1000, offset=0)

        self.assertIn("openalex_dss_local_data_indices.csv", response.headers["Content-Disposition"])
        self.assertEqual(response.headers["X-OpenAlex-DSS-Scope-Status"], "explicit_scope")
        self.assertEqual(response.headers["X-OpenAlex-DSS-Reproducible"], "true")
        self.assertEqual(response.body.decode("utf-8"), "author_id,h\nA1,3\n")
        export_table_csv.assert_called_once_with(
            "indices",
            run_id="run_a",
            dump_id="",
            q="",
            fraction_mode="",
            metric="",
            author_id="",
            work_id="",
            sort="",
            direction="desc",
            limit=1000,
            offset=0,
        )

    def test_local_data_preview_csv_without_scope_requires_scope(self) -> None:
        with self.assertRaises(local_data.HTTPException) as raised:
            local_data.local_data_preview_csv(kind="indices", limit=1000, offset=0)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("run_id or dump_id is required", str(raised.exception.detail))


if __name__ == "__main__":
    unittest.main()
