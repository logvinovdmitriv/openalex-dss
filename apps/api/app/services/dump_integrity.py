from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Iterable

from openalex_dss.io_utils import sha256_file


FINAL_COMPLETENESS = {"complete", "full"}


def count_jsonl_records(path: str | Path, *, max_errors: int = 20) -> dict[str, Any]:
    """Read a JSONL/JSONL.GZ dump to the end and return deterministic integrity facts."""

    target = Path(path).expanduser()
    result: dict[str, Any] = {
        "path": str(target),
        "exists": target.is_file(),
        "records": 0,
        "parse_error_count": 0,
        "parse_errors": [],
        "readable": False,
        "sha256": "",
        "bytes": 0,
    }
    if not target.is_file():
        result["parse_errors"].append("raw_jsonl file is missing")
        return result
    result["bytes"] = target.stat().st_size
    opener = gzip.open if target.suffix == ".gz" else open
    try:
        with opener(target, "rt", encoding="utf-8", newline="\n") as handle:
            for line_no, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError as exc:
                    result["parse_error_count"] += 1
                    if len(result["parse_errors"]) < max_errors:
                        result["parse_errors"].append(f"line {line_no}: {exc.msg}")
                    continue
                if not isinstance(payload, dict):
                    result["parse_error_count"] += 1
                    if len(result["parse_errors"]) < max_errors:
                        result["parse_errors"].append(f"line {line_no}: JSON value is not an object")
                    continue
                result["records"] += 1
        result["readable"] = True
    except OSError as exc:
        result["parse_error_count"] += 1
        result["parse_errors"].append(str(exc))
    if result["readable"]:
        result["sha256"] = sha256_file(target)
    return result


def validate_dump_manifest(dump: dict[str, Any], *, require_expected_count: bool = True) -> dict[str, Any]:
    raw_jsonl = str(dump.get("raw_jsonl") or "").strip()
    facts = count_jsonl_records(raw_jsonl) if raw_jsonl else {
        "path": "",
        "exists": False,
        "records": 0,
        "parse_error_count": 1,
        "parse_errors": ["raw_jsonl is not set"],
        "readable": False,
        "sha256": "",
        "bytes": 0,
    }
    errors: list[str] = []
    warnings: list[str] = []
    if not facts["exists"]:
        errors.append("raw_jsonl_missing")
    if not facts["readable"]:
        errors.append("raw_jsonl_unreadable")
    if int(facts["parse_error_count"] or 0) > 0:
        errors.append("raw_jsonl_parse_errors")

    expected_downloaded = _positive_int(dump.get("records_downloaded"))
    expected_total = _positive_int(dump.get("records_expected"))
    actual_records = int(facts.get("records") or 0)
    if expected_downloaded and actual_records != expected_downloaded:
        errors.append("records_downloaded_mismatch")
    if require_expected_count and expected_total and actual_records != expected_total:
        errors.append("records_expected_mismatch")
    if actual_records <= 0:
        errors.append("raw_jsonl_empty")

    expected_sha = str(dump.get("raw_jsonl_sha256") or "").strip()
    actual_sha = str(facts.get("sha256") or "").strip()
    if expected_sha and actual_sha and expected_sha != actual_sha:
        errors.append("raw_jsonl_sha256_mismatch")
    elif not expected_sha and actual_sha:
        warnings.append("raw_jsonl_sha256_missing_in_manifest")

    status = "ok" if not errors else "failed"
    return {
        "schema": "dump_integrity_v1",
        "status": status,
        "ok": status == "ok",
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "raw_jsonl": raw_jsonl,
        "records_actual": actual_records,
        "records_downloaded_manifest": expected_downloaded or None,
        "records_expected_manifest": expected_total or None,
        "records_count_verified": bool(status == "ok" and actual_records > 0 and (not expected_total or actual_records == expected_total)),
        "raw_jsonl_sha256_actual": actual_sha,
        "raw_jsonl_sha256_manifest": expected_sha or None,
        "raw_jsonl_bytes": int(facts.get("bytes") or 0),
        "parse_error_count": int(facts.get("parse_error_count") or 0),
        "parse_errors": list(facts.get("parse_errors") or []),
    }


def manifest_with_integrity(dump: dict[str, Any], *, require_expected_count: bool = True) -> dict[str, Any]:
    integrity = validate_dump_manifest(dump, require_expected_count=require_expected_count)
    updated = dict(dump)
    updated["integrity_validation"] = integrity
    updated["records_actual"] = integrity["records_actual"]
    updated["records_count_verified"] = bool(integrity["records_count_verified"])
    if integrity.get("raw_jsonl_sha256_actual"):
        updated["raw_jsonl_sha256"] = integrity["raw_jsonl_sha256_actual"]
    if integrity["status"] != "ok":
        updated["allowed_for_final_analysis"] = False
        if str(updated.get("scientific_completeness") or "") in FINAL_COMPLETENESS:
            updated["scientific_completeness"] = "partial_integrity_failed"
        updated["quality_gate"] = {
            **(updated.get("quality_gate") if isinstance(updated.get("quality_gate"), dict) else {}),
            "status": "blocked",
            "reason": "dump_integrity_failed",
            "errors": integrity["errors"],
        }
    return updated


def assert_dump_integrity(dump: dict[str, Any], *, require_expected_count: bool = True) -> dict[str, Any]:
    integrity = validate_dump_manifest(dump, require_expected_count=require_expected_count)
    if integrity["status"] != "ok":
        raise ValueError("Некорректный dump_manifest: " + ", ".join(integrity["errors"]))
    return integrity


def summarize_manifest_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = 0
    errors = 0
    bytes_written = 0
    for row in rows:
        records += int(row.get("records") or 0)
        errors += int(row.get("error_count") or (1 if row.get("status") == "failed" else 0) or 0)
        bytes_written += int(row.get("bytes") or 0)
    return {"records": records, "error_count": errors, "bytes": bytes_written}


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0
