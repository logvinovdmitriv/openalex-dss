from __future__ import annotations

import gzip
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from app.core.paths import DATA, SRC

import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openalex_dss.io_utils import ensure_dir, sha256_file, write_json  # noqa: E402
from openalex_dss.openalex import API_BASE, build_filter, corpus_request, corpus_signature, download_consistency, download_signature_for_strategy  # noqa: E402


ProgressCallback = Callable[[dict[str, Any]], None]


def download_works_cursor(
    cfg: Any,
    *,
    api_key: str = "",
    out_dir: str | Path | None = None,
    estimate: dict[str, Any] | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_callback: Callable[[], bool] | None = None,
    max_download_bytes: int = 0,
) -> dict[str, Any]:
    base_dir = ensure_dir(Path(out_dir) if out_dir else DATA / "raw/openalex_api" / cfg.slice_name)
    raw_path = base_dir / "works.jsonl.gz"
    checkpoint_path = base_dir / "api_cursor_checkpoint.json"
    started_at = datetime.now(timezone.utc)
    params = _cursor_params(cfg, api_key=api_key)
    return _download_query(
        cfg,
        params=params,
        source_mode="openalex_api_cursor",
        source_label="OpenAlex API cursor",
        raw_path=raw_path,
        base_dir=base_dir,
        checkpoint_path=checkpoint_path,
        started_at=started_at,
        estimate=estimate or {},
        progress_callback=progress_callback,
        cancel_callback=cancel_callback,
        max_download_bytes=max_download_bytes,
        source_strategy="openalex_api",
    )


def collect_work_ids_cursor(
    cfg: Any,
    *,
    api_key: str = "",
    progress_callback: ProgressCallback | None = None,
    cancel_callback: Callable[[], bool] | None = None,
    max_ids: int = 0,
) -> list[str]:
    """Collect OpenAlex Work IDs with the same corpus request before hydration.

    This is the end-to-end bridge for search/complex API discovery workflows:
    the list endpoint is used only to collect stable Work IDs, then singleton
    records are hydrated through ``hydrate_work_ids``.
    """

    params = _cursor_params(cfg, api_key=api_key, select_fields=("id",))
    cursor = "*"
    seen_cursors: set[str] = set()
    ids: list[str] = []
    total = 0
    while cursor:
        if cursor in seen_cursors:
            raise RuntimeError(f"OpenAlex cursor did not advance while collecting work IDs: {cursor}")
        seen_cursors.add(cursor)
        if cancel_callback and cancel_callback():
            break
        payload = _get_json(API_BASE, {**params, "cursor": cursor})
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        if not total:
            total = int(meta.get("count") or 0)
        results = payload.get("results") if isinstance(payload.get("results"), list) else []
        if not results:
            break
        for row in results:
            work_id = str((row if isinstance(row, dict) else {}).get("id") or "").strip()
            if work_id:
                ids.append(work_id.rstrip("/").rsplit("/", 1)[-1])
            if max_ids > 0 and len(ids) >= max_ids:
                cursor = ""
                break
        if progress_callback:
            progress_callback(
                {
                    "percent": round(len(ids) * 100 / max(1, total), 3) if total else None,
                    "stage": "Сбор ID работ OpenAlex перед гидратацией",
                    "fetched": len(ids),
                    "target_records": total or None,
                    "progress_scope": "download",
                }
            )
        if cursor:
            next_cursor = str(meta.get("next_cursor") or "")
            if next_cursor and next_cursor == cursor:
                raise RuntimeError(f"OpenAlex cursor did not advance while collecting work IDs: {cursor}")
            cursor = next_cursor
    return ids


def hydrate_work_ids(
    cfg: Any,
    *,
    work_ids: Iterable[str],
    api_key: str = "",
    out_dir: str | Path | None = None,
    estimate: dict[str, Any] | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_callback: Callable[[], bool] | None = None,
    max_download_bytes: int = 0,
) -> dict[str, Any]:
    ids = [str(item).strip().rstrip("/").rsplit("/", 1)[-1] for item in work_ids if str(item).strip()]
    if not ids:
        raise ValueError("Для режима ids_then_hydrate нужен непустой список OpenAlex work IDs.")
    base_dir = ensure_dir(Path(out_dir) if out_dir else DATA / "raw/openalex_ids" / cfg.slice_name)
    raw_path = base_dir / "works.jsonl.gz"
    started_at = datetime.now(timezone.utc)
    total = len(ids)
    records = 0
    bytes_written = 0
    with gzip.open(raw_path, "wt", encoding="utf-8", newline="\n") as handle:
        for index, work_id in enumerate(ids, start=1):
            if cancel_callback and cancel_callback():
                break
            row = _get_json(f"{API_BASE}/{urllib.parse.quote(work_id)}", _auth_params(api_key))
            line = json.dumps(row, ensure_ascii=False, sort_keys=True)
            handle.write(line + "\n")
            records += 1
            bytes_written += len((line + "\n").encode("utf-8"))
            if progress_callback and (index == total or index % 25 == 0):
                progress_callback(
                    {
                        "percent": round(index * 100 / max(1, total), 3),
                        "stage": "Гидратация работ OpenAlex по ID",
                        "fetched": index,
                        "target_records": total,
                        "progress_scope": "download",
                    }
                )
            if max_download_bytes > 0 and bytes_written >= max_download_bytes:
                break
    return _manifest(
        cfg,
        raw_path=raw_path,
        base_dir=base_dir,
        started_at=started_at,
        source_mode="openalex_ids_then_hydrate",
        source_label="Гидратация работ OpenAlex по ID",
        source_strategy="ids_then_hydrate",
        records_expected=total,
        records_downloaded=records,
        estimate=estimate or {},
        api_key=api_key,
        stop_reason="size_limit_reached" if max_download_bytes > 0 and bytes_written >= max_download_bytes else "api_completed",
    )


def _download_query(
    cfg: Any,
    *,
    params: dict[str, str],
    source_mode: str,
    source_label: str,
    raw_path: Path,
    base_dir: Path,
    checkpoint_path: Path,
    started_at: datetime,
    estimate: dict[str, Any],
    progress_callback: ProgressCallback | None,
    cancel_callback: Callable[[], bool] | None,
    max_download_bytes: int,
    source_strategy: str,
) -> dict[str, Any]:
    checkpoint = _read_checkpoint(checkpoint_path)
    resume_allowed = checkpoint.get("status") == "in_progress" and raw_path.is_file()
    cursor = str(checkpoint.get("next_cursor") or "*") if resume_allowed else "*"
    records = int(checkpoint.get("records_downloaded") or 0) if resume_allowed else 0
    total = int(estimate.get("estimate_count") or 0)
    bytes_written = int(checkpoint.get("bytes_written") or 0) if resume_allowed else 0
    stop_reason = "api_completed"
    mode = "at" if resume_allowed else "wt"
    seen_cursors: set[str] = set()
    with gzip.open(raw_path, mode, encoding="utf-8", newline="\n") as handle:
        while cursor:
            if cursor in seen_cursors:
                raise RuntimeError(f"OpenAlex cursor did not advance while downloading Works: {cursor}")
            seen_cursors.add(cursor)
            if cancel_callback and cancel_callback():
                stop_reason = "user_cancelled"
                _write_checkpoint(
                    checkpoint_path,
                    status="in_progress",
                    next_cursor=cursor,
                    records_downloaded=records,
                    records_expected=total,
                    bytes_written=bytes_written,
                    stop_reason=stop_reason,
                )
                break
            page_params = {**params, "cursor": cursor}
            payload = _get_json(API_BASE, page_params)
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            if not total:
                total = int(meta.get("count") or 0)
            results = payload.get("results") if isinstance(payload.get("results"), list) else []
            if not results:
                break
            for row in results:
                line = json.dumps(row, ensure_ascii=False, sort_keys=True)
                handle.write(line + "\n")
                records += 1
                bytes_written += len((line + "\n").encode("utf-8"))
            if progress_callback:
                percent = round(records * 100 / max(1, total), 3) if total else None
                progress_callback(
                    {
                        "percent": percent,
                        "stage": "Скачивание Works через OpenAlex API cursor",
                        "fetched": records,
                        "target_records": total or None,
                        "resumed": bool(resume_allowed),
                        "progress_scope": "download",
                    }
                )
            if max_download_bytes > 0 and bytes_written >= max_download_bytes:
                stop_reason = "size_limit_reached"
                _write_checkpoint(
                    checkpoint_path,
                    status="in_progress",
                    next_cursor=str(meta.get("next_cursor") or ""),
                    records_downloaded=records,
                    records_expected=total,
                    bytes_written=bytes_written,
                    stop_reason=stop_reason,
                )
                break
            next_cursor = str(meta.get("next_cursor") or "")
            if next_cursor and next_cursor == cursor:
                _write_checkpoint(
                    checkpoint_path,
                    status="in_progress",
                    next_cursor=next_cursor,
                    records_downloaded=records,
                    records_expected=total,
                    bytes_written=bytes_written,
                    stop_reason="cursor_not_advanced",
                )
                raise RuntimeError(f"OpenAlex cursor did not advance while downloading Works: {cursor}")
            cursor = next_cursor
            _write_checkpoint(
                checkpoint_path,
                status="in_progress" if cursor else "complete",
                next_cursor=cursor,
                records_downloaded=records,
                records_expected=total,
                bytes_written=bytes_written,
                stop_reason=stop_reason,
            )
    if stop_reason == "api_completed":
        _write_checkpoint(
            checkpoint_path,
            status="complete",
            next_cursor="",
            records_downloaded=records,
            records_expected=total,
            bytes_written=bytes_written,
            stop_reason=stop_reason,
        )
    return _manifest(
        cfg,
        raw_path=raw_path,
        base_dir=base_dir,
        started_at=started_at,
        source_mode=source_mode,
        source_label=source_label,
        source_strategy=source_strategy,
        records_expected=total,
        records_downloaded=records,
        estimate=estimate,
        api_key=str(params.get("api_key") or ""),
        stop_reason=stop_reason,
        checkpoint_path=checkpoint_path,
    )


def _manifest(
    cfg: Any,
    *,
    raw_path: Path,
    base_dir: Path,
    started_at: datetime,
    source_mode: str,
    source_label: str,
    source_strategy: str,
    records_expected: int,
    records_downloaded: int,
    estimate: dict[str, Any],
    api_key: str,
    stop_reason: str,
    checkpoint_path: Path | None = None,
) -> dict[str, Any]:
    checksum = sha256_file(raw_path) if raw_path.is_file() else ""
    dump_id = f"dump_{checksum[:16]}" if checksum else f"dump_{cfg.slice_name}"
    finished_at = datetime.now(timezone.utc)
    count_verified = records_downloaded > 0 and (records_expected <= 0 or records_downloaded == records_expected)
    if records_downloaded <= 0:
        completeness = "empty"
    elif stop_reason in {"user_cancelled", "size_limit_reached"}:
        completeness = "partial"
    elif not count_verified:
        completeness = "partial_count_mismatch"
    else:
        completeness = "complete"
    current_corpus_signature = corpus_signature(cfg)
    current_download_signature = download_signature_for_strategy(cfg, source_strategy)
    accepted_estimate_signature = str(estimate.get("accepted_estimate_signature") or "")
    accepted_download_signature = str(estimate.get("accepted_download_signature") or "")
    consistency = download_consistency(cfg, source_strategy)
    allowed_for_final_analysis = (
        bool(consistency.get("compatible"))
        and bool(accepted_estimate_signature and accepted_estimate_signature == current_corpus_signature)
        and bool(accepted_download_signature and accepted_download_signature == current_download_signature)
        and records_downloaded > 0
        and completeness == "complete"
        and count_verified
    )
    manifest = {
        "slice_id": cfg.slice_name,
        "dump_id": dump_id,
        "source_mode": source_mode,
        "source": source_label,
        "created_at_utc": finished_at.isoformat(),
        "download_started_at_utc": started_at.isoformat(),
        "download_finished_at_utc": finished_at.isoformat(),
        "elapsed_seconds": round((finished_at - started_at).total_seconds(), 3),
        "openalex_request": {**corpus_request(cfg), "content": "selected_metadata"},
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
        "records_downloaded": records_downloaded,
        "records_delta": (records_downloaded - records_expected) if records_expected else None,
        "records_count_verified": bool(count_verified),
        "no_data": records_downloaded == 0,
        "bytes_written": raw_path.stat().st_size if raw_path.is_file() else 0,
        "estimated_raw_bytes": estimate.get("estimated_selected_api_bytes") or estimate.get("estimated_raw_bytes"),
        "stop_reason": stop_reason,
        "scientific_completeness": completeness,
        "usable_for_exploratory_analysis": records_downloaded > 0,
        "allowed_for_final_analysis": allowed_for_final_analysis,
        "raw_jsonl": str(raw_path),
        "raw_jsonl_sha256": checksum,
        "used_api_key": bool(api_key),
        "execution_plan": {
            "strategy": source_strategy,
            "checkpointing": True,
            "checkpoint_path": str(checkpoint_path) if checkpoint_path else None,
            "adaptive_rate_limiting": True,
            "parallel_downloads": False,
            "download_signature_verified": bool(accepted_download_signature and accepted_download_signature == current_download_signature),
        },
        "storage_plan": {
            "download_base_dir": str(base_dir),
            "raw_jsonl": str(raw_path),
            "raw_size_mb": round((raw_path.stat().st_size if raw_path.is_file() else 0) / (1024 * 1024), 3),
            "cleanup_policy": "keep_packed_jsonl_gz",
            "kept_raw_files": True,
        },
    }
    write_json(base_dir / "dump_manifest.json", manifest)
    return manifest


def _cursor_params(cfg: Any, *, api_key: str, select_fields: tuple[str, ...] | None = None) -> dict[str, str]:
    params = {
        "filter": build_filter(cfg),
        "sort": str(getattr(cfg, "sort", "") or "publication_date:asc,openalex:asc"),
        "per_page": str(max(1, min(int(getattr(cfg, "per_page", 100) or 100), 100))),
        "select": ",".join(select_fields or _select_fields(cfg)),
    }
    if str(getattr(cfg, "filter_mode", "") or "") == "search" and str(getattr(cfg, "text_search_query", "") or "").strip():
        params["search"] = str(getattr(cfg, "text_search_query")).strip()
    params.update(_auth_params(api_key))
    return params


def _select_fields(cfg: Any) -> tuple[str, ...]:
    invalid_select_fields = {"authors_count"}
    required = ("language", "open_access", "authorships", "primary_topic", "topics", "primary_location")
    fields = [field for field in tuple(getattr(cfg, "select_fields", ()) or ()) if field not in invalid_select_fields]
    return tuple(dict.fromkeys([*fields, *required]))


def _auth_params(api_key: str) -> dict[str, str]:
    return {"api_key": api_key.strip()} if api_key.strip() else {}


def _get_json(url: str, params: dict[str, str]) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "openalex-dss-indices/0.1.0"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt >= 4:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"OpenAlex HTTP {exc.code}: {body}") from exc
            time.sleep(min(30.0, 2.0**attempt))
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            if attempt >= 4:
                raise RuntimeError(f"OpenAlex API is unavailable: {exc}") from exc
            time.sleep(min(20.0, 1.5**attempt))
    raise RuntimeError("OpenAlex API request failed")


def _read_checkpoint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_checkpoint(
    path: Path,
    *,
    status: str,
    next_cursor: str,
    records_downloaded: int,
    records_expected: int,
    bytes_written: int,
    stop_reason: str,
) -> None:
    doc = {
        "schema": "openalex_api_cursor_checkpoint",
        "status": status,
        "next_cursor": next_cursor or "",
        "records_downloaded": int(records_downloaded or 0),
        "records_expected": int(records_expected or 0) or None,
        "bytes_written": int(bytes_written or 0),
        "stop_reason": stop_reason,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
