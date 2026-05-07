from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


def ensure_parent(path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_jsonl(path: str | Path) -> list[dict]:
    rows: list[dict] = []
    p = Path(path)
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt", encoding="utf-8", newline="\n") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_json(path: str | Path, data: object) -> None:
    p = ensure_parent(path)
    p.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def read_csv_dicts(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_table_dicts(path: str | Path) -> list[dict]:
    p = Path(path)
    if p.suffix == ".parquet":
        try:
            import polars as pl
        except ImportError as exc:
            raise RuntimeError("Reading Parquet tables requires polars to be installed") from exc
        return pl.read_parquet(p).to_dicts()
    return read_csv_dicts(p)


def write_csv_dicts(path: str | Path, rows: Iterable[dict], fieldnames: list[str]) -> int:
    p = ensure_parent(path)
    opener = gzip.open if p.suffix == ".gz" else open
    count = 0
    with opener(p, "wt", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
            count += 1
    return count


def write_parquet_dicts(path: str | Path, rows: Iterable[dict], fieldnames: list[str]) -> int:
    try:
        import polars as pl
    except ImportError:
        return 0
    data = [{key: row.get(key) for key in fieldnames} for row in rows]
    p = ensure_parent(path)
    frame = pl.DataFrame(_parquet_columns(data, fieldnames)) if data else pl.DataFrame({key: [] for key in fieldnames})
    frame.write_parquet(p)
    return len(data)


def _parquet_columns(rows: list[dict], fieldnames: list[str]) -> dict[str, list[Any]]:
    return {field: _coerce_parquet_column([row.get(field) for row in rows]) for field in fieldnames}


def _coerce_parquet_column(values: list[Any]) -> list[Any]:
    observed = [value for value in values if value is not None]
    if not observed:
        return values
    if all(isinstance(value, bool) for value in observed):
        return values
    if all(isinstance(value, int) and not isinstance(value, bool) for value in observed):
        return values
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in observed):
        return [float(value) if value is not None else None for value in values]
    return [_parquet_string_value(value) for value in values]


def _parquet_string_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.10g}"
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def as_int(value: object, default: int = 0) -> int:
    if value in (None, ""):
        return default
    return int(float(str(value)))


def as_float(value: object, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    return float(str(value))
