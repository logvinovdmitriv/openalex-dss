from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401
from _bootstrap import data_path
from openalex_mvp.config import load_config
from openalex_mvp.openalex import fetch_works_slice_dump


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download a compact reproducible OpenAlex Works slice as raw JSONL plus a slice passport."
    )
    parser.add_argument("--config", default="config/slice.yaml")
    parser.add_argument("--out-dir", default=None, help="Default: data/raw/openalex_slices/{slice_name}")
    parser.add_argument("--max-records", type=int, default=None, help="Default: max_works from config")
    parser.add_argument("--max-bytes", type=int, default=500 * 1024 * 1024)
    parser.add_argument("--raw-filename", default="works.jsonl")
    parser.add_argument("--passport-filename", default="slice_passport.json")
    args = parser.parse_args()

    cfg = load_config(args.config)
    passport = fetch_works_slice_dump(
        cfg,
        data_path(args.out_dir) if args.out_dir else None,
        max_records=args.max_records,
        max_bytes=args.max_bytes,
        raw_filename=args.raw_filename,
        passport_filename=args.passport_filename,
    )
    print(f"downloaded_records={passport['records_downloaded']}")
    print(f"stop_reason={passport['stop_reason']}")
    print(f"raw_jsonl={passport['raw_jsonl']}")
    print(f"raw_jsonl_sha256={passport['raw_jsonl_sha256']}")


if __name__ == "__main__":
    main()
