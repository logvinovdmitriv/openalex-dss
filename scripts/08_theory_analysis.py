from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from _bootstrap import data_path
from openalex_mvp.config import load_config
from openalex_mvp.theory import analyze_theory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/slice.yaml")
    parser.add_argument("--author-work", default="data/marts/author_work_metrics.csv")
    parser.add_argument("--indices", default="data/results/author_indices.csv")
    parser.add_argument("--out-json", default="data/results/theory_validation.json")
    parser.add_argument("--out-dir", default="data/results")
    args = parser.parse_args()

    cfg = load_config(args.config)
    result = analyze_theory(
        author_work_path=data_path(args.author_work),
        indices_path=data_path(args.indices),
        out_json=data_path(args.out_json),
        out_dir=data_path(args.out_dir),
        n0=cfg.iupv_n0,
        lam=cfg.iupv_lambda,
        lrdi_p0=cfg.lrdi_p0,
        lrdi_lambda=cfg.lrdi_lambda,
        analysis_year=cfg.analysis_year,
        default_mode=cfg.fraction_mode_default,
    )
    print(f"theory_version={result['theory_version']} default_mode={result['default_fraction_mode']}")


if __name__ == "__main__":
    main()
