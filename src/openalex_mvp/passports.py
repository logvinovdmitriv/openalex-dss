from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any

from .config import SliceConfig, config_to_dict
from .io_utils import sha256_file, write_json


PRIMARY_ARTIFACTS = [
    "config/slice.yaml",
    "requirements.lock",
    "docs/methodology.md",
    "data/raw/works_raw.jsonl",
    "data/normalized/works_flat.csv",
    "data/normalized/authorships_flat.csv",
    "data/marts/author_work_metrics.csv",
    "data/results/author_indices.csv",
    "data/results/rating_positions.csv",
    "data/results/stats_summary.json",
    "data/results/theory_validation.json",
    "data/results/theory_top1_sensitivity.csv",
    "data/results/theory_fraction_mode_sensitivity.csv",
    "data/passports/resolved_entity.json",
    "data/passports/fetch_meta.json",
    "data/passports/quality_report.json",
    "data/passports/slice_passport.json",
    "data/passports/calculation_passport.json",
]


def build_passports(
    cfg: SliceConfig,
    root: str | Path = ".",
    out_dir: str | Path = "data/passports",
    *,
    run_id: str = "base",
    dump_id: str = "",
) -> dict[str, Any]:
    root_path = Path(root)
    data_root = _data_root(root_path)
    out = root_path / out_dir
    out.mkdir(parents=True, exist_ok=True)

    slice_passport = {
        "slice_id": cfg.slice_name,
        "slice_name": cfg.slice_name,
        "data_source": "OpenAlex API",
        "source_mode": "api_dump_first",
        "api_base": "https://api.openalex.org",
        "vak_mapping_status": "не указано",
        "resolved_entities_file": "data/passports/resolved_entity.json",
        "resolved_entity": {
            "entity_level": cfg.entity_level,
            "entity_id_short": cfg.entity_id_short,
            "entity_id_full": cfg.entity_id_full,
            "entity_display_name": cfg.entity_display_name,
        },
        "workflow_mode": cfg.workflow_mode,
        "filter_mode": cfg.filter_mode,
        "topic_mode": cfg.filter_mode,
        "funnel": {
            "topic_filter": {
                "mode": cfg.filter_mode,
                "entity_level": cfg.entity_level,
                "entity_id": cfg.entity_id_short,
                "entity_display_name": cfg.entity_display_name,
            },
            "keyword_filter": {
                "keyword_id": cfg.keyword_id,
                "keyword_display_name": cfg.keyword_display_name,
            },
            "text_search_query": cfg.text_search_query,
            "institution_filter": {
                "institution_id": cfg.institution_id,
                "institution_display_name": cfg.institution_display_name,
                "affiliation_mode": cfg.affiliation_mode,
            },
            "country_filter": cfg.country_code,
        },
        "filters": {
            "country_code": cfg.country_code or None,
            "institution_id": cfg.institution_id or None,
            "topic_ids": [cfg.entity_id_short] if cfg.entity_level == "topic" else [],
            "subfield_ids": [cfg.entity_id_short] if cfg.entity_level == "subfield" else [],
            "field_ids": [cfg.entity_id_short] if cfg.entity_level == "field" else [],
            "from_date": cfg.from_publication_date,
            "to_date": cfg.to_publication_date,
            "work_types": [part for part in cfg.work_type.split("|") if part],
            "exclude_retracted": cfg.exclude_retracted,
            "exclude_paratext": cfg.exclude_paratext,
            "include_xpac": cfg.include_xpac,
        },
        "date_range": {
            "from_publication_date": cfg.from_publication_date,
            "to_publication_date": cfg.to_publication_date,
        },
        "work_type": cfg.work_type,
        "exclude_retracted": cfg.exclude_retracted,
        "exclude_paratext": cfg.exclude_paratext,
        "include_xpac": cfg.include_xpac,
        "sort": cfg.sort,
        "per_page": cfg.per_page,
        "max_works": cfg.max_works,
        "select_fields": list(cfg.select_fields),
        "storage_strategy": {
            "principle": "raw immutable dump -> thin curated slice -> transient marts -> reports/passports",
            "raw_layer": f"data/raw/{cfg.slice_name}/",
            "curated_layer": f"data/curated/{cfg.slice_name}/",
            "mart_layer": f"data/marts/{cfg.slice_name}/",
            "reports_layer": f"data/reports/{cfg.slice_name}/",
            "checksums_layer": f"data/checksums/{cfg.slice_name}/",
            "current_smoke_paths": {
                "raw": "data/raw/works_raw.jsonl",
                "works_flat": "data/normalized/works_flat.csv",
                "authorships_flat": "data/normalized/authorships_flat.csv",
                "author_work_metrics": "data/marts/author_work_metrics.csv",
                "author_indices": "data/results/author_indices.csv",
            },
        },
        "optimization_policy": {
            "principle": "download minimum, store once, compute locally, cache repeated OpenAlex calls",
            "estimate_endpoint": "POST /api/v1/slices/plan",
            "api_cache": "data/cache/openalex_api",
            "limits_config": "configs/execution_limits.yaml",
            "filter_registry": "configs/openalex_filter_registry.yaml",
            "api_usage": "ID resolution, dropdown suggestions, compact works dump and point enrichment only",
        },
    }
    indices = ["p", "c", "c_frac", "cpp", "h", "i10", "g", "m_local"]
    experimental_indices = ["f5", "fm5", "iupv", "islv", "lrdi"]
    theory_validation = [
        "iupv_boundedness_monotonicity",
        "remove_top1_per_author",
        "fraction_mode_sensitivity",
        "metric_concentration",
        "prefix_convergence",
    ]
    extra_formula = {
        "f5_fm5": {
            "status": "operational_definition_requires_primary_source_confirmation",
            "threshold": 5,
            "f5": "count(works where cited_by_count >= 5)",
            "fm5": "sum(credit_weight for works where cited_by_count >= 5)",
        },
        "iupv": {
            "formula": "100 * (pr(P) * pr(h) * pr(C_frac)) ** (1/3)",
            "formula_version": "v2_percentile_geometric_mean",
            "percentile_scope": "current slice within each fraction_mode",
            "status": "experimental",
            "legacy_parameters_ignored": {"n0": cfg.iupv_n0, "lambda": cfg.iupv_lambda},
        },
        "islv": {
            "name_ru": "индекс сбалансированного локального вклада",
            "formula": "100 * G * K_conc, where G is weighted geometric mean of percentile ranks h/C_frac/g/i10/P and K_conc penalizes top1_share above tau",
            "weights": {"h": 0.35, "c_frac": 0.30, "g": 0.20, "i10": 0.10, "p": 0.05},
            "epsilon": 0.01,
            "tau": 0.50,
            "lambda": 0.30,
            "formula_version": "mvp_v1",
            "status": "own_formula",
        },
        "lrdi": {
            "p0": cfg.lrdi_p0,
            "lambda": cfg.lrdi_lambda,
            "analysis_year": cfg.analysis_year,
            "formula_version": "v1",
            "status": "experimental",
        },
    }

    calculation_passport = {
        "run_id": run_id,
        "dump_id": dump_id,
        "fraction_modes": list(cfg.fraction_modes),
        "fraction_mode_default": cfg.fraction_mode_default,
        "ranking_rule": {
            "profile_id": "slice_local_default",
            "primary_metric": "selected_per_report",
            "tie_breakers": ["c desc", "p desc", "author_id asc"],
            "used_by": ["rating_positions.csv", "analytics/ranking", "report_bundle"],
        },
        "indices": indices,
        "experimental_indices": experimental_indices,
        "theory_validation": theory_validation,
        **extra_formula,
        "software": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "config": config_to_dict(cfg),
    }

    write_json(out / "slice_passport.json", slice_passport)
    write_json(out / "calculation_passport.json", calculation_passport)

    checksums = {
        rel: sha256_file(_artifact_path(root_path, data_root, rel))
        for rel in PRIMARY_ARTIFACTS
        if _artifact_path(root_path, data_root, rel).is_file()
    }
    manifest_path = _write_sha256_manifest(root_path, data_root, cfg.slice_name, checksums)
    checksums_doc = {
        "algorithm": "SHA-256",
        "slice_id": cfg.slice_name,
        "primary_artifacts": checksums,
            "sha256_manifest": _display_path(root_path, data_root, manifest_path),
        "notes": [
            "Figures are secondary artifacts and are intentionally excluded from primary checksums.",
            "The dependency-light smoke implementation writes CSV; the architecture reserves slice-based Parquet paths for the production data layer.",
        ],
    }
    write_json(out / "checksums.json", checksums_doc)
    return checksums_doc


def _write_sha256_manifest(root_path: Path, data_root: Path, slice_id: str, checksums: dict[str, str]) -> Path:
    del root_path
    out = data_root / "checksums" / slice_id
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "sha256_manifest.txt"
    lines = [f"{digest}  {rel}" for rel, digest in sorted(checksums.items())]
    manifest.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8", newline="\n")
    return manifest


def _data_root(root_path: Path) -> Path:
    configured = os.environ.get("OPENALEX_DSS_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (root_path.parent / "openalex-dss-data").resolve()


def _artifact_path(root_path: Path, data_root: Path, rel: str) -> Path:
    if rel == "data" or rel.startswith("data/"):
        return data_root / rel.removeprefix("data/").lstrip("/")
    return root_path / rel


def _display_path(root_path: Path, data_root: Path, path: Path) -> str:
    resolved = path.resolve()
    if resolved == data_root or data_root in resolved.parents:
        return str(Path("data") / resolved.relative_to(data_root))
    if resolved == root_path or root_path in resolved.parents:
        return str(resolved.relative_to(root_path))
    return str(resolved)
