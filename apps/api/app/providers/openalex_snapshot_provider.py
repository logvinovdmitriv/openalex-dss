from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from app.core.paths import DATA, SRC

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
    started_at = datetime.now(timezone.utc)
    records = 0
    scanned = 0
    bytes_written = 0
    stop_reason = "snapshot_scan_completed"
    partitions = _snapshot_files(source)
    with gzip.open(raw_path, "wt", encoding="utf-8", newline="\n") as handle:
        for path in partitions:
            if cancel_callback and cancel_callback():
                stop_reason = "user_cancelled"
                break
            for row in _iter_jsonl(path):
                scanned += 1
                if not _matches_cfg(cfg, row):
                    continue
                line = json.dumps(row, ensure_ascii=False, sort_keys=True)
                handle.write(line + "\n")
                records += 1
                bytes_written += len((line + "\n").encode("utf-8"))
                if max_download_bytes > 0 and bytes_written >= max_download_bytes:
                    stop_reason = "size_limit_reached"
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
    checksum = sha256_file(raw_path) if raw_path.is_file() else ""
    finished_at = datetime.now(timezone.utc)
    records_expected = int(estimate.get("estimate_count") or 0)
    count_verified = records > 0 and (records_expected <= 0 or records == records_expected)
    if records <= 0:
        completeness = "empty"
    elif stop_reason in {"user_cancelled", "size_limit_reached"}:
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
        "used_api_key": False,
        "execution_plan": {
            "strategy": source_strategy,
            "checkpointing": True,
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
    write_json(base_dir / "dump_manifest.json", manifest)
    return manifest


def _snapshot_files(root: Path) -> list[Path]:
    return sorted(
        [
            *root.rglob("*.jsonl"),
            *root.rglob("*.jsonl.gz"),
        ]
    )


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


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
