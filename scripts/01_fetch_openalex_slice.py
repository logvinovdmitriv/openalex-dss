from __future__ import annotations

import argparse
import os
from pathlib import Path

import _bootstrap  # noqa: F401
from _bootstrap import data_path
from app.providers.openalex_cli_provider import download_works_metadata
from openalex_dss.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download a reproducible OpenAlex Works slice through the official OpenAlex CLI."
    )
    parser.add_argument("--config", default="config/slice.yaml")
    parser.add_argument("--out-dir", default=None, help="Default: OPENALEX_DSS_DATA_DIR/raw/openalex_cli/{slice_name}")
    parser.add_argument("--api-key", default="", help="Default: environment variable configured by api_key_env")
    args = parser.parse_args()

    cfg = load_config(args.config)
    api_key = args.api_key.strip() or os.environ.get(cfg.api_key_env, "")
    passport = download_works_metadata(
        cfg,
        api_key=api_key,
        out_dir=data_path(args.out_dir) if args.out_dir else None,
    )
    print(f"downloaded_records={passport['records_downloaded']}")
    print(f"stop_reason={passport['stop_reason']}")
    print(f"raw_jsonl={passport['raw_jsonl']}")
    print(f"raw_jsonl_sha256={passport['raw_jsonl_sha256']}")


if __name__ == "__main__":
    main()
