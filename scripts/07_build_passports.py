from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from openalex_dss.config import load_config
from openalex_dss.passports import build_passports


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/slice.yaml")
    parser.add_argument("--root", default=".")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dump-id", default="")
    parser.add_argument("--primary-artifacts-json", required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    primary_artifacts = json.loads(Path(args.primary_artifacts_json).read_text(encoding="utf-8"))
    doc = build_passports(
        cfg,
        root=args.root,
        run_id=args.run_id,
        dump_id=args.dump_id,
        primary_artifacts=primary_artifacts,
    )
    print(f"checksummed_artifacts={len(doc['primary_artifacts'])}")


if __name__ == "__main__":
    main()
