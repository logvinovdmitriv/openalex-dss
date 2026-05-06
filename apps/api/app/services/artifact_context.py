from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.paths import DATA


def active_context_path(*, data_dir: Path | None = None) -> Path:
    return (data_dir or DATA) / "workbench" / "active_context.json"


def write_active_context(
    *,
    run_id: str,
    dump_id: str,
    source: str,
    data_dir: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "active_run_id": str(run_id or ""),
        "active_dump_id": str(dump_id or ""),
        "source": str(source or ""),
        "updated_at_utc": _now(),
    }
    if extra:
        doc.update(extra)
    path = active_context_path(data_dir=data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return doc


def read_active_context(*, data_dir: Path | None = None) -> dict[str, Any]:
    path = active_context_path(data_dir=data_dir)
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
