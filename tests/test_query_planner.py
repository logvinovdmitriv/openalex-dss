from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps/api"
SRC = ROOT / "src"
for path in (API, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.query_planner import choose_strategy  # noqa: E402


LIMITS = {
    "execution_limits": {
        "max_works_per_slice_hard": 300_000,
        "max_api_requests_per_job": 2_000,
    },
    "planner_thresholds": {
        "small_slice_works": 50_000,
        "medium_slice_works": 300_000,
        "hard_stop_works": 1_000_000,
    },
}


class QueryPlannerTests(unittest.TestCase):
    def test_small_slice_can_fetch(self) -> None:
        decision = choose_strategy(
            estimate_count=1200,
            max_works=1200,
            planned_api_requests=12,
            estimated_raw_bytes=30 * 1024 * 1024,
            max_dump_bytes=300 * 1024 * 1024,
            limits=LIMITS,
        )
        self.assertEqual(decision["status"], "can_fetch")
        self.assertTrue(decision["can_execute"])

    def test_large_slice_warns_when_limited(self) -> None:
        decision = choose_strategy(
            estimate_count=500_000,
            max_works=10_000,
            planned_api_requests=100,
            estimated_raw_bytes=200 * 1024 * 1024,
            max_dump_bytes=300 * 1024 * 1024,
            limits=LIMITS,
        )
        self.assertEqual(decision["status"], "should_narrow")
        self.assertTrue(decision["can_execute"])

    def test_request_limit_blocks(self) -> None:
        decision = choose_strategy(
            estimate_count=250_000,
            max_works=250_000,
            planned_api_requests=2_500,
            estimated_raw_bytes=600 * 1024 * 1024,
            max_dump_bytes=300 * 1024 * 1024,
            limits=LIMITS,
        )
        self.assertEqual(decision["status"], "blocked")
        self.assertFalse(decision["can_execute"])


if __name__ == "__main__":
    unittest.main()
