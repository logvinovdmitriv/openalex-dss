from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from _bootstrap import data_path
from openalex_mvp.config import load_config
from openalex_mvp.openalex import fetch_works


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/slice.yaml")
    parser.add_argument("--out", default="data/raw/works_raw.jsonl")
    parser.add_argument("--meta-out", default="data/passports/fetch_meta.json")
    parser.add_argument("--max-works", type=int, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    meta = fetch_works(cfg, out_path=data_path(args.out), meta_path=data_path(args.meta_out), max_works=args.max_works)
    print(f"fetched_works={meta['fetched_works']} total_available={meta['total_available']}")


if __name__ == "__main__":
    main()
