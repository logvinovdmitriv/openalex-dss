from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps/api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from app.services.openalex_filter_ast import filter_relation, parse_filter_string  # noqa: E402


def test_filter_ast_order_independent_equal() -> None:
    assert filter_relation("type:article,from_publication_date:2020-01-01", "from_publication_date:2020-01-01,type:article") == "equal"


def test_filter_ast_or_sets_broader_narrower() -> None:
    assert filter_relation("type:article|review", "type:article") == "broader"
    assert filter_relation("type:article", "type:article|review") == "narrower"


def test_filter_ast_dates_and_numeric_ranges() -> None:
    assert filter_relation("from_publication_date:2020-01-01", "from_publication_date:2021-01-01") == "broader"
    assert filter_relation("to_publication_date:2024-12-31", "to_publication_date:2023-12-31") == "broader"
    assert filter_relation("cited_by_count:>5", "cited_by_count:>10") == "broader"


def test_filter_ast_negation_is_conservative() -> None:
    left = parse_filter_string("is_retracted:!true")
    assert left["is_retracted"].negated is True
    assert filter_relation("is_retracted:!true", "is_retracted:false") == "unknown"


def test_filter_ast_primary_topic_vs_topics_any_not_equal() -> None:
    assert filter_relation("primary_topic.subfield.id:2604", "topics.subfield.id:2604") == "unknown"
