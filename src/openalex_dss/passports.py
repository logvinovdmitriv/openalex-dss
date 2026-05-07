from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any

from .config import SliceConfig, config_to_dict
from .io_utils import sha256_file, write_json


def build_passports(
    cfg: SliceConfig,
    root: str | Path = ".",
    *,
    run_id: str = "",
    dump_id: str = "",
    analysis_eligibility: dict[str, Any] | None = None,
    input_tables: dict[str, Any] | None = None,
    primary_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not primary_artifacts:
        raise ValueError("primary_artifacts is required")
    root_path = Path(root)
    data_root = _data_root(root_path)
    out = _passport_out_dir(data_root, run_id)
    out.mkdir(parents=True, exist_ok=True)

    slice_passport = {
        "slice_id": cfg.slice_name,
        "slice_name": cfg.slice_name,
        "data_source": "OpenAlex CLI works metadata; OpenAlex API only for resolving, estimates and enrichment",
        "source_mode": "openalex_cli_filtered_metadata",
        "api_base": "https://api.openalex.org",
        "vak_mapping_status": "не указано",
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
        "select_fields": list(cfg.select_fields),
        "storage_strategy": {
            "principle": "raw immutable dump -> scoped dump tables -> scoped run tables -> report bundle",
            "raw_layer": f"data/raw/openalex_cli/{cfg.slice_name}/",
            "dump_layer": f"data/dumps/{dump_id or '<dump_id>'}/",
            "canonical_tables_layer": f"data/tables/{dump_id or '<dump_id>'}/",
            "run_tables_layer": f"data/runs/{run_id or '<run_id>'}/tables/",
            "run_passports_layer": f"data/runs/{run_id or '<run_id>'}/passports/",
            "reports_layer": f"data/runs/{run_id or '<run_id>'}/reports/",
        },
        "optimization_policy": {
            "principle": "download minimum, store once, compute locally, cache repeated OpenAlex calls",
            "estimate_endpoint": "POST /api/v1/slices/{slice_id}/estimate",
            "api_cache": "data/cache/openalex_api",
            "limits_config": "configs/execution_limits.yaml",
            "filter_registry": "configs/openalex_filter_registry.yaml",
            "api_usage": "ID resolution, dropdown suggestions, field/filter catalogs, estimate/group_by/sample, rate-limit visibility and point enrichment only",
            "download_usage": "Works corpus is downloaded through the installed OpenAlex CLI, not through the application API client.",
        },
    }
    indices = ["p", "c", "c_frac", "cpp", "h", "i10", "g", "m_local"]
    experimental_indices = ["f5", "fm5", "iupv", "islv", "lrdi"]
    extra_formula = {
        "f5_fm5": {
            "status": "operational_definition_requires_primary_source_confirmation",
            "threshold": 5,
            "f5": "count(works where cited_by_count >= 5)",
            "fm5": "sum(credit_weight for works where cited_by_count >= 5)",
        },
        "iupv": {
            "formula": "100 * (pr(P) * pr(h) * pr(C_frac)) ** (1/3)",
            "percentile_scope": "current slice within each fraction_mode",
            "status": "experimental",
        },
        "islv": {
            "name_ru": "индекс сбалансированного локального вклада",
            "formula": "100 * G * K_conc, where G is weighted geometric mean of percentile ranks h/C_frac/g/i10/P and K_conc penalizes top1_share above tau",
            "weights": {"h": 0.35, "c_frac": 0.30, "g": 0.20, "i10": 0.10, "p": 0.05},
            "epsilon": 0.01,
            "tau": 0.50,
            "lambda": 0.30,
            "status": "own_formula",
        },
        "lrdi": {
            "p0": cfg.lrdi_p0,
            "lambda": cfg.lrdi_lambda,
            "analysis_year": cfg.analysis_year,
            "status": "experimental",
        },
    }

    calculation_passport = {
        "run_id": run_id,
        "dump_id": dump_id,
        "analysis_eligibility": analysis_eligibility or {"status": "unknown", "allowed_for_final_analysis": False},
        "input_tables": input_tables or {},
        "fraction_modes": list(cfg.fraction_modes),
        "fraction_mode_default": cfg.fraction_mode_default,
        "ranking_rule": {
            "profile_id": "slice_local_default",
            "primary_metric": "selected_per_report",
            "tie_breakers": ["c desc", "p desc", "author_id asc"],
            "used_by": ["ratings.csv", "analytics/ranking", "report_bundle"],
        },
        "indices": indices,
        "experimental_indices": experimental_indices,
        **extra_formula,
        "software": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "config": config_to_dict(cfg),
    }

    write_json(out / "slice_passport.json", slice_passport)
    write_json(out / "calculation_passport.json", calculation_passport)

    checksums = _primary_artifact_checksums(primary_artifacts)
    checksum_notes = [
        "Figures are secondary artifacts and are intentionally excluded from primary checksums.",
        "Primary checksums were built from scoped dump/run artifacts.",
    ]
    manifest_path = _write_sha256_manifest_for_out_dir(out, checksums)
    checksums_doc = {
        "algorithm": "SHA-256",
        "slice_id": cfg.slice_name,
        "primary_artifacts": checksums,
        "sha256_manifest": _display_path(root_path, data_root, manifest_path),
        "notes": checksum_notes,
    }
    write_json(out / "checksums.json", checksums_doc)
    return checksums_doc


def _write_sha256_manifest_for_out_dir(out: Path, checksums: dict[str, str]) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "sha256_manifest.txt"
    lines = [f"{digest}  {rel}" for rel, digest in sorted(checksums.items())]
    manifest.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8", newline="\n")
    return manifest


def _primary_artifact_checksums(primary_artifacts: dict[str, Any]) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for label, value in primary_artifacts.items():
        path = _primary_artifact_path(value)
        if path and path.is_file():
            checksums[str(label)] = sha256_file(path)
    return checksums


def _primary_artifact_path(value: Any) -> Path | None:
    raw = value.get("path") if isinstance(value, dict) else value
    if not raw:
        return None
    return Path(str(raw))


def _data_root(root_path: Path) -> Path:
    configured = os.environ.get("OPENALEX_DSS_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (root_path.parent / "openalex-dss-data").resolve()


def _passport_out_dir(data_root: Path, run_id: str) -> Path:
    safe_run_id = _safe_path_component(run_id)
    if not safe_run_id:
        raise ValueError("run_id is required for run-scoped passport generation")
    return data_root / "runs" / safe_run_id / "passports"


def _safe_path_component(value: str) -> str:
    text = str(value or "").strip()
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "=", "."} else "_" for ch in text)


def _display_path(root_path: Path, data_root: Path, path: Path) -> str:
    resolved = path.resolve()
    if resolved == data_root or data_root in resolved.parents:
        return str(Path("data") / resolved.relative_to(data_root))
    if resolved == root_path or root_path in resolved.parents:
        return str(resolved.relative_to(root_path))
    return str(resolved)
