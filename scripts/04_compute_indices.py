from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from _bootstrap import data_path
from openalex_dss.config import load_config
from openalex_dss.metrics import compute_indices


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/slice.yaml")
    parser.add_argument("--in", dest="input_path", default="data/runs/local/tables/author_work.csv")
    parser.add_argument("--out", default="data/runs/local/tables/indices.csv")
    args = parser.parse_args()

    cfg = load_config(args.config)
    rows = compute_indices(
        data_path(args.input_path),
        data_path(args.out),
        lrdi_p0=cfg.lrdi_p0,
        lrdi_lambda=cfg.lrdi_lambda,
        analysis_year=cfg.analysis_year,
    )
    print(f"indices_rows={len(rows)}")


if __name__ == "__main__":
    main()
