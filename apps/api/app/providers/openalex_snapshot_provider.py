from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from app.core.paths import DATA, SRC
from app.services import dump_integrity

import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_dss.io_utils import ensure_dir, sha256_file, write_json  # noqa: E402
from openalex_dss.openalex import corpus_request, corpus_signature, download_consistency, download_signature_for_strategy  # noqa: E402


ProgressCallback = Callable[[dict[str, Any]], None]


def scan_snapshot_partitions(
    cfg: Any,
    *,
    snapshot_dir: str | Path,
    out_dir: str | Path | None = None,
    estimate: dict[str, Any] | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_callback: Callable[[], bool] | None = None,
    max_download_bytes: int = 0,
) -> dict[str, Any]:
    """Scan local OpenAlex snapshot JSONL partitions into a scoped raw dump.

    This provider intentionally works only on an already-local snapshot folder.
    It gives the DSS a production path for large/repeated slices without using
    cursor paging as a bulk extraction mechanism.
    """

    estimate = estimate or {}
    source = Path(snapshot_dir).expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"Папка snapshot не найдена: {source}")
    base_dir = ensure_dir(Path(out_dir) if out_dir else DATA / "raw/openalex_snapshot" / cfg.slice_name)
    raw_path = base_dir / "works.jsonl.gz"
    chunks_dir = ensure_dir(base_dir / "snapshot_chunks")
    partition_manifest_path = base_dir / "snapshot_partition_manifest.jsonl"
    started_at = datetime.now(timezone.utc)
    records = 0
    scanned = 0
    bytes_written = 0
    stop_reason = "snapshot_scan_completed"
    partitions = _snapshot_files(source)
    manifest_rows = _read_jsonl_manifest(partition_manifest_path)
    reusable = {
        str(row.get("source_path") or ""): row
        for row in manifest_rows
        if row.get("status") == "ok" and row.get("chunk_path") and Path(str(row.get("chunk_path"))).is_file()
    }
    new_rows: list[dict[str, Any]] = []
    with _download_lock(base_dir):
        for path in partitions:
            reusable_row = reusable.get(str(path))
            if reusable_row and _source_fingerprint(path) == reusable_row.get("source_fingerprint"):
                new_rows.append(reusable_row)
                records += int(reusable_row.get("records") or 0)
                scanned += int(reusable_row.get("records_scanned") or 0)
                bytes_written += int(reusable_row.get("bytes") or 0)
                continue
            if cancel_callback and cancel_callback():
                stop_reason = "user_cancelled"
                break
            chunk_path = chunks_dir / f"{len(new_rows) + 1:08d}_{path.name}.jsonl.gz"
            chunk_records = 0
            chunk_scanned = 0
            parse_errors: list[dict[str, Any]] = []
            with gzip.open(chunk_path, "wt", encoding="utf-8", newline="\n") as handle:
                for row in _iter_jsonl(path, parse_errors=parse_errors):
                    scanned += 1
                    chunk_scanned += 1
                    if not _matches_cfg(cfg, row):
                        continue
                    line = json.dumps(row, ensure_ascii=False, sort_keys=True)
                    handle.write(line + "\n")
                    records += 1
                    chunk_records += 1
                    bytes_written += len((line + "\n").encode("utf-8"))
                    if max_download_bytes > 0 and bytes_written >= max_download_bytes:
                        stop_reason = "size_limit_reached"
                        break
            chunk_bytes = chunk_path.stat().st_size if chunk_path.is_file() else 0
            row_status = "failed" if parse_errors else "ok"
            manifest_row = {
                "partition_no": len(new_rows) + 1,
                "source_path": str(path),
                "source_fingerprint": _source_fingerprint(path),
                "chunk_path": str(chunk_path),
                "records": chunk_records,
                "records_scanned": chunk_scanned,
                "bytes": chunk_bytes,
                "sha256": sha256_file(chunk_path) if chunk_path.is_file() else "",
                "status": row_status,
                "error_count": len(parse_errors),
                "parse_errors": parse_errors[:20],
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            new_rows.append(manifest_row)
            _write_jsonl_manifest(partition_manifest_path, new_rows)
            if parse_errors and stop_reason == "snapshot_scan_completed":
                stop_reason = "snapshot_parse_errors"
            # Continue after parse errors only when the caller explicitly uses
            # the partial/exploratory result; final eligibility will be blocked.
            if stop_reason == "size_limit_reached":
                break
            if progress_callback:
                progress_callback(
                    {
                        "percent": None,
                        "stage": "Сканирование локального OpenAlex snapshot",
                        "partitions_seen": len(partitions),
                        "records_scanned": scanned,
                        "records_downloaded": records,
                        "progress_scope": "download",
                    }
                )
            if stop_reason in {"user_cancelled", "size_limit_reached"}:
                break
        if new_rows:
            _assemble_chunks(raw_path, [Path(str(row["chunk_path"])) for row in new_rows if row.get("chunk_path")])
    checksum = sha256_file(raw_path) if raw_path.is_file() else ""
    finished_at = datetime.now(timezone.utc)
    records_expected = int(estimate.get("estimate_count") or 0)
    count_verified = records > 0 and (records_expected <= 0 or records == records_expected)
    if records <= 0:
        completeness = "empty"
    elif stop_reason in {"user_cancelled", "size_limit_reached", "snapshot_parse_errors"}:
        completeness = "partial"
    elif not count_verified:
        completeness = "partial_count_mismatch"
    else:
        completeness = "complete"
    current_corpus_signature = corpus_signature(cfg)
    source_strategy = "openalex_snapshot_jsonl"
    current_download_signature = download_signature_for_strategy(cfg, source_strategy)
    accepted_estimate_signature = str(estimate.get("accepted_estimate_signature") or "")
    accepted_download_signature = str(estimate.get("accepted_download_signature") or "")
    consistency = download_consistency(cfg, source_strategy)
    allowed_for_final_analysis = (
        bool(consistency.get("compatible"))
        and bool(accepted_estimate_signature and accepted_estimate_signature == current_corpus_signature)
        and bool(accepted_download_signature and accepted_download_signature == current_download_signature)
        and completeness == "complete"
        and count_verified
    )
    manifest = {
        "slice_id": cfg.slice_name,
        "dump_id": f"dump_{checksum[:16]}" if checksum else f"dump_{cfg.slice_name}",
        "source_mode": "openalex_snapshot_partition_scan",
        "source": "Локальный OpenAlex snapshot JSONL",
        "created_at_utc": finished_at.isoformat(),
        "download_started_at_utc": started_at.isoformat(),
        "download_finished_at_utc": finished_at.isoformat(),
        "elapsed_seconds": round((finished_at - started_at).total_seconds(), 3),
        "openalex_request": {**corpus_request(cfg), "content": "snapshot_scan"},
        "signatures": {
            "estimate_signature": current_corpus_signature,
            "download_signature": current_download_signature,
            "corpus_signature": current_corpus_signature,
            "accepted_estimate_signature": accepted_estimate_signature or None,
            "accepted_download_signature": accepted_download_signature or None,
            "estimate_signature_verified": bool(accepted_estimate_signature and accepted_estimate_signature == current_corpus_signature),
            "accepted_estimate_signature_verified": bool(accepted_estimate_signature and accepted_estimate_signature == current_corpus_signature),
            "download_signature_verified": bool(accepted_download_signature and accepted_download_signature == current_download_signature),
            "download_equivalence": consistency.get("download_equivalence"),
            "compatible": bool(consistency.get("compatible")),
        },
        "records_expected": records_expected or None,
        "records_downloaded": records,
        "records_scanned": scanned,
        "records_delta": (records - records_expected) if records_expected else None,
        "records_count_verified": bool(count_verified),
        "no_data": records == 0,
        "bytes_written": raw_path.stat().st_size if raw_path.is_file() else 0,
        "stop_reason": stop_reason,
        "scientific_completeness": completeness,
        "usable_for_exploratory_analysis": records > 0,
        "allowed_for_final_analysis": allowed_for_final_analysis,
        "raw_jsonl": str(raw_path),
        "raw_jsonl_sha256": checksum,
        "snapshot_dir": str(source),
        "snapshot_partitions_seen": len(partitions),
        "snapshot_partition_manifest": str(partition_manifest_path),
        "snapshot_parse_error_count": sum(int(row.get("error_count") or 0) for row in new_rows),
        "used_api_key": False,
        "execution_plan": {
            "strategy": source_strategy,
            "checkpointing": True,
            "checkpoint_path": str(partition_manifest_path),
            "adaptive_rate_limiting": False,
            "parallel_downloads": False,
            "download_signature_verified": bool(accepted_download_signature and accepted_download_signature == current_download_signature),
        },
        "storage_plan": {
            "download_base_dir": str(base_dir),
            "raw_jsonl": str(raw_path),
            "raw_size_mb": round((raw_path.stat().st_size if raw_path.is_file() else 0) / (1024 * 1024), 3),
            "cleanup_policy": "keep_packed_jsonl_gz",
            "kept_raw_files": True,
            "max_download_bytes": max_download_bytes or None,
        },
    }
    manifest = dump_integrity.manifest_with_integrity(manifest, require_expected_count=True)
    write_json(base_dir / "dump_manifest.json", manifest)
    return manifest


def _snapshot_files(root: Path) -> list[Path]:
    return sorted(
        [
            *root.rglob("*.jsonl"),
            *root.rglob("*.jsonl.gz"),
        ]
    )


def _iter_jsonl(path: Path, *, parse_errors: list[dict[str, Any]] | None = None) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                if parse_errors is not None:
                    parse_errors.append({"line": line_no, "error": exc.msg})
                continue
            if isinstance(row, dict):
                yield row
            elif parse_errors is not None:
                parse_errors.append({"line": line_no, "error": "JSON value is not an object"})


def _matches_cfg(cfg: Any, row: dict[str, Any]) -> bool:
    pub_date = str(row.get("publication_date") or "")
    if str(getattr(cfg, "from_publication_date", "") or "") and pub_date and pub_date < str(getattr(cfg, "from_publication_date")):
        return False
    if str(getattr(cfg, "to_publication_date", "") or "") and pub_date and pub_date > str(getattr(cfg, "to_publication_date")):
        return False
    work_types = _cfg_work_types(cfg)
    if work_types and str(row.get("type") or "").lower() not in work_types:
        return False
    if bool(getattr(cfg, "exclude_retracted", True)) and bool(row.get("is_retracted")):
        return False
    if bool(getattr(cfg, "exclude_paratext", True)) and bool(row.get("is_paratext")):
        return False
    if not bool(getattr(cfg, "include_xpac", False)) and bool(row.get("is_xpac")):
        return False
    return _matches_subject(cfg, row)


def _cfg_work_types(cfg: Any) -> set[str]:
    raw = getattr(cfg, "work_type", "")
    if isinstance(raw, str):
        return {item.strip().lower() for item in raw.replace("|", ",").split(",") if item.strip()}
    if isinstance(raw, (list, tuple, set)):
        return {str(item).strip().lower() for item in raw if str(item).strip()}
    return set()


def _matches_subject(cfg: Any, row: dict[str, Any]) -> bool:
    subject_id = str(getattr(cfg, "entity_id_short", "") or getattr(cfg, "subject_id", "") or "").strip()
    if not subject_id:
        return True
    subject_level = str(getattr(cfg, "entity_level", "") or "").lower()
    primary = row.get("primary_topic") if isinstance(row.get("primary_topic"), dict) else {}
    topics = row.get("topics") if isinstance(row.get("topics"), list) else []
    if str(getattr(cfg, "filter_mode", "") or "") == "topics_any":
        return any(_topic_matches(topic, subject_level, subject_id) for topic in topics if isinstance(topic, dict))
    return _topic_matches(primary, subject_level, subject_id)


def _topic_matches(topic: dict[str, Any], level: str, subject_id: str) -> bool:
    if not topic:
        return False
    if level == "topic":
        return _short_id(topic.get("id")) == subject_id
    if level in {"subfield", "field", "domain"}:
        nested = topic.get(level) if isinstance(topic.get(level), dict) else {}
        return _short_id(nested.get("id")) == subject_id
    return False


def _short_id(value: Any) -> str:
    text = str(value or "").strip().rstrip("/")
    return text.rsplit("/", 1)[-1]


def _source_fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{int(stat.st_mtime_ns)}"


def _read_jsonl_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("rt", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _write_jsonl_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wt", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _assemble_chunks(raw_path: Path, chunks: list[Path]) -> int:
    records = 0
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(raw_path, "wt", encoding="utf-8", newline="\n") as output:
        for chunk in chunks:
            with gzip.open(chunk, "rt", encoding="utf-8", newline="\n") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    output.write(line if line.endswith("\n") else line + "\n")
                    records += 1
    return records


class _download_lock:
    def __init__(self, base_dir: Path) -> None:
        self.path = base_dir / ".download.lock"
        self.handle: Any = None

    def __enter__(self) -> "_download_lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover
            pass
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.handle is None:
            return
        try:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except ImportError:  # pragma: no cover
            pass
        self.handle.close()
