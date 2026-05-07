from __future__ import annotations

import unittest

import _path  # noqa: F401
from openalex_dss.metrics import g_index, h_index, i10_index, iupv_from_percentiles, islv_from_percentiles


class IndexTests(unittest.TestCase):
    def test_h_index_empty(self) -> None:
        self.assertEqual(h_index([]), 0)

    def test_h_index_known_case(self) -> None:
        self.assertEqual(h_index([10, 8, 5, 4, 3]), 4)

    def test_g_index_known_case(self) -> None:
        self.assertEqual(g_index([10, 8, 5, 4, 3]), 5)

    def test_i10_index_threshold(self) -> None:
        self.assertEqual(i10_index([9, 10, 11, 0]), 2)

    def test_iupv_zero_when_component_zero(self) -> None:
        self.assertEqual(iupv_from_percentiles(0, 1.0, 1.0), 0.0)

    def test_iupv_percentile_geometric_mean(self) -> None:
        self.assertAlmostEqual(iupv_from_percentiles(1.0, 1.0, 0.5), 100.0 * (0.5 ** (1.0 / 3.0)))

    def test_iupv_monotone_in_percentile_components(self) -> None:
        self.assertLess(iupv_from_percentiles(0.5, 0.5, 0.5), iupv_from_percentiles(0.5, 0.5, 1.0))

    def test_islv_bounded_at_max_percentiles(self) -> None:
        self.assertAlmostEqual(islv_from_percentiles(1.0, 1.0, 1.0, 1.0, 1.0, 0.0), 100.0)

    def test_islv_penalizes_top1_concentration(self) -> None:
        stable = islv_from_percentiles(0.9, 0.9, 0.9, 0.9, 0.9, 0.50)
        concentrated = islv_from_percentiles(0.9, 0.9, 0.9, 0.9, 0.9, 1.0)
        self.assertLess(concentrated, stable)


if __name__ == "__main__":
    unittest.main()
