"""Tests for the Cloud X rolling encoder statistics (WS2.3)."""
import unittest

from common.xstats import FrameStats


class FrameStatsTests(unittest.TestCase):
    def test_empty_snapshot(self):
        snap = FrameStats().snapshot()
        self.assertEqual(snap["frames"], 0)
        self.assertEqual(snap["fps"], 0.0)
        self.assertIsNone(snap["encode_p50"])
        self.assertIsNone(snap["encode_p95"])
        self.assertEqual(snap["keyframes_s"], 0.0)
        self.assertEqual(snap["frame_kb"], 0.0)

    def test_fps_encode_and_sizes(self):
        stats = FrameStats(window_s=2.0)
        for index in range(61):                   # 1 s of 60 fps frames
            stats.add(5.0, 100_000, key=(index == 0), when=1000.0 + index / 60)
        snap = stats.snapshot(when=1001.0)
        self.assertAlmostEqual(snap["fps"], 60.0, delta=2.0)
        self.assertEqual(snap["encode_p50"], 5.0)
        self.assertEqual(snap["encode_p95"], 5.0)
        self.assertAlmostEqual(snap["frame_kb"], 97.7, delta=0.3)
        self.assertAlmostEqual(snap["keyframes_s"], 1.0, delta=0.1)
        self.assertEqual(snap["frames"], 61)

    def test_percentiles(self):
        stats = FrameStats(window_s=5.0)
        for index, encode in enumerate((2.0, 4.0, 6.0, 8.0)):
            stats.add(encode, 1000, when=10.0 + index / 100)
        snap = stats.snapshot(when=10.05)
        self.assertAlmostEqual(snap["encode_p50"], 5.0)
        self.assertAlmostEqual(snap["encode_p95"], 7.7, places=2)

    def test_window_prunes_old_frames(self):
        stats = FrameStats(window_s=1.0)
        stats.add(9.0, 10, when=0.0)
        stats.add(3.0, 10, when=0.5)
        snap = stats.snapshot(when=1.2)
        self.assertEqual(snap["frames"], 1)       # only the 0.5 s frame remains
        self.assertEqual(snap["encode_p50"], 3.0)

    def test_short_window_does_not_explode_fps(self):
        stats = FrameStats(window_s=2.0)
        stats.add(4.0, 1000, when=50.0)
        snap = stats.snapshot(when=50.0)
        self.assertAlmostEqual(snap["fps"], 4.0)  # 1 frame / 0.25 s floor

    def test_reset(self):
        stats = FrameStats()
        stats.add(4.0, 1000)
        stats.reset()
        self.assertEqual(stats.snapshot()["frames"], 0)

    def test_mature_needs_half_a_second(self):
        stats = FrameStats()
        self.assertFalse(stats.mature(when=10.0))
        stats.add(4.0, 1000, when=10.0)
        self.assertFalse(stats.mature(when=10.2))
        self.assertTrue(stats.mature(when=10.6))
        self.assertTrue(stats.mature(when=11.0, min_span=0.9))

    def test_snapshot_is_json_safe(self):
        import json
        stats = FrameStats()
        stats.add(4.25, 2048, key=True, when=5.0)
        json.dumps(stats.snapshot(when=5.0))


if __name__ == "__main__":
    unittest.main()
