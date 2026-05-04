from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .io_utils import as_float, as_int, read_csv_dicts, truthy, write_csv_dicts
from .normalize import DELETED_AUTHOR_ID, NULL_AUTHOR_ID

AUTHOR_WORK_FIELDS = [
    "run_id",
    "fraction_mode",
    "work_id",
    "author_id",
    "author_display_name",
    "publication_year",
    "cited_by_count",
    "authors_count_used",
    "credit_weight",
    "cited_credit",
    "single_authored_flag",
    "qf_any",
    "qf_authorship_truncated",
    "qf_null_omission",
    "omitted_author_fraction",
]

AUTHOR_INDEX_FIELDS = [
    "run_id",
    "fraction_mode",
    "author_id",
    "author_display_name",
    "p",
    "c",
    "c_frac",
    "cpp",
    "h",
    "i10",
    "g",
    "m_local",
    "top1_share",
    "f5",
    "fm5",
    "iupv",
    "islv",
    "lrdi",
    "mean_authors_per_work",
    "share_single_authored",
    "n_flagged_works",
    "n_truncated_works",
]

NATIVE_AUTHOR_METRICS = ("p", "c", "h", "i10", "two_year_mean_citedness")

AUTHOR_PROFILE_INDEX_FIELDS = [
    "run_id",
    "fraction_mode",
    "author_id",
    "author_display_name",
    "p",
    "c",
    "h",
    "i10",
    "two_year_mean_citedness",
]


def h_index(citations: list[int]) -> int:
    c = sorted((max(0, int(x)) for x in citations), reverse=True)
    h = 0
    for i, value in enumerate(c, start=1):
        if value >= i:
            h = i
        else:
            break
    return h


def i10_index(citations: list[int]) -> int:
    return sum(1 for value in citations if int(value) >= 10)


def g_index(citations: list[int]) -> int:
    c = sorted((max(0, int(x)) for x in citations), reverse=True)
    total = 0
    g = 0
    for i, value in enumerate(c, start=1):
        total += value
        if total >= i * i:
            g = i
    return g


def iupv_from_percentiles(p_pr: float, h_pr: float, c_frac_pr: float) -> float:
    """IUPV v2: geometric mean of percentile ranks for P, h and C_frac."""
    if p_pr <= 0 or h_pr <= 0 or c_frac_pr <= 0:
        return 0.0
    return 100.0 * (max(1e-6, p_pr) * max(1e-6, h_pr) * max(1e-6, c_frac_pr)) ** (1.0 / 3.0)


def islv_from_percentiles(
    h_pr: float,
    c_frac_pr: float,
    g_pr: float,
    i10_pr: float,
    p_pr: float,
    top1_share: float,
    *,
    epsilon: float = 0.01,
    tau: float = 0.50,
    penalty_lambda: float = 0.30,
) -> float:
    """ISLV: balanced local contribution index with top-1 concentration penalty."""
    def component(value: float) -> float:
        return min(1.0, max(0.0, value) + epsilon)

    weights = (
        (component(h_pr), 0.35),
        (component(c_frac_pr), 0.30),
        (component(g_pr), 0.20),
        (component(i10_pr), 0.10),
        (component(p_pr), 0.05),
    )
    weight_sum = sum(weight for _, weight in weights)
    geometric = math.prod(value**weight for value, weight in weights) ** (1.0 / weight_sum)
    concentration_penalty = 1.0 - penalty_lambda * max(0.0, min(1.0, top1_share) - tau)
    return 100.0 * geometric * max(0.0, min(1.0, concentration_penalty))


def iupv(p: int, h: float, c_frac: float, n0: float = 5.0, lam: float = 0.35) -> float:
    """Backward-compatible alias for the v2 formula when percentile ranks are supplied.

    The previous log/saturation formula is intentionally no longer used in the
    pipeline. The argument names are kept stable for older imports; callers that
    need MVP-correct values should call ``assign_iupv_percentiles`` on the full
    author table.
    """
    del n0, lam
    return iupv_from_percentiles(float(p), float(h), float(c_frac))


def assign_iupv_percentiles(rows: list[dict[str, Any]], group_field: str = "fraction_mode") -> None:
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(group_field) or "")].append(row)

    for group in groups.values():
        percentile_maps = {
            field: _percentile_rank_map(group, field)
            for field in ("p", "h", "c_frac", "g", "i10")
        }
        for row in group:
            row["iupv"] = iupv_from_percentiles(
                percentile_maps["p"][id(row)],
                percentile_maps["h"][id(row)],
                percentile_maps["c_frac"][id(row)],
            )
            row["islv"] = islv_from_percentiles(
                percentile_maps["h"][id(row)],
                percentile_maps["c_frac"][id(row)],
                percentile_maps["g"][id(row)],
                percentile_maps["i10"][id(row)],
                percentile_maps["p"][id(row)],
                as_float(row.get("top1_share")),
            )


def lrdi(
    rows: list[dict[str, str]],
    *,
    analysis_year: int = 2026,
    p0: float = 5.0,
    lam: float = 0.15,
) -> float:
    p = len({row["work_id"] for row in rows})
    if p <= 0:
        return 0.0
    shrinkage = p / (p + p0)
    total = 0.0
    for row in rows:
        citations = max(0.0, as_float(row.get("cited_by_count")))
        denom = max(1.0, as_float(row.get("authors_count_used")))
        year = as_int(row.get("publication_year"))
        age = max(0, analysis_year - year) if year else 0
        total += (math.log1p(citations) / denom) * math.exp(-lam * age)
    return shrinkage * total


def build_author_work_metrics(
    works_path: str | Path = "data/normalized/works_flat.csv",
    authorships_path: str | Path = "data/normalized/authorships_flat.csv",
    out_path: str | Path = "data/marts/author_work_metrics.csv",
    fraction_modes: tuple[str, ...] = ("strict_authors_count", "renorm_valid_authors", "integer"),
    run_id: str = "base",
) -> list[dict[str, Any]]:
    works = {row["work_id"]: row for row in read_csv_dicts(works_path)}
    authorships = read_csv_dicts(authorships_path)
    rows: list[dict[str, Any]] = []
    seen_work_author: set[tuple[str, str]] = set()

    for auth in authorships:
        work_id = auth["work_id"]
        work = works.get(work_id)
        if not work:
            continue
        author_id = auth.get("author_id")
        if not author_id or author_id in {NULL_AUTHOR_ID, DELETED_AUTHOR_ID}:
            continue
        key = (work_id, author_id)
        if key in seen_work_author:
            continue
        seen_work_author.add(key)

        cited_by_count = as_int(work.get("cited_by_count"))
        raw_count = as_int(auth.get("authorships_count_raw"))
        valid_count = as_int(auth.get("valid_author_ids_count"))
        is_truncated = truthy(auth.get("qf_authorship_truncated"))
        qf_any = any(
            truthy(auth.get(flag))
            for flag in [
                "qf_null_author_id",
                "qf_deleted_author_id",
                "qf_duplicate_authorship",
                "qf_authorship_truncated",
                "qf_missing_required_fields",
            ]
        )

        for mode in fraction_modes:
            denom = _denominator(mode, raw_count, valid_count)
            if denom <= 0:
                continue
            credit = 1.0 / denom
            omitted = None
            if mode == "strict_authors_count" and raw_count > 0:
                omitted = max(0.0, 1.0 - (valid_count / raw_count))
            rows.append(
                {
                    "run_id": run_id,
                    "fraction_mode": mode,
                    "work_id": work_id,
                    "author_id": author_id,
                    "author_display_name": auth.get("author_display_name"),
                    "publication_year": work.get("publication_year"),
                    "cited_by_count": cited_by_count,
                    "authors_count_used": denom,
                    "credit_weight": credit,
                    "cited_credit": cited_by_count * credit,
                    "single_authored_flag": denom == 1,
                    "qf_any": qf_any,
                    "qf_authorship_truncated": is_truncated,
                    "qf_null_omission": bool(omitted and omitted > 0),
                    "omitted_author_fraction": omitted,
                }
            )

    rows.sort(key=lambda row: (row["fraction_mode"], row["author_id"], row["work_id"]))
    write_csv_dicts(out_path, rows, AUTHOR_WORK_FIELDS)
    return rows


def compute_indices(
    author_work_path: str | Path = "data/marts/author_work_metrics.csv",
    out_path: str | Path = "data/results/author_indices.csv",
    n0: float = 5.0,
    lam: float = 0.35,
    lrdi_p0: float = 5.0,
    lrdi_lambda: float = 0.15,
    analysis_year: int = 2026,
) -> list[dict[str, Any]]:
    rows = read_csv_dicts(author_work_path)
    groups: defaultdict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[(row["run_id"], row["fraction_mode"], row["author_id"])].append(row)

    out_rows: list[dict[str, Any]] = []
    for (run_id, mode, author_id), group in groups.items():
        group.sort(key=lambda row: row["work_id"])
        citations = [as_int(row["cited_by_count"]) for row in group]
        cited_credits = [as_float(row["cited_credit"]) for row in group]
        p = len({row["work_id"] for row in group})
        c = float(sum(citations))
        c_frac = float(sum(cited_credits))
        h = h_index(citations)
        i10 = i10_index(citations)
        g = g_index(citations)
        publication_years = [as_int(row.get("publication_year")) for row in group if as_int(row.get("publication_year")) > 0]
        local_age = max(publication_years) - min(publication_years) + 1 if publication_years else 1
        f5_value = _f5(group)
        fm5_value = _fm5(group)
        out_rows.append(
            {
                "run_id": run_id,
                "fraction_mode": mode,
                "author_id": author_id,
                "author_display_name": _first_nonempty(row.get("author_display_name") for row in group),
                "p": p,
                "c": c,
                "c_frac": c_frac,
                "cpp": c / p if p else 0.0,
                "h": h,
                "i10": i10,
                "g": g,
                "m_local": h / max(1, local_age),
                "top1_share": (max(citations) / c) if c > 0 and citations else 0.0,
                "f5": f5_value,
                "fm5": fm5_value,
                "iupv": 0.0,
                "islv": 0.0,
                "lrdi": lrdi(group, analysis_year=analysis_year, p0=lrdi_p0, lam=lrdi_lambda),
                "mean_authors_per_work": sum(as_float(row["authors_count_used"]) for row in group) / len(group),
                "share_single_authored": sum(1 for row in group if truthy(row["single_authored_flag"])) / len(group),
                "n_flagged_works": sum(1 for row in group if truthy(row["qf_any"])),
                "n_truncated_works": sum(1 for row in group if truthy(row["qf_authorship_truncated"])),
            }
        )

    assign_iupv_percentiles(out_rows)
    out_rows.sort(key=lambda row: (row["fraction_mode"], row["author_id"]))
    write_csv_dicts(out_path, out_rows, AUTHOR_INDEX_FIELDS)
    return out_rows


def compute_author_profile_indices(
    author_profiles_path: str | Path = "data/normalized/author_profiles_flat.csv",
    out_path: str | Path = "data/results/author_indices.csv",
    fraction_mode: str = "openalex_native",
) -> list[dict[str, Any]]:
    rows = read_csv_dicts(author_profiles_path)
    out_rows: list[dict[str, Any]] = []
    for row in rows:
        out_rows.append(
            {
                "run_id": "authors",
                "fraction_mode": fraction_mode,
                "author_id": row.get("author_id"),
                "author_display_name": row.get("author_display_name"),
                "p": as_int(row.get("works_count")),
                "c": as_float(row.get("cited_by_count")),
                "h": as_int(row.get("h")),
                "i10": as_int(row.get("i10")),
                "two_year_mean_citedness": as_float(row.get("two_year_mean_citedness")),
            }
        )
    out_rows.sort(key=lambda row: str(row["author_id"]))
    write_csv_dicts(out_path, out_rows, AUTHOR_PROFILE_INDEX_FIELDS)
    return out_rows


def _denominator(mode: str, raw_count: int, valid_count: int) -> int:
    if mode == "strict_authors_count":
        return raw_count
    if mode == "renorm_valid_authors":
        return valid_count
    if mode == "integer":
        return 1
    raise ValueError(f"Unsupported fraction mode: {mode}")


def _f5(group: list[dict[str, str]]) -> float:
    return float(sum(1 for row in group if as_int(row["cited_by_count"]) >= 5))


def _fm5(group: list[dict[str, str]]) -> float:
    return float(sum(as_float(row["credit_weight"]) for row in group if as_int(row["cited_by_count"]) >= 5))


def _percentile_rank_map(rows: list[dict[str, Any]], field: str) -> dict[int, float]:
    if not rows:
        return {}
    ordered = sorted(enumerate(rows), key=lambda item: (as_float(item[1].get(field)), str(item[1].get("author_id") or "")))
    result: dict[int, float] = {}
    n = len(ordered)
    pos = 0
    while pos < n:
        end = pos + 1
        value = as_float(ordered[pos][1].get(field))
        while end < n and as_float(ordered[end][1].get(field)) == value:
            end += 1
        average_rank = ((pos + 1) + end) / 2.0
        percentile = max(1e-6, average_rank / n)
        for _, row in ordered[pos:end]:
            result[id(row)] = percentile
        pos = end
    return result


def _first_nonempty(values: Any) -> str | None:
    for value in values:
        if value:
            return str(value)
    return None
