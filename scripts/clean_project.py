from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

BASE_ARTIFACTS = [
    Path("apps/web/dist"),
    Path("apps/web/tsconfig.tsbuildinfo"),
    Path("output"),
    Path(".pytest_cache"),
    Path(".mypy_cache"),
    Path(".ruff_cache"),
]

DEPENDENCY_DIRS = [
    Path(".venv"),
    Path("node_modules"),
    Path("apps/web/node_modules"),
]

KEEP_DATA_FILES = {"README.md", ".gitkeep"}
WALK_SKIP_DIRS = {".git", ".venv", "node_modules"}


def _tracked_paths() -> set[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=False,
        )
    except (OSError, subprocess.CalledProcessError):
        return set()
    return {item.decode("utf-8") for item in result.stdout.split(b"\0") if item}


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _has_tracked_content(path: Path, tracked: set[str]) -> bool:
    rel = _rel(path)
    if rel in tracked:
        return True
    prefix = rel.rstrip("/") + "/"
    return any(item.startswith(prefix) for item in tracked)


def _remove(path: Path, tracked: set[str], dry_run: bool) -> bool:
    if not path.exists():
        return False
    if _has_tracked_content(path, tracked):
        print(f"skip tracked: {_rel(path)}")
        return False
    print(f"{'would remove' if dry_run else 'remove'}: {_rel(path)}")
    if dry_run:
        return True
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def _iter_cache_artifacts() -> list[Path]:
    found: list[Path] = []
    for current, dirs, files in os.walk(ROOT):
        current_path = Path(current)
        dirs[:] = [item for item in dirs if item not in WALK_SKIP_DIRS]
        if "__pycache__" in dirs:
            found.append(current_path / "__pycache__")
            dirs.remove("__pycache__")
        for file_name in files:
            if file_name == ".DS_Store" or file_name.endswith((".pyc", ".pyo")):
                found.append(current_path / file_name)
    return found


def _data_artifacts() -> list[Path]:
    data_dir = ROOT / "data"
    if not data_dir.exists():
        return []
    return [item for item in data_dir.iterdir() if item.name not in KEEP_DATA_FILES]


def _empty_old_dirs() -> list[Path]:
    old_web = ROOT / "web"
    if old_web.exists() and old_web.is_dir() and not any(old_web.iterdir()):
        return [old_web]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove local OpenAlex DSS generated artifacts.")
    parser.add_argument("--data", action="store_true", help="Remove repo-local data/* artifacts except data/README.md.")
    parser.add_argument("--deps", action="store_true", help="Remove local dependency folders such as .venv and node_modules.")
    parser.add_argument("--empty-old", action="store_true", help="Remove empty old folders such as ./web.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be removed without deleting.")
    args = parser.parse_args()

    tracked = _tracked_paths()
    targets = [ROOT / item for item in BASE_ARTIFACTS]
    if args.deps:
        targets.extend(ROOT / item for item in DEPENDENCY_DIRS)
    if args.data:
        targets.extend(_data_artifacts())
    if args.empty_old:
        targets.extend(_empty_old_dirs())

    removed = 0
    for target in targets:
        removed += int(_remove(target, tracked, args.dry_run))
    for target in _iter_cache_artifacts():
        removed += int(_remove(target, tracked, args.dry_run))

    print(f"{'planned' if args.dry_run else 'removed'}: {removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
