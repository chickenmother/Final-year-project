"""Tests for the WS3.5 stage-chain executor model (``common/pipeline.py``)."""
import itertools
import json
import unittest

from common import pipeline
from common.pipeline import (
    PIXELS,
    STATE,
    Chain,
    ChannelStats,
    PipelineError,
    merge_channels,
    pixel_format,
    plan_tick,
)

STAGES = ("A", "B", "C", "D", "E")


def table(spec):
    """``table("XXYYY")`` -> A-E tiers (L stays on X, as the rules demand)."""
    return dict(zip(STAGES, spec), L="X")


class ChainTests(unittest.TestCase):
    def test_presets_route_like_their_names(self):
        cloud = Chain(table("XXXXX"))
        self.assertEqual(cloud.stages_of("X"), list(STAGES))
        self.assertEqual(cloud.stages_of("Y"), [])
        self.assertEqual(cloud.stream_tier, "X")
        self.assertFalse(cloud.pixel_channel)
        self.assertEqual(cloud.first()["tier"], "X")

        offload = Chain(table("YYXXX"))
        self.assertEqual(offload.local_run("A", "Y"), (["A", "B"], "C"))
        self.assertEqual(offload.local_run("C", "X"), (["C", "D", "E"], None))
        self.assertEqual(offload.route("B")["kind"], STATE)
        self.assertTrue(offload.route("B")["crossing"])
        self.assertFalse(offload.route("C")["crossing"])

        edge = Chain(table("YYYYY"))
        self.assertEqual(edge.stream_tier, "Y")
        self.assertEqual(edge.local_run("A", "X"), ([], "A"))

    def test_render_encode_split_routes_pixels(self):
        chain = Chain(table("XXXXY"))
        self.assertTrue(chain.pixel_channel)
        self.assertEqual(chain.route("D")["kind"], PIXELS)
        self.assertEqual(chain.local_run("A", "X"), (["A", "B", "C", "D"], "E"))
        self.assertEqual(chain.local_run("E", "Y"), (["E"], None))

    def test_split_ab_routes_state_twice(self):
        chain = Chain(table("XYXXX"))     # A on X, B on Y, C back on X
        self.assertEqual(chain.route("A")["kind"], STATE)
        self.assertEqual(chain.route("B")["next"], "C")
        self.assertEqual(chain.route("B")["kind"], STATE)
        self.assertEqual(len(chain.crossings), 2)
        self.assertEqual(chain.local_run("A", "X"), (["A"], "B"))
        self.assertEqual(chain.local_run("B", "Y"), (["B"], "C"))

    def test_plan_tick_is_a_dry_run(self):
        cloud = Chain(table("XXXXX"))
        self.assertEqual(plan_tick(cloud, "Y"),
                         {"run": [], "forward": "A", "kind": STATE})
        self.assertEqual(plan_tick(cloud, "x")["run"], list(STAGES))
        self.assertIsNone(plan_tick(cloud, "X")["forward"])
        edge = Chain(table("YYYYY"))
        self.assertEqual(plan_tick(edge, "Y")["run"], list(STAGES))
        self.assertEqual(plan_tick(edge, "X")["forward"], "A")
        split = Chain(table("XXXXY"))
        plan = plan_tick(split, "X")
        self.assertEqual(plan["forward"], "E")
        self.assertEqual(plan["kind"], PIXELS)

    def test_unknown_stage_is_rejected(self):
        with self.assertRaises(PipelineError):
            Chain(table("XXXXX")).route("Z")

    def test_every_assignment_is_executable(self):
        """All 32 A-E tables: each stage runs once, forwards == crossings."""
        for spec in itertools.product("XY", repeat=5):
            spec = "".join(spec)
            chain = Chain(table(spec))
            order, tier = [], "Y"            # a tick starts wherever A runs
            tier = chain.owner("A")
            stage, forwards = "A", 0
            while stage is not None:
                run, stage = chain.local_run(stage, tier)
                self.assertTrue(run, f"{spec} stuck on {stage}")
                order.extend(run)
                if stage is not None:
                    forwards += 1
                    tier = chain.owner(stage)
            self.assertEqual(order, list(STAGES), spec)
            self.assertEqual(forwards, len(chain.crossings), spec)
            self.assertTrue(set(chain.tasks.values()) <= {"X", "Y"})


class WireFormatTests(unittest.TestCase):
    """The custom chain's messages must survive a JSON/binary round trip."""

    def test_stage_message_without_state(self):
        msg = pipeline.stage_message("a", 41, 900, "d ")
        data = json.loads(msg)
        self.assertEqual(data["t"], "stage")
        self.assertEqual(data["stage"], "A")
        self.assertNotIn("s", data)
        self.assertEqual(pipeline.parse_stage(data),
                         ("A", 41, 900, "d ", None))

    def test_stage_message_with_state(self):
        snap = {"tick": 41, "score": 3}
        data = json.loads(pipeline.stage_message("C", 41, 900, "", snap))
        self.assertEqual(data["s"], snap)
        self.assertEqual(pipeline.parse_stage(data), ("C", 41, 900, "", snap))
        with self.assertRaises(pipeline.PipelineError):
            pipeline.parse_stage({"stage": "Q", "tick": 1, "seq": 1})
        with self.assertRaises(pipeline.PipelineError):
            pipeline.parse_stage({"stage": "A", "tick": "x", "seq": 1})

    def test_final_and_stride_messages(self):
        data = json.loads(pipeline.final_message(7, 3, {"tick": 7}))
        self.assertEqual((data["t"], data["tick"], data["s"]),
                         ("final", 7, {"tick": 7}))
        stride = json.loads(pipeline.stride_message("x", 0))
        self.assertEqual(stride, {"t": "stride", "src": "x", "n": 0})

    def test_pixels_round_trip(self):
        payload = b"\xff\xd8jpegdata"
        snap = {"tick": 12, "hp": 10}
        msg = pipeline.pixels_message(12, 4, "jpeg85", (1280, 720), snap, payload)
        self.assertEqual(msg[:1], b"p")
        tick, seq, fmt, size, state, data = pipeline.parse_pixels(msg)
        self.assertEqual((tick, seq, fmt, size), (12, 4, "jpeg85", (1280, 720)))
        self.assertEqual(state, snap)
        self.assertEqual(data, payload)

    def test_pixels_rejects_other_or_truncated_messages(self):
        self.assertIsNone(pipeline.parse_pixels(b"x" + b"\x00" * 20))
        self.assertIsNone(pipeline.parse_pixels("not bytes"))
        self.assertIsNone(pipeline.parse_pixels(b"p" + b"\x00" * 4))
        msg = pipeline.pixels_message(1, 1, "raw", (2, 2), None, b"\x00" * 4)
        self.assertIsNone(pipeline.parse_pixels(msg[:-8]))

    def test_bytes_per_tick(self):
        self.assertEqual(pipeline.bytes_per_tick("state", 9000, 60), 527.3)
        self.assertEqual(pipeline.bytes_per_tick("state", 9000, 0), 0.0)


class ChannelStatsTests(unittest.TestCase):
    def test_counters_and_snapshot(self):
        stats = ChannelStats()
        stats.crossing(STATE, 1000)
        stats.crossing(STATE, 500)
        stats.crossing(PIXELS, 90_000)
        stats.stage("A", 2.0)
        stats.stage("A", 4.0)
        stats.encoded(3.0)
        stats.stall(12)
        stats.stall(13)
        snap = stats.snapshot()
        self.assertEqual(snap["state_msgs"], 2)
        self.assertEqual(snap["state_bytes"], 1500)
        self.assertEqual(snap["pixel_msgs"], 1)
        self.assertEqual(snap["pixel_bytes"], 90_000)
        self.assertEqual(snap["stalls"], 2)
        self.assertEqual(snap["stall_ticks"], [12, 13])
        self.assertEqual(snap["encode_frames"], 1)
        self.assertEqual(snap["stage_p50"]["A"], 3.0)
        self.assertIsNone(snap["stage_p50"]["E"])

    def test_merge_adds_both_sides(self):
        a, b = ChannelStats(), ChannelStats()
        a.crossing(STATE, 10)
        b.crossing(PIXELS, 20)
        b.encoded()
        b.stall(7)
        b.mirror(99)
        merged = merge_channels(a, b)
        self.assertIs(merged, a)
        self.assertEqual(merged.state_msgs, 1)
        self.assertEqual(merged.pixel_msgs, 1)
        self.assertEqual(merged.encode_frames, 1)
        self.assertEqual(merged.mirror_bytes, 99)
        self.assertEqual(merged.stall_ticks, [7])

    def test_pixel_format_labels(self):
        self.assertEqual(pixel_format(), "jpeg")
        self.assertEqual(pixel_format(quality=85), "jpeg85")
        self.assertEqual(pixel_format(raw=True, quality=85), "raw")


if __name__ == "__main__":
    unittest.main()
