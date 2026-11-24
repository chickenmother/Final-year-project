"""Tests for the WS3.1 task-placement model."""
import unittest

from common.placement import (
    TASKS,
    PlacementError,
    TaskStats,
    describe,
    merge_metrics,
    owners,
    pattern_table,
    validate,
)


class PatternTests(unittest.TestCase):
    def test_all_cloud_puts_every_task_on_x(self):
        table = pattern_table("all_cloud")
        self.assertEqual(set(table), set(TASKS))
        self.assertTrue(all(tier == "X" for tier in table.values()))

    def test_all_edge_keeps_l_on_x(self):
        table = pattern_table("all_edge")
        for task in ("A", "B", "C", "D", "E"):
            self.assertEqual(table[task], "Y")
        self.assertEqual(table["L"], "X")

    def test_offload_ab(self):
        table = pattern_table("offload_ab")
        self.assertEqual(table["A"], "Y")
        self.assertEqual(table["B"], "Y")
        self.assertEqual(table["C"], "X")
        self.assertEqual(table["L"], "X")

    def test_legacy_has_no_table(self):
        self.assertIsNone(pattern_table("legacy"))
        self.assertIsNone(pattern_table("LEGACY"))

    def test_unknown_pattern(self):
        with self.assertRaises(PlacementError):
            pattern_table("k8s")

    def test_names_are_case_and_space_insensitive(self):
        self.assertEqual(pattern_table(" All_Cloud "), pattern_table("all_cloud"))


class ValidationTests(unittest.TestCase):
    def test_rejects_moving_pinned_l(self):
        with self.assertRaises(PlacementError):
            validate({"L": "Y"})

    def test_rejects_local_u(self):
        with self.assertRaises(PlacementError):
            validate({"U": "Y"})

    def test_rejects_unknown_task_and_tier(self):
        with self.assertRaises(PlacementError):
            validate({"Z": "X"})
        with self.assertRaises(PlacementError):
            validate({"A": "Z"})
        with self.assertRaises(PlacementError):
            validate({})

    def test_requires_all_tasks_when_asked(self):
        with self.assertRaises(PlacementError):
            validate({"A": "X"}, require_all=True)
        full = validate(pattern_table("all_cloud"), require_all=True)
        self.assertEqual(full["L"], "X")

    def test_partial_table_is_normalised(self):
        self.assertEqual(validate({"A": "x", "c": " y "}),
                         {"A": "X", "C": "Y"})

    def test_owners_and_describe(self):
        table = pattern_table("offload_ab")
        self.assertEqual(owners(table, "Y"), ["A", "B"])
        self.assertEqual(owners(table, "X"), ["C", "D", "E", "L"])
        self.assertIn("A/B on Y", describe(table))
        self.assertIn("U on Z", describe(table))
        self.assertEqual(describe({}), "legacy whole-pipeline")


class TaskStatsTests(unittest.TestCase):
    def test_p50_and_p95_per_tier(self):
        stats = TaskStats(window=10)
        for value in (1, 2, 3, 4, 5):
            stats.add("sim", value, "Y")
        stats.add("sim", 9, "X")
        snap = stats.snapshot()
        self.assertEqual(snap["sim"]["Y"]["n"], 5)
        self.assertEqual(snap["sim"]["Y"]["p50"], 3.0)
        self.assertEqual(snap["sim"]["X"]["p50"], 9.0)

    def test_window_and_reset(self):
        stats = TaskStats(window=5)
        for value in range(10):
            stats.add("render", value)
        self.assertEqual(stats.snapshot()["render"]["Y"]["n"], 5)
        stats.reset()
        self.assertEqual(stats.snapshot(), {})

    def test_ignores_bad_values(self):
        stats = TaskStats()
        stats.add("encode", "nan")
        stats.add("encode", -1)
        stats.add("encode", None)
        self.assertEqual(stats.snapshot(), {})
        with self.assertRaises(PlacementError):
            stats.add("teleport", 1)

    def test_merge_with_x_stats_and_hops(self):
        local = {"sim": {"Y": {"n": 5, "p50": 0.4}}}
        x_stats = {"sim_p50": 1.2, "render_p50": 2.5, "encode_p50": 4.0,
                   "frames": 60}
        merged = merge_metrics(local, x_stats, rtt=12.3, rtt_zy=3.2)
        self.assertEqual(merged["sim"]["Y"]["p50"], 0.4)
        self.assertEqual(merged["sim"]["X"]["p50"], 1.2)
        self.assertEqual(merged["render"]["X"]["p50"], 2.5)
        self.assertEqual(merged["encode"]["X"]["p50"], 4.0)
        self.assertEqual(merged["net"]["X"]["p50"], 12.3)
        self.assertEqual(merged["net"]["Z"]["p50"], 3.2)

    def test_merge_skips_missing_values(self):
        self.assertEqual(merge_metrics({}, {"sim_p50": None}), {})


if __name__ == "__main__":
    unittest.main()
