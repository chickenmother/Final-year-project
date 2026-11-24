"""Tests for the shared test-plan model."""
import json
import unittest

from common.testplan import (
    SUMMARY_KEYS,
    Event,
    PlanError,
    TestPlan,
    demo_plan,
    percentile,
    summarize,
    video_payload,
)


class TestPlanTests(unittest.TestCase):
    def test_valid_plan_round_trip(self):
        raw = {
            "name": "A1 delay sweep",
            "warmup_s": 5,
            "duration_s": 60,
            "seed": 42,
            "workload": "light",
            "mode": "auto",
            "video_preset": "A1",
            "input_pattern": "strafe",
            "events": [
                {"at_s": 25, "kind": "delay", "delay_ms": 0},
                {"at_s": 10, "kind": "delay", "delay_ms": 100, "hold_s": 15},
                {"at_s": 35, "kind": "mode", "mode": "edge", "hold_s": 10},
                {"at_s": 50, "kind": "pause", "hold_s": 5},
            ],
        }
        plan = TestPlan.from_dict(raw)
        self.assertEqual(plan.name, "A1 delay sweep")
        self.assertEqual(plan.video_settings()["gop"], 120)
        # to_dict sorts events by time
        times = [e["at_s"] for e in plan.to_dict()["events"]]
        self.assertEqual(times, sorted(times))
        again = TestPlan.from_dict(json.loads(json.dumps(plan.to_dict())))
        self.assertEqual(again.to_dict(), plan.to_dict())

    def test_mode_override_mapping(self):
        self.assertIsNone(TestPlan(mode="auto").mode_override())
        self.assertEqual(TestPlan(mode="cloud").mode_override(), "X")
        self.assertEqual(TestPlan(mode="edge").mode_override(), "Y")

    def test_rejects_bad_values(self):
        with self.assertRaises(PlanError):
            TestPlan.from_dict({"duration_s": 0})
        with self.assertRaises(PlanError):
            TestPlan.from_dict({"duration_s": 60,
                                "events": [{"at_s": 1, "kind": "delay",
                                            "delay_ms": 500}]})
        with self.assertRaises(PlanError):
            TestPlan.from_dict({"duration_s": 60,
                                "events": [{"at_s": 61, "kind": "delay"}]})
        with self.assertRaises(PlanError):
            TestPlan.from_dict({"duration_s": 60,
                                "events": [{"at_s": 1, "kind": "pause"}]})
        with self.assertRaises(PlanError):
            TestPlan.from_dict({"workload": "insane"})
        with self.assertRaises(PlanError):
            TestPlan.from_dict({"mode": "laggy"})
        with self.assertRaises(PlanError):
            TestPlan.from_dict({"input_pattern": "jump"})

    def test_event_values_and_labels(self):
        delay = Event.from_dict({"at_s": 2, "kind": "delay", "delay_ms": 80})
        self.assertEqual(delay.value(), 80)
        self.assertIn("80", delay.label())
        mode = Event.from_dict({"at_s": 1, "kind": "mode", "mode": "edge"})
        self.assertEqual(mode.value(), "edge")
        pattern = Event.from_dict({"at_s": 1, "kind": "pattern",
                                   "pattern": "circle"})
        self.assertEqual(pattern.value(), "circle")

    def test_segments_cover_timeline(self):
        plan = TestPlan(
            duration_s=20,
            events=[
                Event(at_s=5, kind="delay", delay_ms=100, hold_s=5),
                Event(at_s=12, kind="mode", mode="edge", hold_s=3),
                Event(at_s=15, kind="pause", hold_s=2),
            ],
        )
        delay = [s for s in plan.segments() if s.kind == "delay"]
        self.assertEqual(delay[0].value, 0)
        self.assertTrue(any(s.value == 100 and s.start_s == 5 for s in delay))
        mode = [s for s in plan.segments() if s.kind == "mode"]
        self.assertTrue(any(s.value == "edge" for s in mode))
        pauses = [s for s in plan.segments() if s.kind == "pause"]
        self.assertEqual(pauses[0].start_s, 15)
        self.assertEqual(pauses[0].end_s, 17)

    def test_percentile(self):
        self.assertIsNone(percentile([], 0.5))
        self.assertEqual(percentile([5], 0.9), 5)
        values = list(range(1, 101))
        self.assertAlmostEqual(percentile(values, 0.50), 50.5)
        self.assertAlmostEqual(percentile(values, 0.90), 90.1)

    def test_summary_skips_paused_and_missing(self):
        samples = [
            {"e2e": 10, "rtt": 30, "paused": False, "x_encode": None},
            {"e2e": 20, "rtt": 40, "paused": False},
            {"e2e": 999, "rtt": 999, "paused": True},
        ]
        summary = summarize(samples)
        self.assertEqual(summary["e2e"]["n"], 2)
        self.assertEqual(summary["e2e"]["max"], 20)
        self.assertEqual(summary["e2e"]["p50"], 15)
        self.assertEqual(summary["x_encode"]["n"], 0)

    def test_demo_plan_is_valid(self):
        plan = demo_plan()
        plan.validate()
        self.assertEqual(plan.duration_s, 10)
        self.assertEqual(len(plan.events), 2)

    def test_video_payload_for_presets(self):
        a0 = video_payload("A0")
        self.assertEqual(a0["t"], "video")
        self.assertEqual(a0["gop"], 30)
        self.assertEqual(a0["size"], [1280, 720])
        self.assertFalse(a0["intra_refresh"])
        a2 = video_payload("a2")                  # case-insensitive
        self.assertEqual(a2["size"], [960, 540])
        self.assertEqual(a2["gop"], 120)
        intra = video_payload("intra")
        self.assertTrue(intra["intra_refresh"])
        self.assertIsNone(video_payload("current"))
        self.assertIsNone(video_payload("nope"))
        json.dumps(a0)                            # must be wire-ready

    def test_video_command_matches_preset(self):
        plan = TestPlan(video_preset="A1")
        command = plan.video_command()
        self.assertEqual(command["gop"], 120)
        self.assertEqual(command["size"], [1280, 720])
        self.assertIsNone(TestPlan(video_preset="current").video_command())

    def test_summary_covers_runtime_video_metrics(self):
        self.assertIn("x_encode", SUMMARY_KEYS)
        self.assertIn("x_encode_p95", SUMMARY_KEYS)
        self.assertIn("x_kf", SUMMARY_KEYS)

    def test_placement_axis(self):
        self.assertEqual(TestPlan().placement, "legacy")
        plan = TestPlan.from_dict({"placement": "All_Cloud"})
        self.assertEqual(plan.placement, "all_cloud")
        self.assertEqual(plan.to_dict()["placement"], "all_cloud")
        table = plan.placement_table()
        self.assertEqual(table["L"], "X")
        self.assertEqual(table["A"], "X")
        self.assertIsNone(TestPlan(placement="legacy").placement_table())
        with self.assertRaises(PlanError):
            TestPlan.from_dict({"placement": "k8s"})



if __name__ == "__main__":
    unittest.main()
