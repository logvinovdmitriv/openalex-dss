from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from _bootstrap import data_path
from openalex_mvp.config import load_config
from openalex_mvp.metrics import build_author_work_metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/slice.yaml")
    parser.add_argument("--works", default="data/normalized/works_flat.csv")
    parser.add_argument("--auth", default="data/normalized/authorships_flat.csv")
    parser.add_argument("--out", default="data/marts/author_work_metrics.csv")
    args = parser.parse_args()

    cfg = load_config(args.config)
    rows = build_author_work_metrics(data_path(args.works), data_path(args.auth), data_path(args.out), cfg.fraction_modes)
    print(f"author_work_metrics_rows={len(rows)}")


if __name__ == "__main__":
    main()
