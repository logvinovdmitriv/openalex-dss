from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401
from _bootstrap import data_path
from openalex_dss.config import load_config
from openalex_dss.metrics import build_author_work_metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/slice.yaml")
    parser.add_argument("--dump-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--works", default="")
    parser.add_argument("--auth", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    cfg = load_config(args.config)
    dump_tables = Path("data") / "tables" / args.dump_id
    run_tables = Path("data") / "runs" / args.run_id / "tables"
    rows = build_author_work_metrics(
        data_path(args.works or dump_tables / "works.parquet"),
        data_path(args.auth or dump_tables / "authorships.parquet"),
        data_path(args.out or run_tables / "author_work.csv"),
        cfg.fraction_modes,
        run_id=args.run_id,
    )
    print(f"author_work_rows={len(rows)}")


if __name__ == "__main__":
    main()
