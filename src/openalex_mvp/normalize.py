from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .io_utils import read_jsonl, write_csv_dicts, write_json, write_parquet_dicts

NULL_AUTHOR_ID = "https://openalex.org/A9999999999"
DELETED_AUTHOR_ID = "https://openalex.org/A5317838346"

WORK_FIELDS = [
    "work_id",
    "doi",
    "display_name",
    "publication_year",
    "publication_date",
    "type",
    "language",
    "cited_by_count",
    "open_access_is_oa",
    "has_abstract",
    "is_retracted",
    "is_paratext",
    "is_xpac",
    "is_authors_truncated",
    "authorships_count_raw",
    "valid_author_ids_count",
    "primary_topic_id",
    "primary_topic_display_name",
    "primary_subfield_id",
    "primary_subfield_short_id",
    "primary_field_id",
    "primary_domain_id",
    "source_id",
    "source_display_name",
    "source_type",
    "created_date",
    "updated_date",
]

AUTHORSHIP_FIELDS = [
    "work_id",
    "author_seq",
    "author_position",
    "author_id",
    "author_display_name",
    "author_orcid",
    "raw_author_name",
    "is_corresponding",
    "institution_ids_csv",
    "country_codes_csv",
    "authorships_count_raw",
    "valid_author_ids_count",
    "frac_weight_strict",
    "frac_weight_renorm",
    "qf_null_author_id",
    "qf_deleted_author_id",
    "qf_duplicate_authorship",
    "qf_authorship_truncated",
    "qf_missing_required_fields",
]

WORK_TOPIC_FIELDS = [
    "work_id",
    "topic_id",
    "topic_display_name",
    "score",
    "subfield_id",
    "field_id",
    "domain_id",
    "is_primary",
]

def normalize_raw(
    raw_path: str | Path = "data/raw/openalex_cli/current/works.jsonl.gz",
    works_out: str | Path = "data/normalized/works_flat.csv",
    authorships_out: str | Path = "data/normalized/authorships_flat.csv",
    quality_out: str | Path = "data/passports/quality_report.json",
    work_topics_out: str | Path = "data/normalized/work_topics_flat.csv",
) -> dict[str, Any]:
    works = read_jsonl(raw_path)
    works_rows: list[dict[str, Any]] = []
    authorship_rows: list[dict[str, Any]] = []
    work_topic_rows: list[dict[str, Any]] = []
    work_ids_seen: set[str] = set()

    quality = Counter()
    per_work_quality: dict[str, dict[str, Any]] = {}

    for work in works:
        work_id = str(work.get("id") or "")
        if not work_id:
            quality["works_missing_id"] += 1
            continue
        if work_id in work_ids_seen:
            quality["duplicate_work_ids"] += 1
            continue
        work_ids_seen.add(work_id)

        authorships = work.get("authorships") or []
        valid_ids = [
            _author_id(a)
            for a in authorships
            if _author_id(a) and _author_id(a) not in {NULL_AUTHOR_ID, DELETED_AUTHOR_ID}
        ]
        valid_distinct = sorted(set(valid_ids))
        valid_count = len(valid_distinct)
        raw_count = len(authorships)
        is_truncated = bool(work.get("is_authors_truncated", False))
        if is_truncated:
            quality["works_with_truncated_authorships"] += 1

        primary_topic = work.get("primary_topic") or {}
        primary_subfield = primary_topic.get("subfield") or {}
        primary_field = primary_topic.get("field") or {}
        primary_domain = primary_topic.get("domain") or {}
        primary_location = work.get("primary_location") or {}
        source = primary_location.get("source") or {}
        open_access = work.get("open_access") or {}

        works_rows.append(
            {
                "work_id": work_id,
                "doi": work.get("doi") or (work.get("ids") or {}).get("doi"),
                "display_name": work.get("display_name"),
                "publication_year": work.get("publication_year"),
                "publication_date": work.get("publication_date"),
                "type": work.get("type"),
                "language": work.get("language"),
                "cited_by_count": int(work.get("cited_by_count") or 0),
                "open_access_is_oa": open_access.get("is_oa"),
                "has_abstract": bool(work.get("has_abstract") or work.get("abstract_inverted_index")),
                "is_retracted": bool(work.get("is_retracted", False)),
                "is_paratext": bool(work.get("is_paratext", False)),
                "is_xpac": bool(work.get("is_xpac", False)),
                "is_authors_truncated": is_truncated,
                "authorships_count_raw": raw_count,
                "valid_author_ids_count": valid_count,
                "primary_topic_id": primary_topic.get("id"),
                "primary_topic_display_name": primary_topic.get("display_name"),
                "primary_subfield_id": primary_subfield.get("id"),
                "primary_subfield_short_id": _short_id(primary_subfield.get("id")),
                "primary_field_id": primary_field.get("id"),
                "primary_domain_id": primary_domain.get("id"),
                "source_id": source.get("id"),
                "source_display_name": source.get("display_name"),
                "source_type": source.get("type"),
                "created_date": work.get("created_date"),
                "updated_date": work.get("updated_date"),
            }
        )

        author_occurrences: defaultdict[str, int] = defaultdict(int)
        for seq, authorship in enumerate(authorships, start=1):
            author_id = _author_id(authorship)
            if author_id:
                author_occurrences[author_id] += 1
        duplicate_ids = {aid for aid, count in author_occurrences.items() if count > 1}

        qf_missing_topic = not primary_topic.get("id")
        if qf_missing_topic:
            quality["works_missing_primary_topic"] += 1
        topics = work.get("topics") or []
        topic_ids_written: set[str] = set()
        for topic in topics:
            topic_row = _work_topic_row(work_id, topic, primary_topic)
            if topic_row["topic_id"]:
                topic_ids_written.add(str(topic_row["topic_id"]))
                work_topic_rows.append(topic_row)
        primary_topic_id = str(primary_topic.get("id") or "")
        if primary_topic_id and primary_topic_id not in topic_ids_written:
            work_topic_rows.append(_work_topic_row(work_id, primary_topic, primary_topic))
        if not topics and not primary_topic_id:
            quality["works_without_topics"] += 1

        for seq, authorship in enumerate(authorships, start=1):
            author = authorship.get("author") or {}
            author_id = author.get("id")
            qf_null = not author_id or author_id == NULL_AUTHOR_ID
            qf_deleted = author_id == DELETED_AUTHOR_ID
            qf_duplicate = bool(author_id and author_id in duplicate_ids and author_occurrences[author_id] > 1)
            if qf_null:
                quality["authorships_null_author_id"] += 1
            if qf_deleted:
                quality["authorships_deleted_author_id"] += 1
            if qf_duplicate:
                quality["authorships_duplicate_author_id"] += 1

            institutions = authorship.get("institutions") or []
            institution_ids = [inst.get("id") for inst in institutions if inst.get("id")]
            country_codes = authorship.get("countries") or [
                inst.get("country_code") for inst in institutions if inst.get("country_code")
            ]
            strict_weight = 1.0 / raw_count if raw_count > 0 else None
            renorm_weight = 1.0 / valid_count if valid_count > 0 and not (qf_null or qf_deleted) else None

            authorship_rows.append(
                {
                    "work_id": work_id,
                    "author_seq": seq,
                    "author_position": authorship.get("author_position"),
                    "author_id": author_id,
                    "author_display_name": author.get("display_name"),
                    "author_orcid": author.get("orcid"),
                    "raw_author_name": authorship.get("raw_author_name"),
                    "is_corresponding": authorship.get("is_corresponding"),
                    "institution_ids_csv": "|".join(institution_ids),
                    "country_codes_csv": "|".join(sorted(set(filter(None, country_codes)))),
                    "authorships_count_raw": raw_count,
                    "valid_author_ids_count": valid_count,
                    "frac_weight_strict": strict_weight,
                    "frac_weight_renorm": renorm_weight,
                    "qf_null_author_id": qf_null,
                    "qf_deleted_author_id": qf_deleted,
                    "qf_duplicate_authorship": qf_duplicate,
                    "qf_authorship_truncated": is_truncated,
                    "qf_missing_required_fields": qf_missing_topic,
                }
            )

        per_work_quality[work_id] = {
            "authorships_count_raw": raw_count,
            "valid_author_ids_count": valid_count,
            "is_authors_truncated": is_truncated,
            "missing_primary_topic": qf_missing_topic,
        }

    works_rows.sort(key=lambda row: row["work_id"])
    authorship_rows.sort(key=lambda row: (row["work_id"], int(row["author_seq"])))
    work_topic_rows.sort(key=lambda row: (row["work_id"], str(row.get("topic_id") or "")))

    write_csv_dicts(works_out, works_rows, WORK_FIELDS)
    write_csv_dicts(authorships_out, authorship_rows, AUTHORSHIP_FIELDS)
    write_csv_dicts(work_topics_out, work_topic_rows, WORK_TOPIC_FIELDS)
    write_parquet_dicts(_parquet_peer(works_out), works_rows, WORK_FIELDS)
    write_parquet_dicts(_parquet_peer(authorships_out), authorship_rows, AUTHORSHIP_FIELDS)
    write_parquet_dicts(_parquet_peer(work_topics_out), work_topic_rows, WORK_TOPIC_FIELDS)

    report = {
        "raw_works": len(works),
        "works_rows": len(works_rows),
        "authorship_rows": len(authorship_rows),
        "work_topic_rows": len(work_topic_rows),
        "quality_counts": dict(sorted(quality.items())),
        "notes": [
            "authors_count is not returned by the current OpenAlex list select API; strict mode uses observed authorships_count_raw.",
            "For truncated work authorships, singleton work backfill is recommended before final analysis.",
        ],
    }
    write_json(quality_out, report)
    return report


def _author_id(authorship: dict[str, Any]) -> str | None:
    author = authorship.get("author") or {}
    return author.get("id")


def _parquet_peer(path: str | Path) -> Path:
    p = Path(path)
    try:
        parts = list(p.parts)
        if "normalized" in parts:
            parts[parts.index("normalized")] = "parquet"
            return Path(*parts).with_suffix(".parquet")
    except ValueError:
        pass
    return p.with_suffix(".parquet")


def _work_topic_row(work_id: str, topic: dict[str, Any], primary_topic: dict[str, Any]) -> dict[str, Any]:
    subfield = topic.get("subfield") or {}
    field = topic.get("field") or {}
    domain = topic.get("domain") or {}
    topic_id = topic.get("id")
    return {
        "work_id": work_id,
        "topic_id": topic_id,
        "topic_display_name": topic.get("display_name"),
        "score": topic.get("score"),
        "subfield_id": subfield.get("id"),
        "field_id": field.get("id"),
        "domain_id": domain.get("id"),
        "is_primary": bool(topic_id and topic_id == primary_topic.get("id")),
    }


def _short_id(openalex_id: object) -> str | None:
    if not openalex_id:
        return None
    text = str(openalex_id).rstrip("/")
    return text.rsplit("/", 1)[-1]
