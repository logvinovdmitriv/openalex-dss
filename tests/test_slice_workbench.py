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

from app.services import slice_workbench  # noqa: E402


class SliceWorkbenchTests(unittest.TestCase):
    def test_slice_estimate_and_materialization_plan_keep_download_policy_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = {
                "slice_id": "slice_test",
                "entity_level": "subfield",
                "entity_id_short": "1706",
                "entity_id_full": "https://openalex.org/subfields/1706",
                "entity_display_name": "Computer Science Applications",
                "country_code": "RU",
                "from_publication_date": "2020-01-01",
                "to_publication_date": "2025-12-31",
                "work_type": "article|review",
                "download_policy": {
                    "complete_slice_required": True,
                    "allow_incomplete_preview": False,
                },
            }
            fake_plan = {
                "decision": {"status": "can_fetch", "can_execute": True, "reasons": [], "warnings": []},
                "estimate": {
                    "estimate_count": 1000,
                    "planned_records": 1000,
                    "api_requests_planned": 10,
                    "estimated_raw_mb": 12.5,
                    "estimated_raw_bytes": 12_500_000,
                },
                "openalex_filter": "primary_topic.subfield.id:1706,authorships.institutions.country_code:RU",
                "filter_classes": {"pushdown_openalex": ["subject", "country"]},
                "download_policy": {**payload["download_policy"], "user_controls_download_after_estimate": True},
                "limits": {"max_api_requests_per_job": 2000},
            }

            with (
                patch.object(slice_workbench, "SLICES_DIR", tmp_path / "slices"),
                patch.object(slice_workbench, "MATERIALIZATIONS_DIR", tmp_path / "materialization_plans"),
                patch.object(slice_workbench.query_planner, "plan_slice", return_value=fake_plan),
            ):
                created = slice_workbench.create_slice(payload)
                self.assertNotIn("limits", created["slice_definition"])
                self.assertEqual(created["download_policy_default"]["complete_slice_required"], True)

                estimate = slice_workbench.estimate_slice(created["slice_id"], {"download_policy": payload["download_policy"]})
                self.assertEqual(estimate["download_policy"]["user_controls_download_after_estimate"], True)

                materialization = slice_workbench.create_materialization_plan(
                    created["slice_id"],
                    {"storage_profile_id": "minimal_analytics", "download_policy": payload["download_policy"]},
                )
                self.assertEqual(materialization["source_strategy"], "openalex_cli")
                self.assertEqual(materialization["download_policy"]["complete_slice_required"], True)
                self.assertEqual(materialization["download_policy"]["user_controls_download_after_estimate"], True)
                self.assertEqual(materialization["state"], "planned")


if __name__ == "__main__":
    unittest.main()
