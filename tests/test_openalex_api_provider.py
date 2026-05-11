from __future__ import annotations

import gzip
import json
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

from app.providers import openalex_api_provider  # noqa: E402
from openalex_dss.config import load_config, replace_config  # noqa: E402
from openalex_dss.openalex import api_cursor_download_signature, corpus_signature  # noqa: E402


class OpenAlexApiProviderTests(unittest.TestCase):
    def test_cursor_download_writes_checkpoint_and_requires_expected_count_for_final(self) -> None:
        cfg = replace_config(load_config(ROOT / "config/slice.yaml"), slice_name="api_checkpoint", filter_mode="primary_topic", entity_level="subfield", entity_id_short="1706")
        pages = [
            {"meta": {"count": 2, "next_cursor": "next"}, "results": [{"id": "https://openalex.org/W1"}]},
            {"meta": {"count": 2, "next_cursor": ""}, "results": []},
        ]

        def fake_get_json(_url: str, _params: dict[str, str]) -> dict[str, object]:
            return pages.pop(0)

        with tempfile.TemporaryDirectory() as tmp, patch.object(openalex_api_provider, "_get_json", side_effect=fake_get_json):
            manifest = openalex_api_provider.download_works_cursor(
                cfg,
                api_key="key",
                out_dir=Path(tmp),
                estimate={
                    "estimate_count": 2,
                    "accepted_estimate_signature": corpus_signature(cfg),
                    "accepted_download_signature": api_cursor_download_signature(cfg),
                },
            )
            checkpoint = json.loads((Path(tmp) / "api_cursor_checkpoint.json").read_text(encoding="utf-8"))
            with gzip.open(Path(tmp) / "works.jsonl.gz", "rt", encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle if line.strip()]

        self.assertEqual(len(rows), 1)
        self.assertEqual(checkpoint["status"], "complete")
        self.assertEqual(manifest["scientific_completeness"], "partial_count_mismatch")
        self.assertFalse(manifest["allowed_for_final_analysis"])
        self.assertFalse(manifest["records_count_verified"])

    def test_collect_ids_cursor_uses_searchable_cursor_pages(self) -> None:
        cfg = replace_config(load_config(ROOT / "config/slice.yaml"), slice_name="ids_search", filter_mode="search", text_search_query="graph neural")
        calls: list[dict[str, str]] = []

        def fake_get_json(_url: str, params: dict[str, str]) -> dict[str, object]:
            calls.append(params)
            return {"meta": {"count": 1, "next_cursor": ""}, "results": [{"id": "https://openalex.org/W123"}]}

        with patch.object(openalex_api_provider, "_get_json", side_effect=fake_get_json):
            ids = openalex_api_provider.collect_work_ids_cursor(cfg, api_key="key")

        self.assertEqual(ids, ["W123"])
        self.assertEqual(calls[0]["select"], "id")
        self.assertEqual(calls[0]["search"], "graph neural")

    def test_cursor_download_rejects_non_advancing_cursor(self) -> None:
        cfg = replace_config(load_config(ROOT / "config/slice.yaml"), slice_name="api_cursor_loop", filter_mode="primary_topic", entity_level="subfield", entity_id_short="1706")

        def fake_get_json(_url: str, _params: dict[str, str]) -> dict[str, object]:
            return {"meta": {"count": 2, "next_cursor": "*"}, "results": [{"id": "https://openalex.org/W1"}]}

        with tempfile.TemporaryDirectory() as tmp, patch.object(openalex_api_provider, "_get_json", side_effect=fake_get_json):
            with self.assertRaisesRegex(RuntimeError, "cursor did not advance"):
                openalex_api_provider.download_works_cursor(
                    cfg,
                    api_key="key",
                    out_dir=Path(tmp),
                    estimate={
                        "estimate_count": 2,
                        "accepted_estimate_signature": corpus_signature(cfg),
                        "accepted_download_signature": api_cursor_download_signature(cfg),
                    },
                )
