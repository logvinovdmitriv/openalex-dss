from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from _bootstrap import data_path
from openalex_mvp.io_utils import write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity-type", required=True)
    parser.add_argument("--entity-id-short", required=True)
    parser.add_argument("--entity-id-full", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--out", default="data/passports/resolved_entity.json")
    args = parser.parse_args()

    write_json(
        data_path(args.out),
        {
            "entity_type": args.entity_type,
            "entity_id_short": args.entity_id_short,
            "entity_id_full": args.entity_id_full,
            "display_name": args.display_name,
            "resolution_mode": "manual_verified_input",
        },
    )


if __name__ == "__main__":
    main()
