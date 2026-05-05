from __future__ import annotations

import gzip
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from app.core.paths import DATA, SRC

import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_mvp.io_utils import ensure_dir, sha256_file, write_json  # noqa: E402
from openalex_mvp.openalex import build_filter, cli_download_signature, corpus_signature, download_consistency  # noqa: E402


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
    estimate: dict[str, Any] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    status = cli_status()
    if not status["available"]:
        raise RuntimeError("OpenAlex CLI is not installed. Install it locally with: pip install openalex-official")
    if not api_key.strip():
        raise ValueError("OpenAlex CLI mode requires an OpenAlex API key.")

    consistency = download_consistency(cfg)
    if consistency.get("compatible") is False:
        raise ValueError("; ".join(consistency.get("reasons") or []) or "This slice cannot be downloaded through the installed OpenAlex CLI.")

    filter_value = build_filter(cfg)
    if not filter_value:
        raise ValueError("OpenAlex CLI mode requires a concrete OpenAlex filter to avoid unbounded downloads.")

    base_dir = ensure_dir(Path(out_dir) if out_dir else DATA / "raw/openalex_cli" / cfg.slice_name)
    files_dir = ensure_dir(base_dir / "files")
    raw_path = base_dir / "works.jsonl.gz"
    dump_manifest_path = base_dir / "dump_manifest.json"
    stdout_path = base_dir / "openalex_cli_stdout.log"
    stderr_path = base_dir / "openalex_cli_stderr.log"
    manifest_path = base_dir / "files_manifest.json"
    started_at = datetime.now(timezone.utc)
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
    cli_version = _cli_version(str(status["executable"]))
    current_corpus_signature = corpus_signature(cfg)
    current_download_signature = cli_download_signature(cfg)
    estimate_signature = str((estimate or {}).get("estimate_signature") or current_corpus_signature)
    accepted_estimate_signature = str((estimate or {}).get("accepted_estimate_signature") or "")
    accepted_download_signature = str((estimate or {}).get("accepted_download_signature") or "")
    planned_records = int(((estimate or {}).get("estimate_count") or 0))
    planned_raw_bytes = int(((estimate or {}).get("estimated_cli_metadata_bytes") or (estimate or {}).get("estimated_raw_bytes_p90") or (estimate or {}).get("estimated_raw_bytes") or 0))

    if progress_callback:
        progress_callback({"percent": 30, "stage": "running OpenAlex CLI", "fetched": 0})

    completed = subprocess.run(command, cwd=str(base_dir), text=True, capture_output=True, check=False)
    stdout_path.write_text(completed.stdout or "", encoding="utf-8", newline="\n")
    stderr_path.write_text(completed.stderr or "", encoding="utf-8", newline="\n")
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "OpenAlex CLI failed").strip())

    if progress_callback:
        progress_callback({"percent": 82, "stage": "packing CLI JSON files", "fetched": 0})

    records, files_manifest = _pack_work_json_files(files_dir, raw_path, progress_callback=progress_callback)
    write_json(manifest_path, {"files": files_manifest, "records": records})
    checksum = sha256_file(raw_path)
    dump_id = f"dump_{checksum[:16]}" if checksum else f"dump_{cfg.slice_name}"
    finished_at = datetime.now(timezone.utc)
    actual_raw_bytes = raw_path.stat().st_size
    dump_manifest = {
        "slice_id": cfg.slice_name,
        "dump_id": dump_id,
        "source_mode": "openalex_cli",
        "source": "OpenAlex CLI works metadata",
        "created_at_utc": finished_at.isoformat(),
        "download_started_at_utc": started_at.isoformat(),
        "download_finished_at_utc": finished_at.isoformat(),
        "elapsed_seconds": round((finished_at - started_at).total_seconds(), 3),
        "openalex_request": {
            "filter": filter_value,
            "search": "",
            "command": public_command,
            "content": "metadata_only",
        },
        "openalex_cli": {
            "executable": status["executable"],
            "version": cli_version,
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
        },
        "signatures": {
            "estimate_signature": estimate_signature,
            "download_signature": current_download_signature,
            "corpus_signature": current_corpus_signature,
            "accepted_estimate_signature": accepted_estimate_signature or None,
            "accepted_download_signature": accepted_download_signature or None,
            "estimate_signature_verified": estimate_signature == current_corpus_signature,
            "accepted_estimate_signature_verified": bool(accepted_estimate_signature and accepted_estimate_signature == current_corpus_signature),
            "download_signature_verified": bool(accepted_download_signature and accepted_download_signature == current_download_signature),
            "download_equivalence": consistency.get("download_equivalence"),
            "compatible": bool(consistency.get("compatible")),
        },
        "records_expected": planned_records or None,
        "records_downloaded": records,
        "records_delta": (records - planned_records) if planned_records else None,
        "no_data": records == 0,
        "bytes_written": actual_raw_bytes,
        "estimated_raw_bytes": planned_raw_bytes or None,
        "actual_vs_estimate_ratio": round(actual_raw_bytes / planned_raw_bytes, 4) if planned_raw_bytes else None,
        "stop_reason": "cli_completed",
        "scientific_completeness": "complete",
        "allowed_for_final_analysis": True,
        "raw_jsonl": str(raw_path),
        "raw_jsonl_sha256": checksum,
        "files_manifest": str(manifest_path),
        "used_api_key": True,
        "execution_plan": {
            "strategy": "openalex_cli_filtered_metadata",
            "checkpointing": True,
            "adaptive_rate_limiting": True,
            "parallel_downloads": True,
            "estimate_signature_verified": estimate_signature == current_corpus_signature,
            "accepted_estimate_signature_verified": bool(accepted_estimate_signature and accepted_estimate_signature == current_corpus_signature),
            "download_signature_verified": bool(accepted_download_signature and accepted_download_signature == current_download_signature),
        },
        "storage_plan": {
            "cli_output_dir": str(files_dir),
            "raw_jsonl": str(raw_path),
            "raw_size_mb": round(actual_raw_bytes / (1024 * 1024), 3),
            "cleanup_policy": "keep_cli_files_and_packed_jsonl_gz",
            "kept_raw_files": True,
        },
    }
    write_json(dump_manifest_path, dump_manifest)

    if progress_callback:
        progress_callback({"percent": 95, "stage": "CLI slice packed", "fetched": records})

    return dump_manifest


def _pack_work_json_files(
    files_dir: Path,
    raw_path: Path,
    *,
    strict: bool = True,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    records = 0
    manifest: list[dict[str, Any]] = []
    errors: list[str] = []
    candidates = sorted(path for path in files_dir.rglob("*") if path.is_file() and _supported_metadata_file(path))
    with gzip.open(raw_path, "wt", encoding="utf-8", newline="\n") as handle:
        for index, path in enumerate(candidates, start=1):
            before = records
            error = ""
            try:
                for payload in _iter_work_payloads(path):
                    if not str(payload.get("id") or "").startswith("https://openalex.org/W"):
                        continue
                    handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
                    records += 1
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                error = str(exc)
                errors.append(f"{path.relative_to(files_dir)}: {error}")
            file_records = records - before
            item = {
                "path": str(path.relative_to(files_dir)),
                "bytes": path.stat().st_size,
                "records": file_records,
                "sha256": sha256_file(path) if file_records else "",
                "status": "failed" if error else "ok",
            }
            if error:
                item["parse_error"] = error
            manifest.append(item)
            if progress_callback and (index == len(candidates) or records % 500 == 0):
                progress_callback({"percent": 82, "stage": f"packed {records} works", "fetched": records, "files_seen": index})
    if strict and errors:
        raise ValueError("Failed to parse OpenAlex CLI metadata files: " + "; ".join(errors[:5]))
    return records, manifest


def _supported_metadata_file(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".json") or name.endswith(".jsonl") or name.endswith(".jsonl.gz")


def _iter_work_payloads(path: Path) -> Iterator[dict[str, Any]]:
    if path.name.lower().endswith(".jsonl.gz"):
        with gzip.open(path, "rt", encoding="utf-8", newline="\n") as handle:
            for line_no, line in enumerate(handle, start=1):
                if line.strip():
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        yield payload
                    else:
                        raise ValueError(f"{path.name}:{line_no} is not a JSON object")
        return
    if path.name.lower().endswith(".jsonl"):
        with path.open("rt", encoding="utf-8", newline="\n") as handle:
            for line_no, line in enumerate(handle, start=1):
                if line.strip():
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        yield payload
                    else:
                        raise ValueError(f"{path.name}:{line_no} is not a JSON object")
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        for item in payload["results"]:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(payload, dict):
        yield payload


def _cli_version(executable: str) -> str:
    completed = subprocess.run([executable, "--version"], text=True, capture_output=True, check=False)
    return (completed.stdout or completed.stderr or "").strip()
