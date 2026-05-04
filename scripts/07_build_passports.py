from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from _bootstrap import data_path
from openalex_mvp.config import load_config
from openalex_mvp.passports import build_passports


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/slice.yaml")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out-dir", default="data/passports")
    args = parser.parse_args()

    cfg = load_config(args.config)
    doc = build_passports(cfg, root=args.root, out_dir=data_path(args.out_dir))
    print(f"checksummed_artifacts={len(doc['primary_artifacts'])}")


if __name__ == "__main__":
    main()
