from __future__ import annotations

import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps/api"
SRC = ROOT / "src"
for path in (API, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.providers.openalex_cli_provider import _pack_work_json_files  # noqa: E402
from openalex_mvp.io_utils import read_jsonl  # noqa: E402


class OpenAlexCliProviderTests(unittest.TestCase):
    def test_pack_work_files_accepts_json_jsonl_gz_arrays_and_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = root / "files"
            files.mkdir()
            (files / "one.json").write_text(json.dumps(_work("W1")), encoding="utf-8")
            (files / "array.json").write_text(json.dumps([_work("W2"), {"id": "https://openalex.org/A1"}]), encoding="utf-8")
            (files / "results.json").write_text(json.dumps({"results": [_work("W3")]}), encoding="utf-8")
            (files / "lines.jsonl").write_text(json.dumps(_work("W4")) + "\n", encoding="utf-8")
            with gzip.open(files / "lines.jsonl.gz", "wt", encoding="utf-8") as handle:
                handle.write(json.dumps(_work("W5")) + "\n")

            raw = root / "works.jsonl.gz"
            records, manifest = _pack_work_json_files(files, raw)

            self.assertEqual(records, 5)
            self.assertEqual(len(read_jsonl(raw)), 5)
            self.assertEqual(sum(item["records"] for item in manifest), 5)

    def test_pack_work_files_fails_on_malformed_json_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = root / "files"
            files.mkdir()
            (files / "broken.json").write_text("{not-json", encoding="utf-8")

            with self.assertRaises(ValueError):
                _pack_work_json_files(files, root / "works.jsonl.gz")


def _work(short_id: str) -> dict[str, object]:
    return {"id": f"https://openalex.org/{short_id}", "display_name": short_id}


if __name__ == "__main__":
    unittest.main()
