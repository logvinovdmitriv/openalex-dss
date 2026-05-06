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
                "works": {"rows": 2, "run_id": "run_a", "dump_id": "dump_a"},
                "indices": {"rows": 3, "run_id": "run_a", "dump_id": "dump_a"},
                "top1_sensitivity": {"rows": 99, "run_id": "run_a", "dump_id": "dump_a"},
            },
        ):
            payload = local_data.local_data_summary(run_id="run_a")

        self.assertEqual(set(payload["tables"]), {"works", "authorships", "work_topics", "author_work", "indices", "ratings"})
        self.assertNotIn("top1_sensitivity", payload["tables"])
        self.assertEqual(payload["tables"]["works"]["label"], "Работы")
        self.assertEqual(payload["tables"]["authorships"]["rows"], 0)
        self.assertEqual(payload["tables"]["authorships"]["exists"], False)
        self.assertEqual(payload["run_id"], "run_a")
        self.assertEqual(payload["dump_id"], "dump_a")

    def test_local_data_preview_queries_whitelisted_kind(self) -> None:
        with patch.object(
            local_data.warehouse,
            "query_table",
            return_value={"table": "indices", "fields": ["author_id", "h"], "rows": [{"author_id": "A1", "h": 3}], "total": 1, "limit": 25, "offset": 0},
        ) as query_table:
            payload = local_data.local_data_preview(kind="indices", run_id="run_a", dump_id="dump_a", q="Author", limit=25, offset=0)

        self.assertEqual(payload["kind"], "indices")
        self.assertEqual(payload["label"], "Индексы авторов")
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

    def test_local_data_preview_rejects_unknown_kind(self) -> None:
        with self.assertRaises(local_data.HTTPException) as raised:
            local_data.local_data_preview(kind="top1_sensitivity")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Unsupported local data kind", str(raised.exception.detail))

    def test_local_data_preview_csv_uses_whitelisted_kind(self) -> None:
        with patch.object(local_data.warehouse, "export_table_csv", return_value="author_id,h\nA1,3\n") as export_table_csv:
            response = local_data.local_data_preview_csv(kind="indices", run_id="run_a", limit=1000, offset=0)

        self.assertIn("openalex_dss_local_data_indices.csv", response.headers["Content-Disposition"])
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


if __name__ == "__main__":
    unittest.main()
