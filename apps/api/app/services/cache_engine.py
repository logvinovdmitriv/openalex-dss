from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Iterable

import yaml

from app.core.paths import DATA, ROOT


DEFAULT_FILTERED_CACHE_ENTRIES_PER_RUN = 10
DEFAULT_FILTERED_CACHE_BYTES_PER_RUN = 2 * 1024 * 1024 * 1024
DEFAULT_FILTERED_CACHE_TOTAL_BYTES = 10 * 1024 * 1024 * 1024


def prune_run_filtered_cache(run_filtered_root: Path, *, entry_limit: int | None = None, runs_root: Path | None = None) -> None:
    if not run_filtered_root.is_dir():
        prune_total_filtered_cache(runs_root=runs_root)
        return
    entries = _manifest_entries(run_filtered_root.glob("*/manifest.json"))
    limit = max(1, int(entry_limit)) if entry_limit is not None else storage_policy_int("max_filtered_cache_entries_per_run", DEFAULT_FILTERED_CACHE_ENTRIES_PER_RUN, minimum=1)
    max_bytes = storage_policy_int("max_analytics_cache_bytes_per_run", DEFAULT_FILTERED_CACHE_BYTES_PER_RUN, minimum=1)

    ordered = sorted(entries)
    for _, cache_dir, _ in ordered[: max(0, len(entries) - limit)]:
        shutil.rmtree(cache_dir, ignore_errors=True)
    remaining = [(stamp, path, size) for stamp, path, size in ordered[max(0, len(entries) - limit):] if path.exists()]
    total = sum(size for _, _, size in remaining)
    for _, cache_dir, size in remaining:
        if total <= max_bytes:
            break
        shutil.rmtree(cache_dir, ignore_errors=True)
        total -= size
    prune_total_filtered_cache(runs_root=runs_root)


def prune_total_filtered_cache(*, runs_root: Path | None = None) -> None:
    max_bytes = storage_policy_int("max_total_cache_bytes", DEFAULT_FILTERED_CACHE_TOTAL_BYTES, minimum=1)
    if max_bytes <= 0:
        return
    runs_root = runs_root or (DATA / "runs")
    if not runs_root.is_dir():
        return
    entries = _manifest_entries(runs_root.glob("*/analytics/filtered/*/manifest.json"))
    total = sum(size for _, _, size in entries)
    if total <= max_bytes:
        return
    for _, cache_dir, size in sorted(entries):
        if total <= max_bytes:
            break
        shutil.rmtree(cache_dir, ignore_errors=True)
        total -= size


def storage_policy_int(key: str, default: int, *, minimum: int = 0) -> int:
    config_path = ROOT / "configs" / "execution_limits.yaml"
    if config_path.is_file():
        try:
            doc = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            policy = doc.get("storage_policy") if isinstance(doc, dict) else {}
            return max(minimum, int((policy or {}).get(key) or default))
        except (OSError, TypeError, ValueError, yaml.YAMLError):
            return default
    return default


def dir_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    if not path.is_dir():
        return 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def _manifest_entries(manifest_paths: Iterable[Path]) -> list[tuple[str, Path, int]]:
    entries: list[tuple[str, Path, int]] = []
    for manifest_path in manifest_paths:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cache_dir = manifest_path.parent
        entries.append((str(manifest.get("last_used_at") or manifest.get("created_at") or ""), cache_dir, dir_size(cache_dir)))
    return entries
