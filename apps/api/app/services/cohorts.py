from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.paths import DATA
from app.services.analysis_filters import clean_analysis_filters
from app.services import warehouse


COHORTS_DIR = DATA / "cohorts"
COHORT_METRICS = ("p", "c", "c_frac", "cpp", "h", "i10", "g", "m_local", "top1_share", "islv", "iupv", "lrdi")


def create_cohort(payload: dict[str, Any]) -> dict[str, Any]:
    COHORTS_DIR.mkdir(parents=True, exist_ok=True)
    source = str(payload.get("source") or "top_n")
    fraction_mode = str(payload.get("fraction_mode") or "strict_authors_count")
    metric = str(payload.get("metric") or "h")
    scope = warehouse.resolve_analysis_scope(run_id=str(payload.get("run_id") or ""), dump_id=str(payload.get("dump_id") or ""))
    run_id = scope["run_id"]
    dump_id = scope["dump_id"]
    filters = _filters(payload)

    if source == "manual":
        if not run_id:
            raise ValueError("Manual cohort requires run_id for reproducible analysis.")
        author_ids = [str(item).strip() for item in payload.get("author_ids") or [] if str(item).strip()]
    elif source == "metric_filter":
        rows = warehouse.filtered_author_indices(fraction_mode, filters, run_id=run_id, dump_id=dump_id)
        min_publications = int(payload.get("min_publications") or 0)
        min_h = int(payload.get("min_h") or 0)
        min_metric_value = payload.get("min_metric_value")
        author_ids = _metric_filter_author_ids(rows, metric, min_publications=min_publications, min_h=min_h, min_metric_value=min_metric_value)
    else:
        top_n = max(1, min(int(payload.get("top_n") or 100), 1000))
        ranking = warehouse.metric_ranking(fraction_mode, metric, filters, limit=top_n, max_limit=1000, run_id=run_id, dump_id=dump_id)
        rows = ranking.get("rows") or []
        author_ids = [str(row.get("author_id")) for row in rows if row.get("author_id")]
        dump_id = dump_id or str(ranking.get("dump_id") or "")

    min_publications = int(payload.get("min_publications") or 0)
    min_h = int(payload.get("min_h") or 0)
    min_metric_value = payload.get("min_metric_value")
    if source != "metric_filter" and (min_publications or min_h):
        author_ids = _apply_metric_thresholds(
            author_ids,
            fraction_mode,
            filters,
            min_publications=min_publications,
            min_h=min_h,
            run_id=run_id,
            dump_id=dump_id,
        )

    now = _now()
    cohort = {
        "cohort_id": _safe_id(f"cohort_{uuid.uuid4().hex[:10]}"),
        "slice_id": payload.get("slice_id") or "current",
        "run_id": run_id,
        "dump_id": dump_id,
        "name": str(payload.get("name") or "Авторская когорта"),
        "source": source,
        "metric": metric,
        "fraction_mode": fraction_mode,
        "top_n": payload.get("top_n") if source == "top_n" else None,
        "filters": filters,
        "min_publications": min_publications,
        "min_h": min_h,
        "min_metric_value": min_metric_value,
        "author_ids": author_ids,
        "n_authors": len(author_ids),
        "table_scope": _table_scope(run_id, dump_id),
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


def resolve_cohort_context(
    cohort_id: str,
    *,
    run_id: str = "",
    dump_id: str = "",
    fraction_mode: str = "",
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cohort = get_cohort(cohort_id)
    cohort_run_id = str(cohort.get("run_id") or "")
    cohort_dump_id = str(cohort.get("dump_id") or "")
    cohort_fraction_mode = str(cohort.get("fraction_mode") or "")
    if run_id and cohort_run_id and run_id != cohort_run_id:
        raise ValueError(f"cohort_id={cohort_id} belongs to run_id={cohort_run_id}, not run_id={run_id}")
    if dump_id and cohort_dump_id and dump_id != cohort_dump_id:
        raise ValueError(f"cohort_id={cohort_id} belongs to dump_id={cohort_dump_id}, not dump_id={dump_id}")
    if fraction_mode and cohort_fraction_mode and fraction_mode != cohort_fraction_mode:
        raise ValueError(f"cohort_id={cohort_id} uses fraction_mode={cohort_fraction_mode}, not fraction_mode={fraction_mode}")
    request_filters = clean_analysis_filters(filters or {})
    cohort_filters = clean_analysis_filters(cohort.get("filters") or {})
    if request_filters and cohort_filters and request_filters != cohort_filters:
        raise ValueError("Requested filters are incompatible with the stored cohort filters.")
    return {
        "cohort": cohort,
        "author_ids": {str(author_id) for author_id in cohort.get("author_ids") or [] if str(author_id).strip()},
        "run_id": run_id or cohort_run_id,
        "dump_id": dump_id or cohort_dump_id,
        "fraction_mode": fraction_mode or cohort_fraction_mode,
        "filters": request_filters or cohort_filters,
    }


def cohort_statistics(cohort_id: str) -> dict[str, Any]:
    cohort = get_cohort(cohort_id)
    author_ids = set(cohort.get("author_ids") or [])
    run_id = str(cohort.get("run_id") or "")
    dump_id = str(cohort.get("dump_id") or "")
    rows = [
        row for row in warehouse.filtered_author_indices(
            str(cohort.get("fraction_mode") or "strict_authors_count"),
            cohort.get("filters") or {},
            run_id=run_id,
            dump_id=dump_id,
        )
        if str(row.get("author_id") or "") in author_ids
    ]
    descriptive = {metric: _describe([_as_float(row.get(metric)) for row in rows]) for metric in COHORT_METRICS}
    boxplots = {metric: _boxplot([_as_float(row.get(metric)) for row in rows]) for metric in COHORT_METRICS}
    histograms = {
        metric: {
            "raw": _histogram([_as_float(row.get(metric)) for row in rows]),
            "log1p": _histogram([math.log1p(max(0.0, _as_float(row.get(metric)))) for row in rows]),
        }
        for metric in COHORT_METRICS
    }
    return {
        "cohort": cohort,
        "run_id": run_id,
        "dump_id": dump_id,
        "n_rows": len(rows),
        "metrics": list(COHORT_METRICS),
        "descriptive": descriptive,
        "boxplots": boxplots,
        "histograms": histograms,
        "notes": [
            "Statistics are computed for the stored author cohort, not for every author in the slice.",
            "Histogram bins are pre-aggregated so the frontend does not need the full author table.",
            "Formal Q-Q plots, Shapiro/Anderson tests and bootstrap intervals are reserved for the SciPy-backed statistics iteration.",
        ],
    }


def _apply_metric_thresholds(
    author_ids: list[str],
    fraction_mode: str,
    filters: dict[str, Any],
    *,
    min_publications: int,
    min_h: int,
    run_id: str = "",
    dump_id: str = "",
) -> list[str]:
    allowed = set(author_ids)
    rows = warehouse.filtered_author_indices(fraction_mode, filters, run_id=run_id, dump_id=dump_id)
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


def _metric_filter_author_ids(
    rows: list[dict[str, Any]],
    metric: str,
    *,
    min_publications: int,
    min_h: int,
    min_metric_value: Any,
) -> list[str]:
    threshold = None if min_metric_value in (None, "") else _as_float(min_metric_value)
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        author_id = str(row.get("author_id") or "")
        if not author_id or author_id in seen:
            continue
        if min_publications and _as_float(row.get("p")) < min_publications:
            continue
        if min_h and _as_float(row.get("h")) < min_h:
            continue
        if threshold is not None and _as_float(row.get(metric)) < threshold:
            continue
        seen.add(author_id)
        out.append(author_id)
    return out


def _filters(payload: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key in (
        "country_code",
        "institution_id",
        "subject_level",
        "subject_id",
        "filter_mode",
        "keyword_id",
        "keyword_display_name",
        "keyword_name",
        "text_search_query",
        "author_id",
        "author_display_name",
        "author_name",
        "author_orcid",
        "doi",
        "affiliation_mode",
        "source_id",
        "source_display_name",
        "source_name",
        "source_type",
        "language",
        "open_access_is_oa",
        "has_abstract",
        "min_cited_by_count",
        "from_publication_date",
        "to_publication_date",
        "work_type",
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            clean[key] = value
    if "keyword_display_name" not in clean and clean.get("keyword_name"):
        clean["keyword_display_name"] = clean.pop("keyword_name")
    else:
        clean.pop("keyword_name", None)
    if "author_display_name" not in clean and clean.get("author_name"):
        clean["author_display_name"] = clean.pop("author_name")
    else:
        clean.pop("author_name", None)
    if "source_display_name" not in clean and clean.get("source_name"):
        clean["source_display_name"] = clean.pop("source_name")
    else:
        clean.pop("source_name", None)
    return clean


def _table_scope(run_id: str, dump_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "dump_id": dump_id,
        "indices_table": str(warehouse.resolve_scoped_table_path("indices", run_id=run_id) or ""),
        "author_work_table": str(warehouse.resolve_scoped_table_path("author_work", run_id=run_id) or ""),
        "works_table": str(warehouse.resolve_scoped_table_path("works", run_id=run_id, dump_id=dump_id) or ""),
    }


def _describe(values: list[float]) -> dict[str, float]:
    values = sorted(value for value in values if value == value)
    if not values:
        return {"n": 0}
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    std = math.sqrt(variance)
    skewness = (sum((value - mean) ** 3 for value in values) / len(values) / (std**3)) if std > 0 else 0.0
    kurtosis = (sum((value - mean) ** 4 for value in values) / len(values) / (std**4) - 3.0) if std > 0 else 0.0
    return {
        "n": len(values),
        "mean": mean,
        "min": values[0],
        "q1": _quantile(values, 0.25),
        "median": _quantile(values, 0.5),
        "q3": _quantile(values, 0.75),
        "max": values[-1],
        "iqr": _quantile(values, 0.75) - _quantile(values, 0.25),
        "std": std,
        "skewness": skewness,
        "kurtosis": kurtosis,
        "zero_rate": sum(1 for value in values if value == 0) / len(values),
        "tie_rate": 1.0 - (len(set(values)) / len(values)),
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


def _histogram(values: list[float], bins: int = 12) -> list[dict[str, float]]:
    clean = [value for value in values if value == value]
    if not clean:
        return []
    lo = min(clean)
    hi = max(clean)
    if lo == hi:
        return [{"bin_start": lo, "bin_end": hi, "count": float(len(clean))}]
    bins = max(1, min(bins, 50))
    step = (hi - lo) / bins
    counts = [0] * bins
    for value in clean:
        idx = min(bins - 1, int((value - lo) / step))
        counts[idx] += 1
    return [
        {
            "bin_start": lo + idx * step,
            "bin_end": lo + (idx + 1) * step,
            "count": float(count),
        }
        for idx, count in enumerate(counts)
    ]


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
