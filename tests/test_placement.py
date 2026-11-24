"""Tests for the WS3.1 task-placement model."""
import unittest

from common.placement import (
    TASKS,
    PlacementError,
    TaskStats,
    describe,
    describe_chain,
    edge_pipeline,
    merge_metrics,
    next_stage,
    owners,
    pattern_table,
    remote_ab,
    render_tier,
    resolve_chain,
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

    def test_render_tier_follows_the_pattern(self):
        self.assertEqual(render_tier(pattern_table("all_cloud")), "X")
        self.assertEqual(render_tier(pattern_table("offload_ab")), "X")
        self.assertEqual(render_tier(pattern_table("all_edge")), "Y")
        self.assertIsNone(render_tier({}))

    def test_remote_ab_only_for_offload(self):
        self.assertFalse(remote_ab(pattern_table("all_cloud")))
        self.assertTrue(remote_ab(pattern_table("offload_ab")))
        self.assertTrue(remote_ab(pattern_table("all_edge")))
        self.assertFalse(remote_ab({}))

    def test_edge_pipeline_only_when_all_edge(self):
        self.assertFalse(edge_pipeline(pattern_table("all_cloud")))
        self.assertFalse(edge_pipeline(pattern_table("offload_ab")))
        self.assertTrue(edge_pipeline(pattern_table("all_edge")))
        self.assertFalse(edge_pipeline({}))


class ChainTests(unittest.TestCase):
    """WS3.5: any table is described as a stage chain with its crossings."""

    def test_all_cloud_has_no_crossing(self):
        chain = resolve_chain(pattern_table("all_cloud"))
        self.assertEqual(chain["crossings"], [])
        self.assertEqual(chain["stream_tier"], "X")
        self.assertFalse(chain["pixel_channel"])

    def test_offload_ab_is_one_state_crossing(self):
        chain = resolve_chain(pattern_table("offload_ab"))
        self.assertEqual(len(chain["crossings"]), 1)
        self.assertEqual(chain["crossings"][0]["kind"], "state")
        self.assertEqual(chain["crossings"][0]["src"], "Y")
        self.assertEqual(chain["crossings"][0]["dst"], "X")
        self.assertEqual(chain["stream_tier"], "X")

    def test_pipeline_on_y_with_sim_on_x(self):
        table = {"A": "X", "B": "X", "C": "Y", "D": "Y", "E": "Y", "L": "X"}
        chain = resolve_chain(table)
        self.assertEqual(len(chain["crossings"]), 1)
        self.assertEqual(chain["crossings"][0]["from"], "B")
        self.assertEqual(chain["crossings"][0]["to"], "C")
        self.assertEqual(chain["stream_tier"], "Y")

    def test_split_ab_costs_two_crossings(self):
        table = {"A": "X", "B": "Y", "C": "X", "D": "X", "E": "X", "L": "X"}
        chain = resolve_chain(table)
        self.assertEqual(len(chain["crossings"]), 2)
        self.assertEqual([item["kind"] for item in chain["crossings"]],
                         ["state", "state"])
        self.assertEqual(chain["state_crossings"], 2)

    def test_render_encode_split_uses_the_pixel_channel(self):
        table = {"A": "X", "B": "X", "C": "X", "D": "X", "E": "Y", "L": "X"}
        chain = resolve_chain(table)
        self.assertTrue(chain["pixel_crossing"])
        self.assertEqual(chain["crossings"][0]["kind"], "pixels")
        self.assertEqual(chain["stream_tier"], "Y")

    def test_next_stage(self):
        self.assertEqual(next_stage("A"), "B")
        self.assertEqual(next_stage("D"), "E")
        self.assertIsNone(next_stage("E"))
        self.assertIsNone(next_stage("Z"))

    def test_describe_chain_mentions_groups_and_crossings(self):
        text = describe_chain(pattern_table("offload_ab"))
        self.assertIn("A/B on Y", text)
        self.assertIn("C/D/E on X", text)
        self.assertIn("1 crossing", text)
        self.assertIn("stream from X", text)

    def test_describe_chain_without_crossing(self):
        text = describe_chain(pattern_table("all_cloud"))
        self.assertNotIn("crossing", text)


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
