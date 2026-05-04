from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from _bootstrap import data_path
from openalex_mvp.stats import analyze_stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--indices", default="data/results/author_indices.csv")
    parser.add_argument("--ranks", default="data/results/rating_positions.csv")
    parser.add_argument("--fig-dir", default="data/results/figures")
    parser.add_argument("--json-out", default="data/results/stats_summary.json")
    args = parser.parse_args()

    summary = analyze_stats(data_path(args.indices), data_path(args.ranks), data_path(args.fig_dir), data_path(args.json_out))
    modes = ",".join(summary["fraction_modes"].keys())
    print(f"stats_modes={modes}")


if __name__ == "__main__":
    main()
