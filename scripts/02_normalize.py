from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401
from _bootstrap import data_path
from openalex_dss.normalize import normalize_raw


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True, help="Path to a fixed OpenAlex Works JSONL/JSONL.GZ dump, for example data/raw/openalex_cli/<slice_id>/works.jsonl.gz")
    parser.add_argument("--dump-id", required=True)
    parser.add_argument("--works-out", default="")
    parser.add_argument("--auth-out", default="")
    parser.add_argument("--topics-out", default="")
    parser.add_argument("--quality-out", default="")
    args = parser.parse_args()

    dump_root = Path("data") / "dumps" / args.dump_id
    report = normalize_raw(
        data_path(args.raw),
        data_path(args.works_out or dump_root / "normalized" / "works_flat.csv"),
        data_path(args.auth_out or dump_root / "normalized" / "authorships_flat.csv"),
        data_path(args.quality_out or dump_root / "quality_report.json"),
        data_path(args.topics_out or dump_root / "normalized" / "work_topics_flat.csv"),
    )
    print(f"works_rows={report['works_rows']} authorship_rows={report['authorship_rows']}")


if __name__ == "__main__":
    main()
