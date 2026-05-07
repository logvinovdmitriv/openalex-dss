from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SliceConfig:
    slice_name: str
    workflow_mode: str
    entity_level: str
    entity_id_short: str
    entity_id_full: str
    entity_display_name: str
    filter_mode: str
    keyword_id: str
    keyword_display_name: str
    text_search_query: str
    raw_openalex_filter: str
    author_id: str
    author_display_name: str
    author_orcid: str
    institution_id: str
    institution_display_name: str
    institution_ror: str
    source_id: str
    source_display_name: str
    source_type: str
    language: str
    open_access_is_oa: str
    has_abstract: str
    min_cited_by_count: int
    doi: str
    affiliation_mode: str
    from_publication_date: str
    to_publication_date: str
    work_type: str
    exclude_retracted: bool
    exclude_paratext: bool
    include_xpac: bool
    country_code: str
    sort: str
    per_page: int
    api_key_env: str
    fraction_modes: tuple[str, ...]
    fraction_mode_default: str
    select_fields: tuple[str, ...]
    lrdi_p0: float
    lrdi_lambda: float
    analysis_year: int
    random_seed: int


def _parse_value(raw: str) -> object:
    value = raw.strip()
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.lower() in {"null", "none"}:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def read_simple_yaml(path: str | Path) -> dict[str, object]:
    """Read the flat YAML subset used by this DSS config.

    This intentionally avoids a PyYAML dependency for the core smoke pipeline.
    The parser supports comments, blank lines, and simple `key: value` pairs.
    """

    data: dict[str, object] = {}
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise ValueError(f"Invalid config line {line_no}: {line!r}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid empty key on line {line_no}")
        data[key] = _parse_value(value)
    return data


def _csv_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (tuple, list)):
        return tuple(str(v).strip() for v in value if str(v).strip())
    return tuple(part.strip() for part in str(value).split(",") if part.strip())


def load_config(path: str | Path = "config/slice.yaml") -> SliceConfig:
    raw = read_simple_yaml(path)
    required = [
        "slice_name",
        "entity_level",
        "entity_id_short",
        "entity_id_full",
        "entity_display_name",
        "filter_mode",
        "from_publication_date",
        "to_publication_date",
        "work_type",
        "sort",
        "api_key_env",
        "fraction_mode_default",
        "select_fields",
    ]
    missing = [key for key in required if key not in raw]
    if missing:
        raise KeyError(f"Missing config keys: {', '.join(missing)}")

    return SliceConfig(
        slice_name=str(raw["slice_name"]),
        workflow_mode=str(raw.get("workflow_mode", "strict_works")),
        entity_level=str(raw["entity_level"]),
        entity_id_short=str(raw["entity_id_short"]),
        entity_id_full=str(raw["entity_id_full"]),
        entity_display_name=str(raw["entity_display_name"]),
        filter_mode=str(raw["filter_mode"]),
        keyword_id=str(raw.get("keyword_id", "") or ""),
        keyword_display_name=str(raw.get("keyword_display_name", "") or ""),
        text_search_query=str(raw.get("text_search_query", "") or ""),
        raw_openalex_filter=str(raw.get("raw_openalex_filter", "") or ""),
        author_id=str(raw.get("author_id", "") or ""),
        author_display_name=str(raw.get("author_display_name", "") or ""),
        author_orcid=str(raw.get("author_orcid", "") or ""),
        institution_id=str(raw.get("institution_id", "") or ""),
        institution_display_name=str(raw.get("institution_display_name", "") or ""),
        institution_ror=str(raw.get("institution_ror", "") or ""),
        source_id=str(raw.get("source_id", "") or ""),
        source_display_name=str(raw.get("source_display_name", "") or ""),
        source_type=str(raw.get("source_type", "") or ""),
        language=str(raw.get("language", "") or ""),
        open_access_is_oa=str(raw.get("open_access_is_oa", "") or ""),
        has_abstract=str(raw.get("has_abstract", "") or ""),
        min_cited_by_count=int(raw.get("min_cited_by_count", 0) or 0),
        doi=str(raw.get("doi", "") or ""),
        affiliation_mode=str(raw.get("affiliation_mode", "historical") or "historical"),
        from_publication_date=str(raw["from_publication_date"]),
        to_publication_date=str(raw["to_publication_date"]),
        work_type=str(raw["work_type"]),
        exclude_retracted=bool(raw.get("exclude_retracted", True)),
        exclude_paratext=bool(raw.get("exclude_paratext", True)),
        include_xpac=bool(raw.get("include_xpac", False)),
        country_code=str(raw.get("country_code", "") or ""),
        sort=str(raw["sort"]),
        per_page=int(raw.get("per_page", 100)),
        api_key_env=str(raw["api_key_env"]),
        fraction_modes=_csv_tuple(raw.get("fraction_modes", raw["fraction_mode_default"])),
        fraction_mode_default=str(raw["fraction_mode_default"]),
        select_fields=_csv_tuple(raw["select_fields"]),
        lrdi_p0=float(raw.get("lrdi_p0", 5.0)),
        lrdi_lambda=float(raw.get("lrdi_lambda", 0.15)),
        analysis_year=int(raw.get("analysis_year", 2026)),
        random_seed=int(raw.get("random_seed", 42)),
    )


def config_to_dict(cfg: SliceConfig) -> dict[str, object]:
    return {
        "slice_name": cfg.slice_name,
        "workflow_mode": cfg.workflow_mode,
        "entity_level": cfg.entity_level,
        "entity_id_short": cfg.entity_id_short,
        "entity_id_full": cfg.entity_id_full,
        "entity_display_name": cfg.entity_display_name,
        "filter_mode": cfg.filter_mode,
        "keyword_id": cfg.keyword_id,
        "keyword_display_name": cfg.keyword_display_name,
        "text_search_query": cfg.text_search_query,
        "raw_openalex_filter": cfg.raw_openalex_filter,
        "author_id": cfg.author_id,
        "author_display_name": cfg.author_display_name,
        "author_orcid": cfg.author_orcid,
        "institution_id": cfg.institution_id,
        "institution_display_name": cfg.institution_display_name,
        "institution_ror": cfg.institution_ror,
        "source_id": cfg.source_id,
        "source_display_name": cfg.source_display_name,
        "source_type": cfg.source_type,
        "language": cfg.language,
        "open_access_is_oa": cfg.open_access_is_oa,
        "has_abstract": cfg.has_abstract,
        "min_cited_by_count": cfg.min_cited_by_count,
        "doi": cfg.doi,
        "affiliation_mode": cfg.affiliation_mode,
        "from_publication_date": cfg.from_publication_date,
        "to_publication_date": cfg.to_publication_date,
        "work_type": cfg.work_type,
        "exclude_retracted": cfg.exclude_retracted,
        "exclude_paratext": cfg.exclude_paratext,
        "include_xpac": cfg.include_xpac,
        "country_code": cfg.country_code,
        "sort": cfg.sort,
        "per_page": cfg.per_page,
        "api_key_env": cfg.api_key_env,
        "fraction_modes": list(cfg.fraction_modes),
        "fraction_mode_default": cfg.fraction_mode_default,
        "select_fields": list(cfg.select_fields),
        "lrdi_p0": cfg.lrdi_p0,
        "lrdi_lambda": cfg.lrdi_lambda,
        "analysis_year": cfg.analysis_year,
        "random_seed": cfg.random_seed,
    }


def write_config(cfg: SliceConfig, path: str | Path = "config/slice.yaml") -> None:
    data = config_to_dict(cfg)
    lines = []
    for key, value in data.items():
        if isinstance(value, bool):
            out = "true" if value else "false"
        elif isinstance(value, list):
            out = ",".join(str(item) for item in value)
        else:
            out = str(value)
        lines.append(f"{key}: {out}")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def replace_config(cfg: SliceConfig, **updates: object) -> SliceConfig:
    data = config_to_dict(cfg)
    data.update({key: value for key, value in updates.items() if value is not None})
    if isinstance(data.get("fraction_modes"), str):
        fraction_modes = _csv_tuple(data["fraction_modes"])
    else:
        fraction_modes = tuple(str(v) for v in data.get("fraction_modes", cfg.fraction_modes))
    if isinstance(data.get("select_fields"), str):
        select_fields = _csv_tuple(data["select_fields"])
    else:
        select_fields = tuple(str(v) for v in data.get("select_fields", cfg.select_fields))
    return SliceConfig(
        slice_name=str(data["slice_name"]),
        workflow_mode=str(data.get("workflow_mode", "strict_works")),
        entity_level=str(data["entity_level"]),
        entity_id_short=str(data["entity_id_short"]),
        entity_id_full=str(data["entity_id_full"]),
        entity_display_name=str(data["entity_display_name"]),
        filter_mode=str(data["filter_mode"]),
        keyword_id=str(data.get("keyword_id", "") or ""),
        keyword_display_name=str(data.get("keyword_display_name", "") or ""),
        text_search_query=str(data.get("text_search_query", "") or ""),
        raw_openalex_filter=str(data.get("raw_openalex_filter", "") or ""),
        author_id=str(data.get("author_id", "") or ""),
        author_display_name=str(data.get("author_display_name", "") or ""),
        author_orcid=str(data.get("author_orcid", "") or ""),
        institution_id=str(data.get("institution_id", "") or ""),
        institution_display_name=str(data.get("institution_display_name", "") or ""),
        institution_ror=str(data.get("institution_ror", "") or ""),
        source_id=str(data.get("source_id", "") or ""),
        source_display_name=str(data.get("source_display_name", "") or ""),
        source_type=str(data.get("source_type", "") or ""),
        language=str(data.get("language", "") or ""),
        open_access_is_oa=str(data.get("open_access_is_oa", "") or ""),
        has_abstract=str(data.get("has_abstract", "") or ""),
        min_cited_by_count=int(data.get("min_cited_by_count", 0) or 0),
        doi=str(data.get("doi", "") or ""),
        affiliation_mode=str(data.get("affiliation_mode", "historical") or "historical"),
        from_publication_date=str(data["from_publication_date"]),
        to_publication_date=str(data["to_publication_date"]),
        work_type=str(data["work_type"]),
        exclude_retracted=bool(data["exclude_retracted"]),
        exclude_paratext=bool(data["exclude_paratext"]),
        include_xpac=bool(data["include_xpac"]),
        country_code=str(data.get("country_code", "") or ""),
        sort=str(data["sort"]),
        per_page=int(data["per_page"]),
        api_key_env=str(data["api_key_env"]),
        fraction_modes=fraction_modes,
        fraction_mode_default=str(data["fraction_mode_default"]),
        select_fields=select_fields,
        lrdi_p0=float(data.get("lrdi_p0", 5.0)),
        lrdi_lambda=float(data.get("lrdi_lambda", 0.15)),
        analysis_year=int(data.get("analysis_year", 2026)),
        random_seed=int(data["random_seed"]),
    )
