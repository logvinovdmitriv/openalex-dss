from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.paths import DATA, ROOT


LAKE_ZONES = {
    "bronze_api": DATA / "lake/bronze/openalex/api",
    "bronze_snapshot": DATA / "lake/bronze/openalex/snapshot",
    "bronze_files": DATA / "lake/bronze/openalex/files",
    "silver_openalex": DATA / "lake/silver/openalex",
    "gold_scientometrics": DATA / "lake/gold/scientometrics",
    "warehouse": DATA / "warehouse",
}

SAFE_SCAN_ROOTS = {
    "raw": DATA / "raw",
    "ref": DATA / "ref",
    "dumps": DATA / "dumps",
    "tables": DATA / "tables",
    "runs": DATA / "runs",
    "cohorts": DATA / "cohorts",
    "validation": DATA / "validation",
    "workbench": DATA / "workbench",
    "lake": DATA / "lake",
    "warehouse": DATA / "warehouse",
}

DATA_FILE_SUFFIXES = {
    ".jsonl",
    ".gz",
    ".json",
    ".csv",
    ".tsv",
    ".parquet",
    ".duckdb",
    ".yaml",
    ".yml",
}


def prepare_lakehouse_dirs() -> dict[str, Any]:
    created: dict[str, str] = {}
    for name, path in {**SAFE_SCAN_ROOTS, **LAKE_ZONES}.items():
        path.mkdir(parents=True, exist_ok=True)
        created[name] = str(path)
    return {"status": "ok", "zones": created}


def storage_overview() -> dict[str, Any]:
    prepare_lakehouse_dirs()
    zones = []
    for name, path in {**SAFE_SCAN_ROOTS, **LAKE_ZONES}.items():
        zones.append(
            {
                "name": name,
                "path": str(path),
                "exists": path.exists(),
                "files_count": _count_files(path),
                "bytes": _dir_size(path),
            }
        )
    return {
        "project_root": str(ROOT),
        "data_root": str(DATA),
        "safe_roots": {name: str(path) for name, path in SAFE_SCAN_ROOTS.items()},
        "lake_zones": {name: str(path) for name, path in LAKE_ZONES.items()},
        "zones": zones,
    }


def list_data_files(root: str = "data", limit: int = 300) -> dict[str, Any]:
    base = _root_from_key(root)
    rows = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or not _is_supported(path):
            continue
        stat = path.stat()
        rows.append(
            {
                "name": path.name,
                "path": str(path),
                "relative_path": _display_path(path),
                "suffix": "".join(path.suffixes[-2:]) if path.name.endswith(".jsonl.gz") else path.suffix,
                "bytes": stat.st_size,
                "modified_at": int(stat.st_mtime),
                "source_kind": _source_kind(path),
                "importable": path.name.endswith(".jsonl") or path.name.endswith(".jsonl.gz"),
            }
        )
    rows.sort(key=lambda row: (not row["importable"], row["source_kind"], row["relative_path"]))
    return {"root": str(base), "files": rows[: max(1, min(limit, 2000))], "limit": limit}


def resolve_safe_path(value: str | Path) -> Path:
    raw = Path(value).expanduser()
    if raw.is_absolute():
        path = raw
    elif raw.parts and raw.parts[0] == "data":
        path = DATA.joinpath(*raw.parts[1:])
    else:
        path = ROOT / raw
    resolved = path.resolve()
    allowed = [ROOT.resolve(), DATA.resolve()]
    if not any(resolved == root or root in resolved.parents for root in allowed):
        raise ValueError(f"Path is outside the project workspace or configured data root: {value}")
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"Source file does not exist: {value}")
    return resolved


def file_profile(value: str | Path) -> dict[str, Any]:
    path = resolve_safe_path(value)
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "relative_path": _display_path(path),
        "bytes": stat.st_size,
        "modified_at": int(stat.st_mtime),
        "source_kind": _source_kind(path),
        "importable": path.name.endswith(".jsonl") or path.name.endswith(".jsonl.gz"),
    }


def _root_from_key(root: str) -> Path:
    if root in SAFE_SCAN_ROOTS:
        return SAFE_SCAN_ROOTS[root]
    if root in LAKE_ZONES:
        return LAKE_ZONES[root]
    if root in {"data", ""}:
        return DATA
    return resolve_safe_path(root).parent


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    data_root = DATA.resolve()
    root = ROOT.resolve()
    if resolved == data_root or data_root in resolved.parents:
        return str(Path("data") / resolved.relative_to(data_root))
    if resolved == root or root in resolved.parents:
        return str(resolved.relative_to(root))
    return str(resolved)


def _is_supported(path: Path) -> bool:
    if path.name.endswith(".jsonl.gz"):
        return True
    return path.suffix.lower() in DATA_FILE_SUFFIXES


def _source_kind(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(DATA.resolve())
        text = "/" + rel.as_posix()
    except ValueError:
        text = path.as_posix()
    if "/lake/bronze/openalex/snapshot/" in text:
        return "openalex_snapshot"
    if "/raw/openalex_cli/" in text:
        return "openalex_cli"
    if "/lake/bronze/openalex/api/" in text or text.startswith("/raw/"):
        return "openalex_api"
    if "/lake/bronze/openalex/files/" in text:
        return "local_file"
    if path.suffix == ".duckdb":
        return "warehouse"
    return "artifact"


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file())


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
