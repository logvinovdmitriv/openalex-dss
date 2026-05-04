from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.paths import DATA
from app.services import warehouse


COHORTS_DIR = DATA / "cohorts"
COHORT_METRICS = ("p", "c", "c_frac", "cpp", "h", "i10", "g", "m_local", "top1_share", "islv", "iupv", "lrdi")


def create_cohort(payload: dict[str, Any]) -> dict[str, Any]:
    COHORTS_DIR.mkdir(parents=True, exist_ok=True)
    source = str(payload.get("source") or "top_n")
    fraction_mode = str(payload.get("fraction_mode") or "strict_authors_count")
    metric = str(payload.get("metric") or "h")
    filters = _filters(payload)

    if source == "manual":
        author_ids = [str(item).strip() for item in payload.get("author_ids") or [] if str(item).strip()]
    else:
        top_n = max(1, min(int(payload.get("top_n") or 100), 1000))
        ranking = warehouse.metric_ranking(fraction_mode, metric, filters, limit=top_n)
        rows = ranking.get("rows") or []
        author_ids = [str(row.get("author_id")) for row in rows if row.get("author_id")]

    min_publications = int(payload.get("min_publications") or 0)
    min_h = int(payload.get("min_h") or 0)
    if min_publications or min_h:
        author_ids = _apply_metric_thresholds(author_ids, fraction_mode, filters, min_publications=min_publications, min_h=min_h)

    now = _now()
    cohort = {
        "cohort_id": _safe_id(f"cohort_{uuid.uuid4().hex[:10]}"),
        "slice_id": payload.get("slice_id") or "current",
        "name": str(payload.get("name") or "Авторская когорта"),
        "source": source,
        "metric": metric,
        "fraction_mode": fraction_mode,
        "top_n": payload.get("top_n"),
        "filters": filters,
        "min_publications": min_publications,
        "min_h": min_h,
        "author_ids": author_ids,
        "n_authors": len(author_ids),
        "created_at_utc": now,
        "checksum": _checksum(author_ids),
    }
    _write(cohort)
    return cohort


def list_cohorts(limit: int = 50) -> dict[str, Any]:
    COHORTS_DIR.mkdir(parents=True, exist_ok=True)
    docs = [_read(path) for path in sorted(COHORTS_DIR.glob("*.json"), reverse=True)]
    docs = [doc for doc in docs if doc]
    return {"cohorts": docs[: max(1, min(limit, 250))], "total": len(docs)}


def get_cohort(cohort_id: str) -> dict[str, Any]:
    path = _path(cohort_id)
    if not path.exists():
        raise KeyError(cohort_id)
    return _read(path)


def cohort_statistics(cohort_id: str) -> dict[str, Any]:
    cohort = get_cohort(cohort_id)
    author_ids = set(cohort.get("author_ids") or [])
    rows = [
        row for row in warehouse.filtered_author_indices(str(cohort.get("fraction_mode") or "strict_authors_count"), cohort.get("filters") or {})
        if str(row.get("author_id") or "") in author_ids
    ]
    descriptive = {metric: _describe([_as_float(row.get(metric)) for row in rows]) for metric in COHORT_METRICS}
    boxplots = {metric: _boxplot([_as_float(row.get(metric)) for row in rows]) for metric in COHORT_METRICS}
    return {
        "cohort": cohort,
        "n_rows": len(rows),
        "metrics": list(COHORT_METRICS),
        "descriptive": descriptive,
        "boxplots": boxplots,
        "notes": [
            "Statistics are computed for the stored author cohort, not for every author in the slice.",
            "Q-Q plots and bootstrap intervals are reserved for the next statistics iteration.",
        ],
    }


def _apply_metric_thresholds(
    author_ids: list[str],
    fraction_mode: str,
    filters: dict[str, Any],
    *,
    min_publications: int,
    min_h: int,
) -> list[str]:
    allowed = set(author_ids)
    rows = warehouse.filtered_author_indices(fraction_mode, filters)
    out: list[str] = []
    for row in rows:
        author_id = str(row.get("author_id") or "")
        if author_id not in allowed:
            continue
        if min_publications and _as_float(row.get("p")) < min_publications:
            continue
        if min_h and _as_float(row.get("h")) < min_h:
            continue
        out.append(author_id)
    return out


def _filters(payload: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key in ("country_code", "institution_id", "subject_level", "subject_id", "filter_mode"):
        value = str(payload.get(key) or "").strip()
        if value:
            clean[key] = value
    return clean


def _describe(values: list[float]) -> dict[str, float]:
    values = sorted(value for value in values if value == value)
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": sum(values) / len(values),
        "min": values[0],
        "q1": _quantile(values, 0.25),
        "median": _quantile(values, 0.5),
        "q3": _quantile(values, 0.75),
        "max": values[-1],
        "iqr": _quantile(values, 0.75) - _quantile(values, 0.25),
    }


def _boxplot(values: list[float]) -> dict[str, Any]:
    values = sorted(value for value in values if value == value)
    if not values:
        return {"n": 0, "outliers": []}
    q1 = _quantile(values, 0.25)
    q3 = _quantile(values, 0.75)
    iqr = q3 - q1
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    inliers = [value for value in values if low <= value <= high] or values
    return {
        "n": len(values),
        "min": min(inliers),
        "q1": q1,
        "median": _quantile(values, 0.5),
        "q3": q3,
        "max": max(inliers),
        "outliers": [value for value in values if value < low or value > high][:100],
    }


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    index = int(round((len(values) - 1) * max(0.0, min(1.0, q))))
    return float(values[index])


def _as_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _checksum(author_ids: list[str]) -> str:
    payload = "\n".join(sorted(author_ids)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write(doc: dict[str, Any]) -> None:
    _path(str(doc["cohort_id"])).write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _path(cohort_id: str) -> Path:
    COHORTS_DIR.mkdir(parents=True, exist_ok=True)
    return COHORTS_DIR / f"{_safe_id(cohort_id)}.json"


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in value)[:120] or "cohort"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
