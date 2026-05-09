from __future__ import annotations

import ast
import json
import math
import re
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.paths import DATA


BASE_NUMERIC_FIELDS = {
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
}

ALLOWED_FUNCTIONS = {
    "abs": abs,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "log": math.log,
    "log1p": math.log1p,
    "exp": math.exp,
    "pow": pow,
    "round": round,
    "floor": math.floor,
    "ceil": math.ceil,
}

SQL_FUNCTIONS = {
    "abs": "abs",
    "sqrt": "sqrt",
    "log": "ln",
    "log1p": "log1p",
    "exp": "exp",
    "pow": "pow",
    "round": "round",
    "floor": "floor",
    "ceil": "ceil",
}

ALLOWED_NAMES = set(BASE_NUMERIC_FIELDS) | {f"pr_{field}" for field in BASE_NUMERIC_FIELDS} | {"pi", "e"}
SAFE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,48}$")


def parse_custom_metrics(raw: str | list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> list[dict[str, str]]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Пользовательские формулы должны быть переданы как JSON.") from exc
    else:
        payload = raw
    if not isinstance(payload, list):
        raise ValueError("Пользовательские формулы должны быть списком.")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError("Каждая пользовательская формула должна быть объектом.")
        expression = str(item.get("expression") or "").strip()
        if not expression:
            continue
        metric_id = _metric_id(str(item.get("id") or ""), index)
        if metric_id in seen:
            raise ValueError(f"Повторяется идентификатор пользовательской формулы: {metric_id}.")
        label = str(item.get("label") or "").strip() or f"Пользовательская формула {index}"
        description = str(item.get("description") or "").strip()
        _compile_expression(expression)
        seen.add(metric_id)
        out.append({"id": metric_id, "label": label[:120], "description": description[:500], "expression": expression})
    if len(out) > 20:
        raise ValueError("Можно передать не более 20 пользовательских формул за один расчет.")
    return out


def apply_custom_metrics(rows: list[dict[str, Any]], definitions: list[dict[str, str]] | None) -> list[dict[str, Any]]:
    definitions = definitions or []
    if not definitions or not rows:
        return rows
    percentile_fields = _percentile_fields(definitions)
    percentile_maps = {
        field: _percentile_rank_map(rows, field)
        for field in percentile_fields
        if field in BASE_NUMERIC_FIELDS
    }
    compiled = [(definition, _compile_expression(definition["expression"])) for definition in definitions]
    context_names = sorted({name for _, expression in compiled for name in _expression_names(expression)})
    out: list[dict[str, Any]] = []
    for row in rows:
        next_row = dict(row)
        context = _row_context(next_row, percentile_maps, context_names)
        for definition, expression in compiled:
            metric_id = definition["id"]
            try:
                value = float(_eval_expression(expression, context))
            except (ArithmeticError, ValueError, OverflowError):
                value = 0.0
            if not math.isfinite(value):
                value = 0.0
            next_row[metric_id] = value
        out.append(next_row)
    return out


def custom_metric_ids(definitions: list[dict[str, str]] | None) -> set[str]:
    return {definition["id"] for definition in definitions or []}


def referenced_base_fields(definitions: list[dict[str, str]] | None) -> set[str]:
    fields: set[str] = set()
    for definition in definitions or []:
        expression = _compile_expression(definition["expression"])
        for name in _expression_names(expression):
            base_name = name[3:] if name.startswith("pr_") else name
            if base_name in BASE_NUMERIC_FIELDS:
                fields.add(base_name)
    return fields


def metric_catalog(definitions: list[dict[str, str]] | None) -> list[dict[str, str]]:
    return [
        {
            "value": definition["id"],
            "label": definition["label"],
            "description": definition.get("description") or "Пользовательская формула, рассчитанная по текущей выборке.",
            "formula": definition["expression"],
        }
        for definition in definitions or []
    ]


def list_metric_models(run_id: str) -> list[dict[str, Any]]:
    run_id = _safe_run_id(run_id)
    if not run_id:
        raise ValueError("Для сохраненных формул нужен выбранный расчет.")
    root = _metric_models_dir(run_id)
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in root.glob("*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict) and doc.get("id") and doc.get("expression"):
            items.append(doc)
    return sorted(items, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)


def save_metric_model(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    run_id = _safe_run_id(run_id)
    if not run_id:
        raise ValueError("Выберите расчет, к которому нужно сохранить формулу.")
    definition = parse_custom_metrics([payload])
    if not definition:
        raise ValueError("Введите формулу перед сохранением.")
    item = definition[0]
    now = _utc_now()
    path = _metric_model_path(run_id, item["id"])
    created_at = now
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            created_at = str(existing.get("created_at") or now)
        except (OSError, json.JSONDecodeError):
            created_at = now
    doc = {
        "schema": "custom_metric_model",
        "id": item["id"],
        "label": item["label"],
        "description": item.get("description") or "Пользовательская формула, рассчитанная по текущей выборке.",
        "expression": item["expression"],
        "enabled": bool(payload.get("enabled", True)),
        "created_at": created_at,
        "updated_at": now,
    }
    _write_json(path, doc)
    return doc


def delete_metric_model(run_id: str, model_id: str) -> dict[str, Any]:
    run_id = _safe_run_id(run_id)
    model_id = _metric_id(model_id, 1)
    if not run_id:
        raise ValueError("Выберите расчет, из которого нужно удалить формулу.")
    path = _metric_model_path(run_id, model_id)
    if path.is_file():
        path.unlink()
        return {"deleted": True, "id": model_id}
    return {"deleted": False, "id": model_id}


def metric_models_as_definitions(run_id: str) -> list[dict[str, str]]:
    return [
        {
            "id": str(item["id"]),
            "label": str(item["label"]),
            "description": str(item.get("description") or ""),
            "expression": str(item["expression"]),
        }
        for item in list_metric_models(run_id)
        if item.get("enabled", True)
    ]


def duckdb_percentile_expressions(definitions: list[dict[str, str]] | None, available_fields: set[str]) -> list[str]:
    expressions: list[str] = []
    for field in sorted(_percentile_fields(definitions or [])):
        alias = _quote_identifier(f"pr_{field}")
        if field not in available_fields:
            expressions.append(f"0.0 AS {alias}")
        else:
            expressions.append(f"COALESCE(percent_rank() OVER (ORDER BY TRY_CAST({_quote_identifier(field)} AS DOUBLE)), 0.0) AS {alias}")
    return expressions


def _metric_models_dir(run_id: str) -> Path:
    return DATA / "runs" / _safe_run_id(run_id) / "metric_models"


def _metric_model_path(run_id: str, model_id: str) -> Path:
    return _metric_models_dir(run_id) / f"{_metric_id(model_id, 1)}.json"


def _safe_run_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._-")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def duckdb_metric_expressions(definitions: list[dict[str, str]] | None, available_fields: set[str]) -> list[str]:
    out: list[str] = []
    for definition in definitions or []:
        expression = _compile_expression(definition["expression"])
        out.append(f"{_duckdb_expression(expression, available_fields)} AS {_quote_identifier(definition['id'])}")
    return out


def _metric_id(raw: str, index: int) -> str:
    text = raw.strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = f"custom_formula_{index}"
    if not text.startswith("custom_"):
        text = f"custom_{text}"
    if not SAFE_ID_RE.match(text):
        text = f"custom_formula_{index}"
    return text[:48]


def _compile_expression(expression: str) -> ast.Expression:
    if len(expression) > 500:
        raise ValueError("Формула слишком длинная.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("Формула содержит синтаксическую ошибку.") from exc
    _validate_node(tree)
    return tree


def _validate_node(node: ast.AST) -> None:
    allowed_nodes = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.Mod,
        ast.USub,
        ast.UAdd,
        ast.Constant,
        ast.Name,
        ast.Load,
        ast.Call,
    )
    if not isinstance(node, allowed_nodes):
        raise ValueError("Формула содержит неподдерживаемую операцию.")
    if isinstance(node, ast.Name) and node.id not in ALLOWED_NAMES:
        raise ValueError(f"Неизвестное поле в формуле: {node.id}.")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCTIONS:
            raise ValueError("Формула содержит неподдерживаемую функцию.")
        if len(node.args) > 4 or node.keywords:
            raise ValueError("Функции в формуле принимают только позиционные аргументы.")
    for child in ast.iter_child_nodes(node):
        _validate_node(child)


def _expression_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id not in {"pi", "e"} and child.id not in ALLOWED_FUNCTIONS:
            names.add(child.id)
    return names


def _eval_expression(node: ast.AST, context: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval_expression(node.body, context)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError("В формуле разрешены только числовые константы.")
    if isinstance(node, ast.Name):
        if node.id == "pi":
            return math.pi
        if node.id == "e":
            return math.e
        return float(context.get(node.id, 0.0))
    if isinstance(node, ast.UnaryOp):
        value = _eval_expression(node.operand, context)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
    if isinstance(node, ast.BinOp):
        left = _eval_expression(node.left, context)
        right = _eval_expression(node.right, context)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return 0.0 if right == 0 else left / right
        if isinstance(node.op, ast.Mod):
            return 0.0 if right == 0 else left % right
        if isinstance(node.op, ast.Pow):
            return left**right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = ALLOWED_FUNCTIONS[node.func.id]
        return float(fn(*[_eval_expression(arg, context) for arg in node.args]))
    raise ValueError("Формула содержит неподдерживаемое выражение.")


def _duckdb_expression(node: ast.AST, available_fields: set[str]) -> str:
    if isinstance(node, ast.Expression):
        return _duckdb_expression(node.body, available_fields)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return repr(float(node.value))
        raise ValueError("В формуле разрешены только числовые константы.")
    if isinstance(node, ast.Name):
        if node.id == "pi":
            return repr(math.pi)
        if node.id == "e":
            return repr(math.e)
        if node.id.startswith("pr_"):
            return f"COALESCE({_quote_identifier(node.id)}, 0.0)" if node.id in available_fields else "0.0"
        if node.id in BASE_NUMERIC_FIELDS:
            return f"COALESCE(TRY_CAST({_quote_identifier(node.id)} AS DOUBLE), 0.0)" if node.id in available_fields else "0.0"
        raise ValueError(f"Неизвестное поле в формуле: {node.id}.")
    if isinstance(node, ast.UnaryOp):
        value = _duckdb_expression(node.operand, available_fields)
        if isinstance(node.op, ast.USub):
            return f"(-({value}))"
        if isinstance(node.op, ast.UAdd):
            return f"({value})"
    if isinstance(node, ast.BinOp):
        left = _duckdb_expression(node.left, available_fields)
        right = _duckdb_expression(node.right, available_fields)
        if isinstance(node.op, ast.Add):
            return f"(({left}) + ({right}))"
        if isinstance(node.op, ast.Sub):
            return f"(({left}) - ({right}))"
        if isinstance(node.op, ast.Mult):
            return f"(({left}) * ({right}))"
        if isinstance(node.op, ast.Div):
            return f"(CASE WHEN ({right}) = 0 THEN 0.0 ELSE ({left}) / ({right}) END)"
        if isinstance(node.op, ast.Mod):
            return f"(CASE WHEN ({right}) = 0 THEN 0.0 ELSE ({left}) % ({right}) END)"
        if isinstance(node.op, ast.Pow):
            return f"pow(({left}), ({right}))"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        args = [_duckdb_expression(arg, available_fields) for arg in node.args]
        if node.func.id == "min":
            return f"least({', '.join(args)})"
        if node.func.id == "max":
            return f"greatest({', '.join(args)})"
        sql_fn = SQL_FUNCTIONS.get(node.func.id)
        if sql_fn:
            return f"{sql_fn}({', '.join(args)})"
    raise ValueError("Формула содержит неподдерживаемое выражение.")


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _row_context(row: dict[str, Any], percentile_maps: dict[str, dict[int, float]], names: list[str]) -> dict[str, float]:
    context: dict[str, float] = {}
    row_id = id(row)
    for name in names:
        if name.startswith("pr_"):
            context[name] = percentile_maps.get(name[3:], {}).get(row_id, 0.0)
        elif name in BASE_NUMERIC_FIELDS:
            context[name] = _as_float(row.get(name))
    return context


def _percentile_fields(definitions: list[dict[str, str]]) -> set[str]:
    fields: set[str] = set()
    for definition in definitions:
        for name in re.findall(r"\bpr_([a-z][a-z0-9_]*)\b", definition.get("expression") or ""):
            fields.add(name)
    return fields


def _percentile_rank_map(rows: list[dict[str, Any]], field: str) -> dict[int, float]:
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("fraction_mode") or "")].append(row)
    out: dict[int, float] = {}
    for group in groups.values():
        values = sorted(_as_float(row.get(field)) for row in group)
        n = len(values)
        if n <= 1:
            for row in group:
                out[id(row)] = 1.0
            continue
        for row in group:
            value = _as_float(row.get(field))
            rank = bisect_right(values, value)
            out[id(row)] = max(0.0, min(1.0, (rank - 1) / (n - 1)))
    return out


def _as_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        out = float(value)
        return out if math.isfinite(out) else 0.0
    except (TypeError, ValueError):
        return 0.0
