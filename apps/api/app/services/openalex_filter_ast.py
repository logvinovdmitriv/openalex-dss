from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Relation = Literal["equal", "broader", "narrower", "overlap", "unknown"]


@dataclass(frozen=True)
class FilterCondition:
    field: str
    values: tuple[str, ...]
    operator: str = "eq"
    negated: bool = False


def parse_filter_string(value: str) -> dict[str, FilterCondition]:
    """Parse the OpenAlex comma filter subset used by the workbench.

    The parser intentionally avoids claiming support for the full OpenAlex
    grammar. Unsupported fragments are kept as opaque field/value pairs, which
    makes relation checks conservative instead of silently treating raw
    filters as compatible.
    """

    out: dict[str, FilterCondition] = {}
    for part in _split_filter_parts(value):
        if ":" not in part:
            out[f"__raw__:{part}"] = FilterCondition(f"__raw__:{part}", (part,))
            continue
        field, raw = part.split(":", 1)
        field = _normalize_token(field)
        negated_field = field.startswith("!")
        if negated_field:
            field = field[1:]
        operator, raw = _parse_operator(raw)
        values = tuple(sorted({_normalize_value(item) for item in raw.split("|") if _normalize_value(item)}))
        negated = negated_field or operator == "neq" or any(value.startswith("!") for value in values)
        if negated:
            values = tuple(sorted({value[1:] if value.startswith("!") else value for value in values if value}))
        if not field or not values:
            continue
        out[field] = FilterCondition(field, values, operator=operator, negated=negated)
    return out


def filter_relation(left: str, right: str) -> Relation:
    """Return relation of left corpus to right corpus.

    broader means the left filter can contain all records matching right and
    possibly more. narrower means the left filter is a strict subset.
    """

    left_ast = parse_filter_string(left)
    right_ast = parse_filter_string(right)
    if not left_ast or not right_ast:
        return "unknown"
    if left_ast == right_ast:
        return "equal"
    left_covers_right = _covers(left_ast, right_ast)
    right_covers_left = _covers(right_ast, left_ast)
    if left_covers_right and not right_covers_left:
        return "broader"
    if right_covers_left and not left_covers_right:
        return "narrower"
    if left_covers_right and right_covers_left:
        return "equal"
    shared = set(left_ast) & set(right_ast)
    if shared and any(_condition_relation(left_ast[field], right_ast[field]) == "overlap" for field in shared):
        return "overlap"
    return "unknown"


def _covers(candidate: dict[str, FilterCondition], target: dict[str, FilterCondition]) -> bool:
    """True when candidate filter is not narrower than target."""

    for field, candidate_condition in candidate.items():
        target_condition = target.get(field)
        if target_condition is None:
            return False
        relation = _condition_relation(candidate_condition, target_condition)
        if relation not in {"equal", "broader"}:
            return False
    return True


def _condition_relation(left: FilterCondition, right: FilterCondition) -> Relation:
    if left.field != right.field:
        return "unknown"
    if left.negated or right.negated:
        return "equal" if left == right else "unknown"
    if left.operator != right.operator:
        return _range_condition_relation(left, right)
    if left.values == right.values:
        return "equal"
    if left.operator in {">", ">=", "<", "<="}:
        return _range_condition_relation(left, right)
    if left.field.startswith("from_"):
        left_value = left.values[0]
        right_value = right.values[0]
        if left_value <= right_value:
            return "broader"
        return "narrower"
    if left.field.startswith("to_"):
        left_value = left.values[0]
        right_value = right.values[0]
        if left_value >= right_value:
            return "broader"
        return "narrower"
    left_values = set(left.values)
    right_values = set(right.values)
    if left_values.issuperset(right_values):
        return "broader"
    if left_values.issubset(right_values):
        return "narrower"
    if left_values & right_values:
        return "overlap"
    return "unknown"


def _range_condition_relation(left: FilterCondition, right: FilterCondition) -> Relation:
    if left.field != right.field or left.negated or right.negated:
        return "unknown"
    if not left.values or not right.values:
        return "unknown"
    if left.operator == right.operator and left.values == right.values:
        return "equal"
    if left.operator in {">", ">="} and right.operator in {">", ">="}:
        left_value = _comparable_value(left.values[0])
        right_value = _comparable_value(right.values[0])
        if left_value <= right_value:
            return "broader"
        return "narrower"
    if left.operator in {"<", "<="} and right.operator in {"<", "<="}:
        left_value = _comparable_value(left.values[0])
        right_value = _comparable_value(right.values[0])
        if left_value >= right_value:
            return "broader"
        return "narrower"
    return "unknown"


def _split_filter_parts(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _normalize_token(value: str) -> str:
    return str(value or "").strip().lower()


def _parse_operator(raw: str) -> tuple[str, str]:
    text = str(raw or "").strip()
    for op in (">=", "<=", "!=", ">", "<", "!"):
        if text.startswith(op):
            return ("neq" if op in {"!", "!="} else op), text[len(op) :].strip()
    return "eq", text


def _comparable_value(value: str) -> float | str:
    try:
        return float(str(value))
    except ValueError:
        return str(value)


def _normalize_value(value: str) -> str:
    text = str(value or "").strip().strip('"').strip("'")
    if text.startswith(("https://openalex.org/", "http://openalex.org/")):
        text = text.rstrip("/").rsplit("/", 1)[-1]
    return text.lower()
