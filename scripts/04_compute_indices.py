from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from _bootstrap import data_path
from openalex_dss.config import load_config
from openalex_dss.metrics import compute_indices


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/slice.yaml")
    parser.add_argument("--in", dest="input_path", default="data/marts/author_work_metrics.csv")
    parser.add_argument("--out", default="data/results/author_indices.csv")
    args = parser.parse_args()

    cfg = load_config(args.config)
    rows = compute_indices(data_path(args.input_path), data_path(args.out), n0=cfg.iupv_n0, lam=cfg.iupv_lambda)
    print(f"author_indices_rows={len(rows)}")


if __name__ == "__main__":
    main()
