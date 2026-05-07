from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from _bootstrap import data_path
from openalex_dss.normalize import normalize_raw


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True, help="Path to a fixed OpenAlex Works JSONL/JSONL.GZ dump, for example data/raw/openalex_cli/<slice_id>/works.jsonl.gz")
    parser.add_argument("--works-out", default="data/normalized/works_flat.csv")
    parser.add_argument("--auth-out", default="data/normalized/authorships_flat.csv")
    parser.add_argument("--quality-out", default="data/passports/quality_report.json")
    args = parser.parse_args()

    report = normalize_raw(data_path(args.raw), data_path(args.works_out), data_path(args.auth_out), data_path(args.quality_out))
    print(f"works_rows={report['works_rows']} authorship_rows={report['authorship_rows']}")


if __name__ == "__main__":
    main()
