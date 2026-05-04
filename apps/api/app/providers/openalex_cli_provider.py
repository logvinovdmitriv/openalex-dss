from __future__ import annotations

import gzip
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.core.paths import DATA, SRC

import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_mvp.io_utils import ensure_dir, sha256_file, write_json  # noqa: E402
from openalex_mvp.openalex import build_filter  # noqa: E402


def cli_status() -> dict[str, Any]:
    executable = shutil.which("openalex")
    return {
        "available": bool(executable),
        "executable": executable or "",
        "install": "pip install openalex-official",
        "purpose": "official OpenAlex downloader for filtered Works metadata with checkpointing and rate limiting",
    }


def download_works_metadata(
    cfg: Any,
    *,
    api_key: str,
    out_dir: str | Path | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    status = cli_status()
    if not status["available"]:
        raise RuntimeError("OpenAlex CLI is not installed. Install it locally with: pip install openalex-official")
    if not api_key.strip():
        raise ValueError("OpenAlex CLI mode requires an OpenAlex API key.")

    filter_value = build_filter(cfg)
    if not filter_value:
        raise ValueError("OpenAlex CLI mode requires a concrete OpenAlex filter to avoid unbounded downloads.")

    base_dir = ensure_dir(Path(out_dir) if out_dir else DATA / "raw/openalex_cli" / cfg.slice_name)
    files_dir = ensure_dir(base_dir / "files")
    raw_path = base_dir / "works.jsonl.gz"
    passport_path = base_dir / "slice_passport.json"
    command = [
        str(status["executable"]),
        "download",
        "--api-key",
        api_key,
        "--output",
        str(files_dir),
        "--filter",
        filter_value,
    ]
    public_command = [part if part != api_key else "***" for part in command]

    if progress_callback:
        progress_callback({"percent": 30, "stage": "running OpenAlex CLI", "fetched": 0})

    completed = subprocess.run(command, cwd=str(base_dir), text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "OpenAlex CLI failed").strip())

    if progress_callback:
        progress_callback({"percent": 82, "stage": "packing CLI JSON files", "fetched": 0})

    records = _pack_work_json_files(files_dir, raw_path)
    checksum = sha256_file(raw_path)
    passport = {
        "slice_id": cfg.slice_name,
        "source_mode": "openalex_cli",
        "source": "OpenAlex CLI works metadata",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "openalex_request": {
            "filter": filter_value,
            "command": public_command,
            "content": "metadata_only",
        },
        "records_downloaded": records,
        "no_data": records == 0,
        "bytes_written": raw_path.stat().st_size,
        "stop_reason": "cli_completed",
        "scientific_completeness": "complete",
        "allowed_for_final_analysis": True,
        "raw_jsonl": str(raw_path),
        "raw_jsonl_sha256": checksum,
        "used_api_key": True,
        "execution_plan": {
            "strategy": "openalex_cli_filtered_metadata",
            "checkpointing": True,
            "adaptive_rate_limiting": True,
            "parallel_downloads": True,
        },
        "storage_plan": {
            "cli_output_dir": str(files_dir),
            "raw_jsonl": str(raw_path),
            "raw_size_mb": round(raw_path.stat().st_size / (1024 * 1024), 3),
        },
    }
    write_json(passport_path, passport)

    if progress_callback:
        progress_callback({"percent": 95, "stage": "CLI slice packed", "fetched": records})

    return passport


def _pack_work_json_files(files_dir: Path, raw_path: Path) -> int:
    records = 0
    json_files = sorted(path for path in files_dir.rglob("*.json") if path.is_file())
    with gzip.open(raw_path, "wt", encoding="utf-8", newline="\n") as handle:
        for path in json_files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not str(payload.get("id") or "").startswith("https://openalex.org/W"):
                continue
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            records += 1
    return records
