"""Tests for the WS4.2 report comparison."""
import unittest

from common import compare as cmp


def _report(report_id, placement, e2e=15.0, p90=16.0, fps=60.0,
            workload="medium", offload=None, task_stats=None):
    return {
        "id": report_id,
        "duration_s": 12.0,
        "plan": {"placement": placement, "workload": workload,
                 "video_preset": "A1"},
        "environment": {
            "placement": placement,
            "placement_applied": placement != "legacy",
            "mode_final": "Y" if placement == "all_edge" else "X",
            "task_stats": task_stats or {},
            "offload": offload or {},
        },
        "summary": {
            "e2e": {"n": 50, "p50": e2e, "p90": p90, "p99": p90 + 1},
            "rtt": {"n": 50, "p50": 2.0, "p90": 3.0},
            "x_fps": {"n": 50, "p50": fps},
            "y_fps": {"n": 50, "p50": fps},
            "z_fps": {"n": 50, "p50": fps},
            "x_encode": {"n": 50, "p50": 5.5},
            "x_encode_p95": {"n": 50, "p50": 6.0},
            "z_decode": {"n": 50, "p50": 2.5},
        },
        "samples": [{"t": index * 0.2} for index in range(10)],
    }


class SummariseTests(unittest.TestCase):
    def test_flattens_metrics_and_tasks(self):
        report = _report("20260101-000001", "offload_ab", e2e=14.5,
                         offload={"kb_s": 530.0, "total": 2000},
                         task_stats={"sim": {"Y": {"p50": 0.06}},
                                     "render": {"X": {"p50": 0.7}},
                                     "net": {"Z": {"p50": 3.0}}})
        row = cmp.summarise(report)
        self.assertEqual(row["placement"], "offload_ab")
        self.assertEqual(row["e2e_p50"], 14.5)
        self.assertEqual(row["samples"], 10)
        self.assertEqual(row["sim_y"], 0.06)
        self.assertEqual(row["render_x"], 0.7)
        self.assertIsNone(row["render_y"])
        self.assertEqual(row["offload_kb_s"], 530.0)

    def test_missing_environment_defaults_to_legacy(self):
        row = cmp.summarise({"id": "x", "plan": {}, "environment": {},
                             "summary": {}, "samples": []})
        self.assertEqual(row["placement"], "legacy")
        self.assertFalse(row["placement_applied"])
        self.assertIsNone(row["e2e_p50"])


class SelectionTests(unittest.TestCase):
    def test_pick_newest_per_placement(self):
        reports = [
            _report("20260101-000001", "all_cloud", e2e=20.0),
            _report("20260102-000001", "all_cloud", e2e=15.0),
            _report("20260103-000001", "all_edge", e2e=13.0),
        ]
        rows = cmp.pick(reports)
        self.assertEqual([row["placement"] for row in rows],
                         ["all_cloud", "all_edge"])
        self.assertEqual(rows[0]["id"], "20260102-000001")   # newest kept

    def test_workload_and_placement_filters(self):
        reports = [
            _report("20260101-000001", "all_cloud", workload="light"),
            _report("20260102-000001", "all_cloud", workload="medium"),
            _report("20260103-000001", "offload_ab", workload="medium"),
        ]
        rows = cmp.pick(reports, workload="medium")
        self.assertEqual(len(rows), 2)
        only = cmp.pick(reports, placements=("offload_ab",))
        self.assertEqual([row["placement"] for row in only], ["offload_ab"])

    def test_rows_are_sorted_by_pattern_order(self):
        reports = [_report("20260103-000001", "all_edge"),
                   _report("20260101-000001", "all_cloud"),
                   _report("20260102-000001", "offload_ab")]
        self.assertEqual([row["placement"] for row in cmp.pick(reports)],
                         ["all_cloud", "offload_ab", "all_edge"])


class DeltaTests(unittest.TestCase):
    def test_delta_against_all_cloud(self):
        rows = cmp.compare([_report("20260101-000001", "all_cloud", e2e=15.0),
                            _report("20260102-000001", "offload_ab", e2e=16.5),
                            _report("20260103-000001", "all_edge", e2e=13.0)])
        by_placement = {row["placement"]: row for row in rows}
        self.assertEqual(by_placement["all_cloud"]["e2e_p50_delta"], 0.0)
        self.assertAlmostEqual(by_placement["offload_ab"]["e2e_p50_delta"], 1.5)
        self.assertAlmostEqual(by_placement["offload_ab"]["e2e_pct"], 10.0)
        self.assertAlmostEqual(by_placement["all_edge"]["e2e_p50_delta"], -2.0)

    def test_no_baseline_leaves_deltas_empty(self):
        rows = cmp.compare([_report("20260101-000001", "all_edge", e2e=13.0)])
        self.assertIsNone(rows[0]["e2e_p50_delta"])
        self.assertIsNone(rows[0]["e2e_pct"])


class OutputTests(unittest.TestCase):
    def test_markdown_table(self):
        rows = cmp.compare([_report("20260101-000001", "all_cloud", e2e=15.0),
                            _report("20260102-000001", "offload_ab", e2e=16.5,
                                    offload={"kb_s": 530.0},
                                    task_stats={"render": {"X": {"p50": 0.7}},
                                                "encode": {"X": {"p50": 5.6}}})])
        text = cmp.markdown(rows)
        header = text.splitlines()[0]
        self.assertIn("e2e p50", header)
        self.assertIn("all_cloud", text)
        self.assertIn("+1.50 ms (+10.0%)", text)
        self.assertIn("X 0.70", text)
        self.assertIn("530.0 KB/s", text)
        self.assertIn("—", text)          # missing values stay explicit

    def test_csv_round_trip(self):
        rows = cmp.compare([_report("20260101-000001", "all_cloud")])
        text = cmp.csv_text(rows)
        header = text.splitlines()[0]
        self.assertTrue(header.startswith("id,placement,placement_applied"))
        self.assertIn("20260101-000001,all_cloud", text)
        self.assertEqual(len(text.strip().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
