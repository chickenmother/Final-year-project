"""Tests for per-test report files."""
import csv
import json
import tempfile
import time
import unittest
from pathlib import Path

from common import report as report_mod
from common.testplan import demo_plan


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = report_mod.report_dir(self.temp.name)
        self.plan = demo_plan()
        self.samples = [
            {"t": 0.0, "rtt": 31.0, "e2e": 70.0, "paused": False},
            {"t": 0.2, "rtt": 33.0, "e2e": 75.0, "paused": False},
            {"t": 0.4, "rtt": 99.0, "e2e": 999.0, "paused": True},
        ]

    def tearDown(self):
        self.temp.cleanup()

    def test_build_and_write(self):
        report = report_mod.build(
            self.plan, 1_700_000_000.0, 1_700_000_010.0, self.samples,
            [{"at_s": 2.0, "kind": "delay", "delay_ms": 100}],
            environment={"mode": "X"}, report_id="20261119-171500")
        paths = report_mod.write(self.dir, report)
        self.assertTrue(Path(paths["json"]).is_file())
        self.assertTrue(Path(paths["csv"]).is_file())
        loaded = report_mod.load(self.dir, "20261119-171500")
        self.assertEqual(loaded["id"], "20261119-171500")
        expected_date = time.strftime("%Y-%m-%d",
                                      time.localtime(1_700_000_000.0))
        self.assertEqual(loaded["date"], expected_date)
        self.assertEqual(loaded["duration_s"], 10.0)
        self.assertEqual(loaded["summary"]["e2e"]["n"], 2)
        self.assertEqual(loaded["summary"]["e2e"]["max"], 75.0)
        with open(paths["csv"], newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["e2e"], "70.0")

    def test_list_reports_newest_first(self):
        for rid in ("20261119-170000", "20261119-171500"):
            report = report_mod.build(self.plan, 1_700_000_000.0,
                                      1_700_000_010.0, self.samples, [],
                                      report_id=rid)
            report_mod.write(self.dir, report)
        listed = report_mod.list_reports(self.dir)
        self.assertEqual([r["id"] for r in listed],
                         ["20261119-171500", "20261119-170000"])
        self.assertEqual(listed[0]["name"], self.plan.name)
        self.assertEqual(listed[0]["summary"]["rtt"]["n"], 2)

    def test_load_accepts_filename(self):
        report = report_mod.build(self.plan, 1_700_000_000.0,
                                  1_700_000_010.0, self.samples, [],
                                  report_id="abc")
        report_mod.write(self.dir, report)
        self.assertEqual(report_mod.load(self.dir, "abc.json")["id"], "abc")

    def test_missing_report_raises(self):
        with self.assertRaises(OSError):
            report_mod.load(self.dir, "does-not-exist")

    def test_report_dir_creates_nested_path(self):
        self.assertEqual(self.dir, Path(self.temp.name) / "logs" / "reports")
        self.assertTrue(self.dir.is_dir())


if __name__ == "__main__":
    unittest.main()
