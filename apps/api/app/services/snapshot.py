from __future__ import annotations

import json
import urllib.request
from collections import Counter
from typing import Any


S3_HTTPS_BASE = "https://openalex.s3.amazonaws.com"
ENTITIES = ("works", "authors", "sources", "institutions", "topics", "domains", "fields", "subfields", "publishers", "funders", "concepts")


def fetch_manifest(entity: str = "works", max_entries: int = 1000) -> dict[str, Any]:
    if entity not in ENTITIES:
        raise ValueError(f"Unsupported OpenAlex entity: {entity}")
    url = f"{S3_HTTPS_BASE}/data/{entity}/manifest"
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    entries = payload.get("entries", [])
    partitions = Counter(_partition(entry.get("url", "")) for entry in entries)
    total_records = sum(int((entry.get("meta") or {}).get("record_count") or 0) for entry in entries)
    total_bytes = sum(int((entry.get("meta") or {}).get("content_length") or 0) for entry in entries)
    return {
        "entity": entity,
        "manifest_url": url,
        "entries_count": len(entries),
        "total_records": total_records,
        "total_compressed_bytes": total_bytes,
        "partitions_count": len(partitions),
        "recent_partitions": sorted(partitions)[-20:],
        "sample_entries": entries[:max(0, min(max_entries, 20))],
    }


def _partition(s3_url: str) -> str:
    marker = "updated_date="
    if marker not in s3_url:
        return "unknown"
    return s3_url.split(marker, 1)[1].split("/", 1)[0]
