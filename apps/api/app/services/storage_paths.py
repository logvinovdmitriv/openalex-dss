from __future__ import annotations

import json
from pathlib import Path

from app.core.paths import DATA, TABLE_KINDS


DUMP_TABLES = {"works", "authorships", "work_topics"}
RUN_JSON_DOCS = {
    "fetch_meta": ("passports", "fetch_meta.json"),
    "quality": ("passports", "quality_report.json"),
    "checksums": ("passports", "checksums.json"),
    "pipeline": ("passports", "pipeline_summary.json"),
}


def _data_root(data_root: Path | None = None) -> Path:
    return data_root or DATA


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in str(value).strip())[:140] or "artifact"


def run_dir(run_id: str, *, data_root: Path | None = None) -> Path:
    return _data_root(data_root) / "runs" / safe_id(run_id)


def dump_table_path(dump_id: str, table: str, *, data_root: Path | None = None) -> Path:
    root = _data_root(data_root)
    return root / "tables" / safe_id(resolve_dump_id(dump_id, data_root=root)) / f"{table}.parquet"


def resolve_dump_id(dump_id: str, *, data_root: Path | None = None) -> str:
    raw = str(dump_id or "").strip()
    if not raw:
        return ""
    root = _data_root(data_root)
    safe = safe_id(raw)
    if (root / "tables" / safe).exists() or (root / "dumps" / safe).exists():
        return raw
    if not safe.startswith("dump_"):
        candidate = f"dump_{safe}"
        if (root / "tables" / candidate).exists() or (root / "dumps" / candidate).exists():
            return candidate
    return raw


def run_table_path(run_id: str, table: str, *, data_root: Path | None = None) -> Path | None:
    if table in DUMP_TABLES:
        return None
    candidates = [run_dir(run_id, data_root=data_root) / "tables" / f"{table}{suffix}" for suffix in (".parquet", ".csv")]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def run_json_path(run_id: str, name: str, *, data_root: Path | None = None) -> Path | None:
    base = run_dir(run_id, data_root=data_root)
    parts = RUN_JSON_DOCS.get(name)
    if parts:
        path = base.joinpath(*parts)
        if path.exists():
            return path
    fallback = base / "passports" / f"{name}.json"
    if fallback.exists():
        return fallback
    return None


def dump_id_for_run(run_id: str, *, data_root: Path | None = None) -> str:
    run_id = str(run_id or "").strip()
    if not run_id:
        return ""
    manifest_path = run_dir(run_id, data_root=data_root) / "metric_run.json"
    if not manifest_path.is_file():
        return ""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(manifest.get("input_dump_id") or manifest.get("dump_id") or "")


def recent_run_for_dump(dump_id: str, *, data_root: Path | None = None) -> str:
    root = _data_root(data_root)
    safe_dump = safe_id(resolve_dump_id(dump_id, data_root=root))
    if not safe_dump:
        return ""
    runs_root = root / "runs"
    if not runs_root.is_dir():
        return ""
    candidates: list[tuple[float, str]] = []
    for manifest_path in runs_root.glob("run_*/metric_run.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if safe_id(resolve_dump_id(str(manifest.get("input_dump_id") or manifest.get("dump_id") or ""), data_root=root)) != safe_dump:
            continue
        try:
            mtime = manifest_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((mtime, manifest_path.parent.name))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][1]


def resolve_analysis_scope(*, run_id: str = "", dump_id: str = "", data_root: Path | None = None) -> dict[str, str]:
    root = _data_root(data_root)
    run_id = str(run_id or "").strip()
    dump_id = resolve_dump_id(str(dump_id or "").strip(), data_root=root)
    if not run_id and dump_id:
        run_id = recent_run_for_dump(dump_id, data_root=root)
    expected_dump_id = resolve_dump_id(dump_id_for_run(run_id, data_root=root), data_root=root) if run_id else ""
    if run_id and dump_id and expected_dump_id and safe_id(dump_id) != safe_id(expected_dump_id):
        raise ValueError(f"dump_id={dump_id} is incompatible with run_id={run_id}; expected {expected_dump_id}")
    return {"run_id": run_id, "dump_id": dump_id or expected_dump_id}


def resolve_scoped_table_path(
    table: str,
    *,
    run_id: str | None = None,
    dump_id: str | None = None,
    data_root: Path | None = None,
) -> Path | None:
    if table not in TABLE_KINDS:
        raise ValueError(f"Unknown table: {table}")
    root = _data_root(data_root)
    scope = resolve_analysis_scope(run_id=run_id or "", dump_id=dump_id or "", data_root=root)
    resolved_run_id = scope["run_id"]
    resolved_dump_id = scope["dump_id"]
    if resolved_run_id:
        if table in DUMP_TABLES:
            return dump_table_path(resolved_dump_id, table, data_root=root) if resolved_dump_id else None
        return run_table_path(resolved_run_id, table, data_root=root)
    if resolved_dump_id and table in DUMP_TABLES:
        return dump_table_path(resolved_dump_id, table, data_root=root)
    return None
