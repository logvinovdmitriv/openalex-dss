from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.providers import openalex_cli_provider
from openalex_dss.io_utils import iter_jsonl, write_json


StageProgressCallback = Callable[[int | None, str, dict[str, Any] | None], None]
CancelCallback = Callable[[], bool]
FetchWorkCallback = Callable[[str, str], dict[str, Any]]


def backfill_truncated_authorships(
    raw_jsonl: str | Path,
    *,
    api_key: str = "",
    output_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    fetch_work: FetchWorkCallback | None = None,
    progress_callback: StageProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
    max_works: int = 0,
) -> dict[str, Any]:
    source = Path(raw_jsonl).expanduser()
    if not source.is_file():
        raise FileNotFoundError("Файл локального среза для backfill не найден.")
    target = Path(output_path).expanduser() if output_path else _default_output_path(source)
    manifest = Path(manifest_path).expanduser() if manifest_path else target.with_name("backfill_manifest.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)

    total_records, total_candidates = _count_records(source)
    if progress_callback:
        progress_callback(0, "Поиск работ с обрезанным списком авторов", {"total_records": total_records, "backfill_candidates": total_candidates})
    if total_candidates <= 0:
        now = _now()
        checksum = openalex_cli_provider.sha256_file(source)
        payload = {
            "status": "not_required",
            "source_path": str(source),
            "output_path": str(source),
            "manifest_path": str(manifest),
            "records_total": total_records,
            "candidates_total": 0,
            "attempted": 0,
            "replaced": 0,
            "unresolved": 0,
            "sha256": checksum,
            "created_at_utc": now,
            "finished_at_utc": now,
        }
        write_json(manifest, payload)
        return payload

    fetcher = fetch_work or fetch_singleton_work
    started = _now()
    attempted = 0
    replaced = 0
    unresolved = 0
    failed: list[dict[str, str]] = []
    records_written = 0
    candidates_limit = max(0, int(max_works or 0))
    opener = gzip.open if target.suffix == ".gz" else open
    with opener(target, "wt", encoding="utf-8", newline="\n") as out:
        for record_index, work in enumerate(iter_jsonl(source), start=1):
            if cancel_callback and cancel_callback():
                raise RuntimeError("Восстановление authorships остановлено пользователем.")
            needs_backfill = _needs_backfill(work)
            if needs_backfill and (candidates_limit <= 0 or attempted < candidates_limit):
                attempted += 1
                work_id = _work_id(work)
                try:
                    full = fetcher(work_id, api_key)
                except Exception as exc:  # pragma: no cover - network boundary
                    unresolved += 1
                    failed.append({"work_id": work_id, "error": _safe_error(str(exc))})
                else:
                    if _is_better_authorship_record(work, full):
                        work = full
                        replaced += 1
                    else:
                        unresolved += 1
                        failed.append({"work_id": work_id, "error": "singleton record did not contain a fuller authorship list"})
            out.write(json.dumps(work, ensure_ascii=False, separators=(",", ":")) + "\n")
            records_written += 1
            if progress_callback and (record_index == total_records or record_index % 100 == 0 or needs_backfill):
                percent = int(record_index * 100 / total_records) if total_records else None
                progress_callback(
                    percent,
                    "Восстановление singleton work records",
                    {
                        "backfill_percent": percent,
                        "records_processed": record_index,
                        "records_total": total_records,
                        "backfill_candidates": total_candidates,
                        "backfill_attempted": attempted,
                        "backfill_replaced": replaced,
                        "backfill_unresolved": unresolved,
                    },
                )

    checksum = openalex_cli_provider.sha256_file(target)
    status = "complete" if unresolved == 0 and (candidates_limit <= 0 or attempted >= min(total_candidates, candidates_limit)) else "partial"
    payload = {
        "status": status,
        "source_path": str(source),
        "output_path": str(target),
        "manifest_path": str(manifest),
        "records_total": total_records,
        "records_written": records_written,
        "candidates_total": total_candidates,
        "attempted": attempted,
        "replaced": replaced,
        "unresolved": unresolved,
        "failed": failed[:50],
        "sha256": checksum,
        "created_at_utc": started,
        "finished_at_utc": _now(),
    }
    write_json(manifest, payload)
    return payload


def fetch_singleton_work(work_id: str, api_key: str = "", *, attempts: int = 4) -> dict[str, Any]:
    short_id = _short_work_id(work_id)
    if not short_id:
        raise ValueError("Не удалось определить OpenAlex ID работы для восстановления.")
    params = {}
    if str(api_key or "").strip():
        params["api_key"] = str(api_key).strip()
    query = ("?" + urllib.parse.urlencode(params)) if params else ""
    url = f"https://api.openalex.org/works/{urllib.parse.quote(short_id)}{query}"
    last_error = ""
    for attempt in range(max(1, int(attempts))):
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "openalex-dss/1.0"})
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed OpenAlex endpoint
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code == 429 and attempt < attempts - 1:
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else min(30.0, 2.0 ** attempt)
                time.sleep(delay)
                continue
            raise RuntimeError(f"OpenAlex не вернул singleton record для {short_id}: {last_error}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = str(exc)
            if attempt < attempts - 1:
                time.sleep(min(15.0, 1.5 ** attempt))
                continue
            raise RuntimeError(f"OpenAlex singleton record недоступен для {short_id}: {last_error}") from exc
    raise RuntimeError(f"OpenAlex singleton record недоступен для {short_id}: {last_error}")


def _count_records(source: Path) -> tuple[int, int]:
    total = 0
    candidates = 0
    for work in iter_jsonl(source):
        total += 1
        if _needs_backfill(work):
            candidates += 1
    return total, candidates


def _needs_backfill(work: dict[str, Any]) -> bool:
    authorships = work.get("authorships") if isinstance(work.get("authorships"), list) else []
    reported = _reported_authors_count(work)
    return bool(work.get("is_authors_truncated")) or bool(reported and reported > len(authorships))


def _is_better_authorship_record(original: dict[str, Any], candidate: dict[str, Any]) -> bool:
    old_authorships = original.get("authorships") if isinstance(original.get("authorships"), list) else []
    new_authorships = candidate.get("authorships") if isinstance(candidate.get("authorships"), list) else []
    if len(new_authorships) < len(old_authorships):
        return False
    reported = _reported_authors_count(candidate) or _reported_authors_count(original)
    if reported and len(new_authorships) < min(reported, len(old_authorships) + 1):
        return not bool(candidate.get("is_authors_truncated")) and len(new_authorships) >= len(old_authorships)
    return True


def _reported_authors_count(work: dict[str, Any]) -> int:
    for key in ("authors_count", "authors_count_reported"):
        try:
            value = int(work.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return 0


def _work_id(work: dict[str, Any]) -> str:
    return str(work.get("id") or work.get("work_id") or "").strip()


def _short_work_id(work_id: str) -> str:
    raw = str(work_id or "").strip()
    if not raw:
        return ""
    return raw.rstrip("/").split("/")[-1]


def _default_output_path(source: Path) -> Path:
    name = source.name
    if name.endswith(".jsonl.gz"):
        return source.with_name(name[: -len(".jsonl.gz")] + ".backfilled.jsonl.gz")
    if name.endswith(".jsonl"):
        return source.with_name(name[: -len(".jsonl")] + ".backfilled.jsonl.gz")
    return source.with_name(source.name + ".backfilled.jsonl.gz")


def _safe_error(text: str) -> str:
    return str(text or "").replace("\n", " ")[:500]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
