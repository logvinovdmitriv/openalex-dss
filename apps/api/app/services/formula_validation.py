from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.core.paths import DATA, ROOT
from app.services import custom_metrics, warehouse


CORE_METRICS = ("p", "c", "c_frac", "h", "i10", "g")
PROTOCOL_PATH = ROOT / "configs/analysis_protocols.yaml"


def protocol_registry() -> dict[str, Any]:
    if not PROTOCOL_PATH.is_file():
        return {"version": "0", "protocols": {}, "templates": {}}
    data = yaml.safe_load(PROTOCOL_PATH.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {"version": "0", "protocols": {}, "templates": {}}


def validate_formula(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = str(payload.get("run_id") or "").strip()
    dump_id = str(payload.get("dump_id") or "").strip()
    fraction_mode = str(payload.get("fraction_mode") or "strict_authors_count")
    if not run_id and not dump_id:
        raise ValueError("Для проверки формулы нужен выбранный run_id или dump_id.")
    expression = _resolve_expression(payload)
    metric_id = _safe_metric_id(str(payload.get("id") or payload.get("formula_id") or "custom_formula"))
    definition = custom_metrics.parse_custom_metrics(
        [
            {
                "id": metric_id,
                "label": str(payload.get("label") or "Пользовательская формула"),
                "description": str(payload.get("description") or ""),
                "expression": expression,
            }
        ]
    )
    data_filters = warehouse.parse_column_filters(payload.get("data_filters") if isinstance(payload.get("data_filters"), (dict, str)) else None)
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else None
    distribution = warehouse.metric_distribution(
        fraction_mode,
        metric_id,
        filters,
        run_id=run_id,
        dump_id=dump_id,
        data_filters=data_filters,
        custom_metric_defs=definition,
    )
    ranking = warehouse.metric_ranking(
        fraction_mode,
        metric_id,
        filters,
        limit=int(payload.get("top_n") or 20),
        max_limit=500,
        run_id=run_id,
        dump_id=dump_id,
        data_filters=data_filters,
        custom_metric_defs=definition,
    )
    rows = warehouse.selected_index_rows(
        fraction_mode,
        filters,
        run_id=run_id,
        dump_id=dump_id,
        data_filters=data_filters,
        data_limit=max(0, min(500_000, int(payload.get("protocol_data_limit") or 0))),
        custom_metric_defs=definition,
        select_fields={"author_id", metric_id, *CORE_METRICS, "top1_share", "mean_authors_per_work"},
    )
    comparison = _comparison_summary(rows, metric_id)
    warnings = _formula_warnings(distribution, comparison)
    doc = {
        "status": "ok",
        "schema": "custom_metric_validation.v1",
        "formula_id": metric_id,
        "label": definition[0]["label"],
        "expression": expression,
        "parameters": payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {},
        "base_fields": sorted(custom_metrics.referenced_base_fields(definition)),
        "run_id": run_id,
        "dump_id": distribution.get("dump_id") or dump_id,
        "fraction_mode": fraction_mode,
        "analysis_protocol_id": "custom_formula_validation",
        "protocol_version": str(protocol_registry().get("version") or "1.0"),
        "readiness": distribution.get("chart_readiness") or {},
        "distribution": {key: distribution.get(key) for key in ("n", "min", "q1", "median", "mean", "q3", "p90", "max", "unique_count", "zero_count", "zero_rate")},
        "ranking_preview": ranking.get("rows") or [],
        "comparison": comparison,
        "warnings": warnings,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    artifact_path = _write_validation_artifact(run_id or str(distribution.get("run_id") or ""), metric_id, doc)
    doc["artifact_path"] = str(artifact_path)
    _write_formula_passport(run_id or str(distribution.get("run_id") or ""), metric_id, doc)
    return doc


def _resolve_expression(payload: dict[str, Any]) -> str:
    expression = str(payload.get("expression") or "").strip()
    template_id = str(payload.get("template_id") or "").strip()
    if not expression and template_id:
        registry = protocol_registry()
        template = (registry.get("templates") or {}).get(template_id) if isinstance(registry.get("templates"), dict) else None
        if not isinstance(template, dict):
            raise ValueError(f"Шаблон формулы не найден: {template_id}")
        expression = str(template.get("expression_template") or "")
        params = template.get("parameters") if isinstance(template.get("parameters"), dict) else {}
        overrides = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
        values = {name: (overrides.get(name) if name in overrides else spec.get("value")) for name, spec in params.items() if isinstance(spec, dict)}
        expression = expression.format(**values)
    if not expression:
        raise ValueError("Введите выражение формулы или выберите шаблон.")
    return expression


def _comparison_summary(rows: list[dict[str, Any]], metric_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "n_authors": len(rows),
        "spearman_vs_core": {},
        "top20_overlap_vs_core": {},
        "tie_rate": _tie_rate(rows, metric_id),
    }
    custom_order = _ordered_authors(rows, metric_id)
    custom_top20 = set(custom_order[:20])
    for metric in CORE_METRICS:
        out["spearman_vs_core"][metric] = _spearman_from_rows(rows, metric_id, metric)
        base_top20 = set(_ordered_authors(rows, metric)[:20])
        denominator = min(20, len(custom_top20), len(base_top20))
        out["top20_overlap_vs_core"][metric] = (len(custom_top20 & base_top20) / denominator) if denominator else None
    mean_authors_values = [float(row.get("mean_authors_per_work") or 0.0) for row in rows]
    custom_values = [float(row.get(metric_id) or 0.0) for row in rows]
    out["coauthorship_score_correlation"] = _pearson(custom_values, mean_authors_values)
    return out


def _formula_warnings(distribution: dict[str, Any], comparison: dict[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    readiness = distribution.get("chart_readiness") or {}
    if readiness.get("status") not in {"", "ok"}:
        warnings.append({"code": str(readiness.get("status") or "not_chartable"), "message": str(readiness.get("message") or "Распределение формулы неинформативно.")})
    tie_rate = comparison.get("tie_rate")
    if isinstance(tie_rate, (int, float)) and tie_rate > 0.5:
        warnings.append({"code": "high_tie_rate", "message": "У формулы высокая доля совпадающих значений; она слабо различает авторов."})
    for metric, value in (comparison.get("spearman_vs_core") or {}).items():
        if isinstance(value, (int, float)) and value > 0.98:
            warnings.append({"code": "duplicates_core_metric", "message": f"Формула почти дублирует показатель {metric}: Spearman {value:.3f}."})
            break
    return warnings


def _ordered_authors(rows: list[dict[str, Any]], metric: str) -> list[str]:
    return [
        str(row.get("author_id") or "")
        for row in sorted(rows, key=lambda row: (-float(row.get(metric) or 0.0), -float(row.get("c") or 0.0), -float(row.get("p") or 0.0), str(row.get("author_id") or "")))
        if str(row.get("author_id") or "")
    ]


def _spearman_from_rows(rows: list[dict[str, Any]], left: str, right: str) -> float | None:
    left_order = _ordered_authors(rows, left)
    right_order = _ordered_authors(rows, right)
    left_ranks = {author_id: index + 1 for index, author_id in enumerate(left_order)}
    right_ranks = {author_id: index + 1 for index, author_id in enumerate(right_order)}
    common = [author_id for author_id in left_ranks if author_id in right_ranks]
    if len(common) < 3:
        return None
    return _pearson([float(left_ranks[item]) for item in common], [float(right_ranks[item]) for item in common])


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum((x - mean_left) * (y - mean_right) for x, y in zip(left, right))
    denom_left = math.sqrt(sum((x - mean_left) ** 2 for x in left))
    denom_right = math.sqrt(sum((y - mean_right) ** 2 for y in right))
    return numerator / (denom_left * denom_right) if denom_left and denom_right else None


def _tie_rate(rows: list[dict[str, Any]], metric: str) -> float | None:
    values = [round(float(row.get(metric) or 0.0), 12) for row in rows]
    if not values:
        return None
    return 1.0 - (len(set(values)) / len(values))


def _write_validation_artifact(run_id: str, metric_id: str, doc: dict[str, Any]) -> Path:
    root = DATA / "runs" / _safe_id(run_id) / "formula_validation"
    path = root / f"{_safe_id(metric_id)}.json"
    _write_json(path, doc)
    return path


def _write_formula_passport(run_id: str, metric_id: str, validation: dict[str, Any]) -> Path:
    root = DATA / "runs" / _safe_id(run_id) / "metric_models"
    path = root / f"{_safe_id(metric_id)}.passport.json"
    passport = {
        "schema": "custom_metric_model.passport.v1",
        "formula_id": metric_id,
        "label": validation.get("label"),
        "expression": validation.get("expression"),
        "parameters": validation.get("parameters") or {},
        "base_fields": validation.get("base_fields") or [],
        "run_id": run_id,
        "dump_id": validation.get("dump_id"),
        "fraction_mode": validation.get("fraction_mode"),
        "analysis_protocol": validation.get("analysis_protocol_id"),
        "validation_summary": {
            "readiness": validation.get("readiness") or {},
            "comparison": validation.get("comparison") or {},
            "warnings": validation.get("warnings") or [],
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(path, passport)
    return path


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._-") or "formula"


def _safe_metric_id(value: str) -> str:
    text = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    if not text or not text[0].isalpha():
        text = f"custom_{text or 'formula'}"
    return text[:48]


def _write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
