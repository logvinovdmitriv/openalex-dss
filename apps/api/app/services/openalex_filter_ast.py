from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Relation = Literal["equal", "broader", "narrower", "overlap", "unknown"]


@dataclass(frozen=True)
class FilterCondition:
    field: str
    values: tuple[str, ...]


def parse_filter_string(value: str) -> dict[str, FilterCondition]:
    """Parse the OpenAlex comma filter subset used by the workbench.

    The parser intentionally avoids claiming support for the full OpenAlex
    grammar. Unsupported fragments are kept as opaque field/value pairs, which
    makes compatibility checks conservative instead of silently treating raw
    filters as compatible.
    """

    out: dict[str, FilterCondition] = {}
    for part in _split_filter_parts(value):
        if ":" not in part:
            out[f"__raw__:{part}"] = FilterCondition(f"__raw__:{part}", (part,))
            continue
        field, raw = part.split(":", 1)
        field = _normalize_token(field)
        values = tuple(sorted({_normalize_value(item) for item in raw.split("|") if _normalize_value(item)}))
        if not field or not values:
            continue
        out[field] = FilterCondition(field, values)
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
    if set(left_ast) & set(right_ast):
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
    if left.values == right.values:
        return "equal"
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


def _split_filter_parts(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _normalize_token(value: str) -> str:
    return str(value or "").strip().lower()


def _normalize_value(value: str) -> str:
    text = str(value or "").strip().strip('"').strip("'")
    if text.startswith(("https://openalex.org/", "http://openalex.org/")):
        text = text.rstrip("/").rsplit("/", 1)[-1]
    return text.lower()
