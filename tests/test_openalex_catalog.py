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

from app.services import metadata_store, openalex_catalog  # noqa: E402


class OpenAlexCatalogTests(unittest.TestCase):
    def test_countries_use_openalex_countries_endpoint_without_local_alias_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.sqlite"
            with (
                patch.object(metadata_store, "DB_PATH", db_path),
                patch.object(openalex_catalog.metadata_store, "DB_PATH", db_path),
                patch.object(openalex_catalog, "_get") as get_json,
            ):
                get_json.return_value = {
                    "results": [
                        {
                            "id": "https://openalex.org/countries/RU",
                            "display_name": "Russia",
                            "country_code": "RU",
                            "works_count": 10,
                        }
                    ]
                }

                result = openalex_catalog.search_countries("RU", limit=5)

                self.assertEqual(result["results"][0]["id"], "RU")
                self.assertIn("Russia", result["results"][0]["name"])
                get_json.assert_any_call(
                    "countries",
                    {
                        "page": "1",
                        "per_page": "100",
                        "select": "id,display_name,country_code,works_count",
                        "sort": "works_count:desc",
                    },
                )

    def test_work_lookup_accepts_doi_for_point_enrichment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.sqlite"
            with (
                patch.object(metadata_store, "DB_PATH", db_path),
                patch.object(openalex_catalog.metadata_store, "DB_PATH", db_path),
                patch.object(openalex_catalog, "_get_single") as get_single,
                patch.object(openalex_catalog, "_get") as get_json,
            ):
                get_single.return_value = {
                    "id": "https://openalex.org/W2741809807",
                    "doi": "https://doi.org/10.7717/peerj.4375",
                    "display_name": "Example work",
                    "publication_year": 2024,
                    "type": "article",
                    "cited_by_count": 12,
                }
                get_json.return_value = {"results": []}

                result = openalex_catalog.search_works("10.7717/peerj.4375", limit=5)

                self.assertEqual(result["results"][0]["id"], "W2741809807")
                self.assertEqual(result["results"][0]["level"], "work")
                self.assertEqual(result["results"][0]["doi"], "https://doi.org/10.7717/peerj.4375")

    def test_group_catalog_sync_uses_openalex_page_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "metadata.sqlite"
            with (
                patch.object(metadata_store, "DB_PATH", db_path),
                patch.object(openalex_catalog.metadata_store, "DB_PATH", db_path),
                patch.object(openalex_catalog, "_get") as get_json,
            ):
                get_json.return_value = {
                    "group_by": [
                        {"key": "article", "key_display_name": "article", "count": 10},
                    ]
                }

                result = openalex_catalog._sync_group_catalog("work_type", "type")

                self.assertEqual(result["inserted"], 1)
                get_json.assert_called_once_with("works", {"group_by": "type", "per_page": "100"})


if __name__ == "__main__":
    unittest.main()
