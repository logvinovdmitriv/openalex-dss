#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / ".venv/bin/python"
if (
    not os.environ.get("OPENALEX_DSS_BENCHMARK_REEXEC")
    and VENV_PYTHON.exists()
    and not str(sys.prefix).startswith(str((ROOT / ".venv").resolve()))
):
    os.environ["OPENALEX_DSS_BENCHMARK_REEXEC"] = "1"
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])
API = ROOT / "apps/api"
SRC = ROOT / "src"
for path in (API, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services import pipeline, query_planner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a real OpenAlex slice benchmark with explicit opt-in download.")
    parser.add_argument("--subject-level", default="subfield")
    parser.add_argument("--subject-id", default="2604")
    parser.add_argument("--subject-name", default="Applied Mathematics")
    parser.add_argument("--from-date", default="2020-01-01")
    parser.add_argument("--to-date", default="2024-12-31")
    parser.add_argument("--work-type", default="article")
    parser.add_argument("--source-strategy", default="openalex_api", choices=["openalex_cli", "openalex_api", "api_cursor_selected_fields", "ids_then_hydrate", "openalex_snapshot_jsonl"])
    parser.add_argument("--download", action="store_true", help="Actually download and compute. Without this flag the script only estimates.")
    parser.add_argument("--api-key", default=os.environ.get("OPENALEX_API_KEY", ""))
    parser.add_argument("--max-download-mb", type=float, default=0.0)
    parser.add_argument("--snapshot-dir", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    payload = {
        "slice_name": f"benchmark_{args.subject_level}_{args.subject_id}_{args.from_date}_{args.to_date}",
        "entity_level": args.subject_level,
        "entity_id_short": args.subject_id,
        "entity_display_name": args.subject_name,
        "filter_mode": "primary_topic",
        "from_publication_date": args.from_date,
        "to_publication_date": args.to_date,
        "work_type": args.work_type,
        "exclude_retracted": True,
        "exclude_paratext": True,
        "include_xpac": False,
        "source_strategy": args.source_strategy,
        "api_key": args.api_key,
        "refresh_estimate": True,
    }
    if args.snapshot_dir:
        payload["snapshot_dir"] = args.snapshot_dir
    if args.max_download_mb > 0:
        payload["max_download_mb"] = args.max_download_mb
    started = time.perf_counter()
    plan = query_planner.plan_slice(payload)
    result: dict[str, object] = {
        "status": "estimated",
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "source_strategy": args.source_strategy,
        "estimate": plan.get("estimate"),
        "storage_estimate": plan.get("storage_estimate"),
        "decision": plan.get("decision"),
    }
    if args.download:
        if not args.api_key and args.source_strategy != "openalex_snapshot_jsonl":
            raise SystemExit("OPENALEX_API_KEY or --api-key is required for live download.")
        estimate = plan.get("estimate") if isinstance(plan.get("estimate"), dict) else {}
        payload.update(
            {
                "query_plan": plan,
                "accepted_estimate_signature": estimate.get("estimate_signature"),
                "accepted_download_signature": estimate.get("download_signature"),
            }
        )
        download_started = time.perf_counter()
        run = pipeline.fetch_slice_dump(payload, require_accepted_signatures=True)
        result.update(
            {
                "status": "downloaded",
                "download_elapsed_seconds": round(time.perf_counter() - download_started, 3),
                "dump": run.get("dump"),
            }
        )
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).expanduser().write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
