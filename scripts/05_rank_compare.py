from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from _bootstrap import data_path
from openalex_dss.ranking import build_ratings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="input_path", default="data/results/author_indices.csv")
    parser.add_argument("--out", default="data/results/rating_positions.csv")
    args = parser.parse_args()

    rows = build_ratings(data_path(args.input_path), data_path(args.out))
    print(f"rating_positions_rows={len(rows)}")


if __name__ == "__main__":
    main()
