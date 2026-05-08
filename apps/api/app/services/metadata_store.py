from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.paths import DATA


DB_PATH = DATA / "warehouse" / "openalex_metadata.sqlite"


def catalog_status() -> dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT entity_type, count(*) AS n
            FROM catalog_entities
            GROUP BY entity_type
            ORDER BY entity_type
            """
        ).fetchall()
        dumps = conn.execute("SELECT count(*) FROM slice_dumps").fetchone()[0]
    return {
        "db_path": str(DB_PATH),
        "exists": DB_PATH.exists(),
        "entities": {row["entity_type"]: row["n"] for row in rows},
        "slice_dumps": dumps,
    }


def upsert_entities(entity_type: str, items: list[dict[str, Any]], *, source: str = "openalex") -> int:
    _ensure_schema()
    now = _now()
    rows = [_entity_row(entity_type, item, source, now) for item in items if item.get("openalex_id") or item.get("id")]
    if not rows:
        return 0
    with _connect() as conn:
        conn.executemany(
            """
            INSERT INTO catalog_entities (
              entity_key, entity_type, level, openalex_id, short_id, display_name,
              description, country_code, external_id, works_count, cited_by_count,
              payload_json, source, updated_at_utc
            )
            VALUES (
              :entity_key, :entity_type, :level, :openalex_id, :short_id, :display_name,
              :description, :country_code, :external_id, :works_count, :cited_by_count,
              :payload_json, :source, :updated_at_utc
            )
            ON CONFLICT(entity_key) DO UPDATE SET
              level=excluded.level,
              openalex_id=excluded.openalex_id,
              short_id=excluded.short_id,
              display_name=excluded.display_name,
              description=excluded.description,
              country_code=excluded.country_code,
              external_id=excluded.external_id,
              works_count=excluded.works_count,
              cited_by_count=excluded.cited_by_count,
              payload_json=excluded.payload_json,
              source=excluded.source,
              updated_at_utc=excluded.updated_at_utc
            """,
            rows,
        )
    return len(rows)


def search_entities(entity_type: str, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    _ensure_schema()
    text = query.casefold().strip()
    if not text:
        return list_entities(entity_type, limit=limit)
    like = f"%{text}%"
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM catalog_entities
            WHERE entity_type = ?
              AND (
                lower(display_name) LIKE ?
                OR lower(short_id) LIKE ?
                OR lower(openalex_id) LIKE ?
                OR lower(coalesce(external_id, '')) LIKE ?
                OR lower(coalesce(description, '')) LIKE ?
              )
            ORDER BY works_count DESC, display_name ASC
            LIMIT ?
            """,
            [entity_type, like, like, like, like, like, max(1, min(limit, 50))],
        ).fetchall()
    return [_row_to_entity(row) for row in rows]


def list_entities(entity_type: str, *, limit: int = 8) -> list[dict[str, Any]]:
    _ensure_schema()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM catalog_entities
            WHERE entity_type = ?
            ORDER BY works_count DESC, display_name ASC
            LIMIT ?
            """,
            [entity_type, max(1, min(limit, 50))],
        ).fetchall()
    return [_row_to_entity(row) for row in rows]


def record_slice_dump(passport: dict[str, Any]) -> None:
    _ensure_schema()
    signatures = passport.get("signatures") if isinstance(passport.get("signatures"), dict) else {}
    request = passport.get("openalex_request") if isinstance(passport.get("openalex_request"), dict) else {}
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO slice_dumps (
              slice_id, raw_jsonl, records_downloaded, bytes_written, sha256,
              stop_reason, created_at_utc, payload_json, dump_id, source_mode,
              scientific_completeness, allowed_for_final_analysis, openalex_filter,
              estimate_signature, download_signature, records_expected,
              actual_vs_estimate_ratio
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slice_id, raw_jsonl) DO UPDATE SET
              records_downloaded=excluded.records_downloaded,
              bytes_written=excluded.bytes_written,
              sha256=excluded.sha256,
              stop_reason=excluded.stop_reason,
              created_at_utc=excluded.created_at_utc,
              dump_id=excluded.dump_id,
              source_mode=excluded.source_mode,
              scientific_completeness=excluded.scientific_completeness,
              allowed_for_final_analysis=excluded.allowed_for_final_analysis,
              openalex_filter=excluded.openalex_filter,
              estimate_signature=excluded.estimate_signature,
              download_signature=excluded.download_signature,
              records_expected=excluded.records_expected,
              actual_vs_estimate_ratio=excluded.actual_vs_estimate_ratio,
              payload_json=excluded.payload_json
            """,
            [
                str(passport.get("slice_id") or ""),
                str(passport.get("raw_jsonl") or ""),
                int(passport.get("records_downloaded") or 0),
                int(passport.get("bytes_written") or 0),
                str(passport.get("raw_jsonl_sha256") or ""),
                str(passport.get("stop_reason") or ""),
                str(passport.get("created_at_utc") or _now()),
                json.dumps(passport, ensure_ascii=False, sort_keys=True),
                str(passport.get("dump_id") or ""),
                str(passport.get("source_mode") or ""),
                str(passport.get("scientific_completeness") or ""),
                1 if bool(passport.get("allowed_for_final_analysis")) else 0,
                str(request.get("filter") or ""),
                str(signatures.get("estimate_signature") or ""),
                str(signatures.get("download_signature") or ""),
                int(passport.get("records_expected")) if passport.get("records_expected") is not None else None,
                float(passport.get("actual_vs_estimate_ratio")) if passport.get("actual_vs_estimate_ratio") is not None else None,
            ],
        )


def list_slice_dumps(limit: int = 50) -> list[dict[str, Any]]:
    _ensure_schema()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM slice_dumps
            ORDER BY created_at_utc DESC
            LIMIT ?
            """,
            [max(1, min(limit, 250))],
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(_row_to_slice_dump(row))
    return result


def get_slice_dump_by_dump_id(dump_id: str) -> dict[str, Any] | None:
    _ensure_schema()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM slice_dumps
            WHERE dump_id = ?
            ORDER BY created_at_utc DESC
            LIMIT 1
            """,
            [dump_id],
        ).fetchone()
    return _row_to_slice_dump(row) if row else None


def delete_slice_dump_by_dump_id(dump_id: str) -> dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM slice_dumps
            WHERE dump_id = ?
            """,
            [dump_id],
        ).fetchall()
        conn.execute("DELETE FROM slice_dumps WHERE dump_id = ?", [dump_id])
    return {"deleted": len(rows), "dumps": [_row_to_slice_dump(row) for row in rows]}


def _entity_row(entity_type: str, item: dict[str, Any], source: str, now: str) -> dict[str, Any]:
    openalex_id = str(item.get("openalex_id") or item.get("id") or "")
    short_id = str(item.get("id") or "").strip() or _short_openalex_id(openalex_id)
    level = str(item.get("level") or entity_type)
    key = f"{entity_type}:{level}:{short_id or openalex_id}"
    external_id = str(item.get("ror") or item.get("orcid") or item.get("doi") or item.get("external_id") or "")
    return {
        "entity_key": key,
        "entity_type": entity_type,
        "level": level,
        "openalex_id": openalex_id,
        "short_id": short_id,
        "display_name": str(item.get("name") or item.get("display_name") or short_id),
        "description": str(item.get("description") or ""),
        "country_code": str(item.get("country_code") or ""),
        "external_id": external_id,
        "works_count": int(item.get("works_count") or 0),
        "cited_by_count": int(item.get("cited_by_count") or 0),
        "payload_json": json.dumps(item, ensure_ascii=False, sort_keys=True),
        "source": source,
        "updated_at_utc": now,
    }


def _row_to_entity(row: sqlite3.Row) -> dict[str, Any]:
    payload = {}
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {
        **payload,
        "id": row["short_id"],
        "openalex_id": row["openalex_id"],
        "name": row["display_name"],
        "level": row["level"],
        "description": row["description"],
        "country_code": row["country_code"],
        "works_count": row["works_count"],
        "cited_by_count": row["cited_by_count"],
        "source": "metadata_db",
    }


def _row_to_slice_dump(row: sqlite3.Row) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {
        **payload,
        "slice_id": row["slice_id"],
        "raw_jsonl": row["raw_jsonl"],
        "records_downloaded": row["records_downloaded"],
        "bytes_written": row["bytes_written"],
        "sha256": row["sha256"],
        "stop_reason": row["stop_reason"],
        "created_at_utc": row["created_at_utc"],
        "dump_id": row["dump_id"],
        "source_mode": row["source_mode"],
        "scientific_completeness": row["scientific_completeness"],
        "allowed_for_final_analysis": bool(row["allowed_for_final_analysis"]),
        "openalex_filter": row["openalex_filter"],
        "estimate_signature": row["estimate_signature"],
        "download_signature": row["download_signature"],
        "records_expected": row["records_expected"],
        "actual_vs_estimate_ratio": row["actual_vs_estimate_ratio"],
    }


def _ensure_schema() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog_entities (
              entity_key TEXT PRIMARY KEY,
              entity_type TEXT NOT NULL,
              level TEXT NOT NULL,
              openalex_id TEXT NOT NULL,
              short_id TEXT NOT NULL,
              display_name TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              country_code TEXT NOT NULL DEFAULT '',
              external_id TEXT NOT NULL DEFAULT '',
              works_count INTEGER NOT NULL DEFAULT 0,
              cited_by_count INTEGER NOT NULL DEFAULT 0,
              payload_json TEXT NOT NULL DEFAULT '{}',
              source TEXT NOT NULL DEFAULT '',
              updated_at_utc TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_type_name ON catalog_entities(entity_type, display_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_type_works ON catalog_entities(entity_type, works_count)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS slice_dumps (
              slice_id TEXT NOT NULL,
              raw_jsonl TEXT NOT NULL,
              records_downloaded INTEGER NOT NULL DEFAULT 0,
              bytes_written INTEGER NOT NULL DEFAULT 0,
              sha256 TEXT NOT NULL DEFAULT '',
              stop_reason TEXT NOT NULL DEFAULT '',
              created_at_utc TEXT NOT NULL,
              payload_json TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY(slice_id, raw_jsonl)
            )
            """
        )
        _ensure_column(conn, "slice_dumps", "dump_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "slice_dumps", "source_mode", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "slice_dumps", "scientific_completeness", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "slice_dumps", "allowed_for_final_analysis", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "slice_dumps", "openalex_filter", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "slice_dumps", "estimate_signature", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "slice_dumps", "download_signature", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "slice_dumps", "records_expected", "INTEGER")
        _ensure_column(conn, "slice_dumps", "actual_vs_estimate_ratio", "REAL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_slice_dumps_dump_id ON slice_dumps(dump_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_slice_dumps_final ON slice_dumps(allowed_for_final_analysis)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_slice_dumps_source_mode ON slice_dumps(source_mode)")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=1.0)
    conn.row_factory = sqlite3.Row
    return conn


def _short_openalex_id(value: str) -> str:
    return str(value or "").strip().rstrip("/").rsplit("/", 1)[-1]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
