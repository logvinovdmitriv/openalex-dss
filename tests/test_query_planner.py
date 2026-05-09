from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps/api"
SRC = ROOT / "src"
for path in (API, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services import query_planner  # noqa: E402
from app.services.query_planner import choose_strategy  # noqa: E402


LIMITS = {
    "execution_limits": {},
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
            planned_api_requests=12,
            estimated_raw_bytes=30 * 1024 * 1024,
            limits=LIMITS,
        )
        self.assertEqual(decision["status"], "can_fetch")
        self.assertTrue(decision["can_execute"])

    def test_large_slice_warns_but_remains_user_decision(self) -> None:
        decision = choose_strategy(
            estimate_count=500_000,
            planned_api_requests=100,
            estimated_raw_bytes=200 * 1024 * 1024,
            limits=LIMITS,
        )
        self.assertEqual(decision["status"], "large_slice")
        self.assertTrue(decision["can_execute"])
        self.assertTrue(decision["user_decides_after_estimate"])

    def test_very_large_slice_warns_but_does_not_block(self) -> None:
        decision = choose_strategy(
            estimate_count=1_500_000,
            planned_api_requests=15_000,
            estimated_raw_bytes=4_000 * 1024 * 1024,
            limits=LIMITS,
        )
        self.assertEqual(decision["status"], "very_large_slice")
        self.assertTrue(decision["can_execute"])

    def test_no_data_does_not_execute(self) -> None:
        decision = choose_strategy(
            estimate_count=0,
            planned_api_requests=0,
            estimated_raw_bytes=0,
            limits=LIMITS,
        )
        self.assertEqual(decision["status"], "no_data")
        self.assertFalse(decision["can_execute"])

    def test_estimate_cache_hits_until_refresh_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = {"count": 0}

            def fake_fetch(_cfg: object, *, api_key: str = "") -> dict[str, int]:
                calls["count"] += 1
                return {"estimate_count": calls["count"], "api_requests_planned": 1, "estimated_raw_bytes": 10, "estimated_cli_metadata_bytes": 10}

            with (
                patch.object(query_planner, "DATA", root),
                patch.object(query_planner, "_estimate_cache_key", return_value="cache_key"),
                patch.object(query_planner, "_fetch_estimate", side_effect=fake_fetch),
            ):
                first, first_cache = query_planner._cached_estimate(object(), LIMITS, refresh=False)
                second, second_cache = query_planner._cached_estimate(object(), LIMITS, refresh=False)
                third, third_cache = query_planner._cached_estimate(object(), LIMITS, refresh=True)

        self.assertEqual(first["estimate_count"], 1)
        self.assertEqual(first_cache["status"], "miss")
        self.assertEqual(second["estimate_count"], 1)
        self.assertEqual(second_cache["status"], "hit")
        self.assertEqual(third["estimate_count"], 2)
        self.assertEqual(third_cache["status"], "refresh")


if __name__ == "__main__":
    unittest.main()
