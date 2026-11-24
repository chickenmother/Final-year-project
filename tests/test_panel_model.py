"""Tests for the WS2.2 panel model (no Tk, no websocket)."""
import json
import tempfile
import unittest
from pathlib import Path

from common.testplan import PlanError
from tools import panel_model as pm


class PlanEditingTests(unittest.TestCase):
    def test_blank_plan_is_valid(self):
        plan = pm.blank_plan()
        plan.validate()
        self.assertEqual(plan.events, [])

    def test_build_plan_coerces_form_strings(self):
        plan = pm.build_plan({"name": "form", "warmup_s": "2", "duration_s": "15",
                              "seed": "7", "workload": "LIGHT", "mode": "Cloud",
                              "video_preset": "a1", "input_pattern": "Strafe"})
        self.assertEqual(plan.duration_s, 15.0)
        self.assertEqual(plan.seed, 7)
        self.assertEqual(plan.workload, "light")
        self.assertEqual(plan.mode, "cloud")
        self.assertEqual(plan.video_preset, "A1")
        self.assertEqual(plan.input_pattern, "strafe")

    def test_build_plan_rejects_bad_values(self):
        with self.assertRaises(PlanError):
            pm.build_plan({"duration_s": "0"})
        with self.assertRaises(PlanError):
            pm.build_plan({"workload": "insane"})

    def test_update_plan_keeps_events(self):
        plan = pm.add_event(pm.blank_plan(), 5, "delay", 100)
        updated = pm.update_plan(plan, {"name": "renamed", "duration_s": 30})
        self.assertEqual(updated.name, "renamed")
        self.assertEqual(updated.duration_s, 30.0)
        self.assertEqual(len(updated.events), 1)
        self.assertEqual(plan.name, "WS2.2 panel run")   # original untouched

    def test_build_plan_carries_a_custom_table(self):
        fields = {"name": "split", "placement": "custom"}
        tasks = {"A": "X", "B": "Y", "C": "Y", "D": "Y", "E": "Y", "L": "X"}
        plan = pm.build_plan(fields, (), tasks)
        self.assertEqual(plan.placement, "custom")
        self.assertEqual(plan.placement_tasks, tasks)
        # a preset ignores the rows, so the plan stays preset-shaped
        preset = pm.build_plan({"placement": "all_cloud"}, (), tasks)
        self.assertEqual(preset.placement, "all_cloud")
        self.assertEqual(preset.placement_tasks, {})

    def test_update_plan_keeps_the_custom_table(self):
        tasks = {"A": "Y", "B": "Y", "C": "X", "D": "X", "E": "X", "L": "X"}
        plan = pm.build_plan({"name": "chain", "placement": "custom"}, (), tasks)
        updated = pm.update_plan(plan, {"duration_s": 45})
        self.assertEqual(updated.placement_tasks, tasks)
        self.assertEqual(updated.duration_s, 45.0)

    def test_preset_tasks_and_tasks_for(self):
        self.assertEqual(pm.preset_tasks("offload_ab")["A"], "Y")
        self.assertEqual(pm.preset_tasks("legacy")["A"], "X")
        self.assertEqual(pm.preset_tasks("legacy")["L"], "X")
        plan = pm.blank_plan()
        self.assertEqual(pm.tasks_for(plan), pm.preset_tasks("legacy"))
        tasks = {"A": "Y", "B": "Y", "C": "Y", "D": "Y", "E": "Y", "L": "X"}
        custom = pm.build_plan({"placement": "custom"}, (), tasks)
        self.assertEqual(pm.tasks_for(custom), tasks)

    def test_chain_summary_and_titles(self):
        self.assertIn("legacy", pm.chain_summary({}))
        summary = pm.chain_summary(pm.preset_tasks("offload_ab"))
        self.assertIn("1 crossing", summary)
        self.assertIn("state", summary)
        self.assertIn("stream from X", summary)
        split = dict(pm.preset_tasks("all_cloud"), E="Y")
        self.assertIn("pixels channel", pm.chain_summary(split))
        self.assertEqual(pm.stage_title("A"), "A simulation")
        self.assertEqual(pm.stage_title("L"), "L leaderboard")
        self.assertEqual(pm.TASK_ROWS, ("A", "B", "C", "D", "E", "L"))

    def test_plan_text_round_trip(self):
        plan = pm.add_event(pm.blank_plan(), 5, "pause", hold_s=2)
        again = pm.plan_from_text(pm.plan_text(plan))
        self.assertEqual(again.to_dict(), plan.to_dict())

    def test_plan_from_text_reports_bad_input(self):
        with self.assertRaises(PlanError):
            pm.plan_from_text("{not json", source="broken.json")
        with self.assertRaises(PlanError):
            pm.plan_from_text(json.dumps({"duration_s": 0}))
        with self.assertRaises(PlanError):
            pm.plan_from_text(json.dumps([1, 2, 3]))

    def test_plan_from_text_tolerates_bom(self):
        plan = pm.blank_plan("bom")
        again = pm.plan_from_text("\ufeff" + json.dumps(plan.to_dict()))
        self.assertEqual(again.to_dict(), plan.to_dict())


    def test_save_and_load_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plans" / "custom.json"
            plan = pm.add_event(pm.blank_plan("saved"), 3, "mode", "edge")
            written = pm.save_plan(path, plan)
            self.assertEqual(written, path)
            loaded = pm.load_plan(path)
            self.assertEqual(loaded.to_dict(), plan.to_dict())
            self.assertEqual(pm.plan_files(path.parent), [path])
            self.assertEqual(pm.plan_files(Path(tmp) / "missing"), [])

    def test_add_event_variants(self):
        plan = pm.blank_plan()
        plan = pm.add_event(plan, "5", "delay", "100", "3")
        plan = pm.add_event(plan, 10, "mode", "edge", 4)
        plan = pm.add_event(plan, 20, "pattern", "shoot")
        plan = pm.add_event(plan, 30, "pause", None, 2)
        self.assertEqual([e.kind for e in plan.sorted_events()],
                         ["delay", "mode", "pattern", "pause"])
        self.assertEqual(plan.sorted_events()[0].delay_ms, 100)
        self.assertEqual(plan.sorted_events()[0].hold_s, 3.0)
        self.assertEqual(plan.sorted_events()[2].pattern, "shoot")

    def test_add_event_rejects_bad_kind_and_out_of_window(self):
        plan = pm.blank_plan("window")
        with self.assertRaises(PlanError):
            pm.add_event(plan, 1, "teleport")
        with self.assertRaises(PlanError):
            pm.add_event(plan, plan.duration_s + 5, "delay", 10)
        with self.assertRaises(PlanError):
            pm.add_event(plan, 1, "delay", 999)

    def test_remove_event(self):
        plan = pm.blank_plan()
        plan = pm.add_event(plan, 10, "delay", 50)
        plan = pm.add_event(plan, 20, "pause", None, 3)
        trimmed = pm.remove_event(plan, 0)
        self.assertEqual([e.kind for e in trimmed.events], ["pause"])
        with self.assertRaises(PlanError):
            pm.remove_event(plan, 5)

    def test_event_rows_are_sorted(self):
        plan = pm.blank_plan()
        plan = pm.add_event(plan, 20, "pause", None, 2)
        plan = pm.add_event(plan, 5, "delay", 80)
        rows = pm.event_rows(plan)
        self.assertEqual([row["at_s"] for row in rows], ["5", "20"])
        self.assertEqual(rows[0]["index"], 0)
        self.assertEqual(rows[1]["kind"], "pause")

    def test_timeline_rows(self):
        plan = pm.blank_plan("timeline")
        plan = pm.add_event(plan, 0, "delay", 100, 30)
        plan = pm.add_event(plan, 30, "pause", None, 10)
        rows = {row["kind"]: row for row in pm.timeline_rows(plan, width=20)}
        self.assertEqual(set(rows), set(pm.EVENT_KINDS))
        for row in rows.values():
            self.assertEqual(len(row["bar"]), 20)
        # the baseline delay/mode/pattern segments cover the whole window
        self.assertEqual(rows["delay"]["bar"], "=" * 20)
        self.assertEqual(rows["mode"]["bar"], "M" * 20)
        self.assertEqual(rows["pattern"]["bar"], "i" * 20)
        # pause only marks its own hold window
        self.assertIn("x", rows["pause"]["bar"])
        self.assertIn(" ", rows["pause"]["bar"])
        self.assertIn("100 ms", rows["delay"]["labels"])
        self.assertIn("0-60s strafe", rows["pattern"]["labels"])
        self.assertIn("x= pause", pm.timeline_legend())


class LiveStateTests(unittest.TestCase):
    def test_progress_idle_and_running(self):
        idle = pm.progress({})
        self.assertEqual(idle["state"], "idle")
        self.assertEqual(idle["progress"], 0.0)
        state = {"test": {"state": "running", "elapsed_s": 12.34,
                          "duration_s": 60, "remaining_s": 47.66,
                          "progress": 0.2,
                          "next_event": {"label": "delay 0 ms"}}}
        running = pm.progress(state)
        self.assertEqual(running["label"], "running 12.3/60.0 s")
        self.assertEqual(running["next"], "delay 0 ms")
        self.assertAlmostEqual(running["progress"], 0.2)

    def test_progress_warmup_finished_error_and_clamp(self):
        warmup = pm.progress({"test": {"state": "warmup", "warmup_left_s": 3.5}})
        self.assertIn("warm-up 3.5 s", warmup["label"])
        finished = pm.progress({"test": {"state": "finished", "elapsed_s": 60}})
        self.assertIn("finished after 60.0 s", finished["label"])
        failed = pm.progress({"test": {"state": "error", "error": "no Z"}})
        self.assertIn("no Z", failed["label"])
        clamped = pm.progress({"test": {"state": "running", "progress": 5}})
        self.assertEqual(clamped["progress"], 1.0)

    def test_metrics_formatting(self):
        state = {"mode": "X", "linked": True, "paused": False,
                 "rtt": 63.04, "delay_ms": 0, "e2e": 79.2, "rtt_zy": None,
                 "x_fps": 60, "y_fps": 30.02,
                 "z_stats": {"fps": 59.8, "decode": 2.9}}
        values = pm.metrics(state)
        self.assertEqual(values["mode"], "X")
        self.assertEqual(values["linked"], "yes")
        self.assertEqual(values["rtt"], "63")
        self.assertEqual(values["e2e"], "79")
        self.assertEqual(values["y_fps"], "30.0")
        self.assertEqual(values["z_fps"], "59.8")
        self.assertEqual(values["rtt_zy"], "-")
        self.assertEqual(pm.metrics({})["mode"], "-")
        self.assertEqual(pm.fmt("abc"), "abc")

    def test_metrics_from_x_stats_and_applied_video(self):
        state = {"x_stats": {"encode_p50": 5.44, "encode_p95": 8.06,
                             "keyframes_s": 0.52, "frame_kb": 110.4},
                 "x_video": {"size": [1280, 720], "gop": 120,
                             "intra_refresh": False}}
        values = pm.metrics(state)
        self.assertEqual(values["x_encode"], "5.4")
        self.assertEqual(values["x_encode_p95"], "8.1")
        self.assertEqual(values["x_kf"], "0.52")
        self.assertEqual(values["x_kb"], "110.4")
        self.assertEqual(values["x_video"], "1280x720 GOP 120")
        intra = pm.metrics({"x_video": {"size": [960, 540], "gop": 120,
                                        "intra_refresh": True}})
        self.assertEqual(intra["x_video"], "960x540 GOP 120 intra")
        self.assertEqual(pm.metrics({})["x_encode"], "-")
        self.assertEqual(pm.video_label(None), "-")

    def test_metrics_placement_and_task_lines(self):
        state = {"placement": {"A": "X", "B": "X", "C": "X", "D": "X",
                               "E": "X", "L": "X"},
                 "task_stats": {"sim": {"X": {"n": 60, "p50": 1.2},
                                        "Y": {"n": 60, "p50": 0.4}},
                                "render": {"X": {"n": 60, "p50": 2.5}},
                                "encode": {}}}
        values = pm.metrics(state)
        self.assertIn("A/B/C/D/E/L on X", values["placement"])
        self.assertEqual(values["task_sim"], "X 1.2 / Y 0.40")
        self.assertEqual(values["task_render"], "X 2.5")
        self.assertEqual(values["task_encode"], "-")
        self.assertEqual(pm.metrics({})["placement"], "legacy whole-pipeline")

    def test_sub_millisecond_task_p50_keeps_two_decimals(self):
        state = {"task_stats": {"sim": {"X": {"p50": 0.02},
                                        "Y": {"p50": 0.014}}}}
        self.assertEqual(pm.metrics(state)["task_sim"], "X 0.02 / Y 0.01")

    def test_hit_and_offload_lines(self):
        state = {"task_stats": {"hit": {"X": {"p50": 0.42}, "Y": {"p50": 0.31}}},
                 "offload": {"n": 58, "bytes": 62000, "kb_s": 60.5,
                             "total": 744000}}
        values = pm.metrics(state)
        self.assertEqual(values["task_hit"], "X 0.42 / Y 0.31")
        self.assertEqual(values["offload"], "60.5 KB/s · 727 kB")
        self.assertEqual(pm.metrics({})["task_hit"], "-")
        self.assertEqual(pm.metrics({})["offload"], "-")

    def test_placement_payload(self):
        self.assertEqual(pm.placement_payload("all_cloud"),
                         {"cmd": "placement", "pattern": "all_cloud"})
        self.assertEqual(pm.placement_payload("legacy"),
                         {"cmd": "placement", "pattern": "legacy"})
        with self.assertRaises(PlanError):
            pm.placement_payload("k8s")


    def test_buttons_per_phase(self):
        self.assertTrue(pm.buttons("idle")["start"])
        self.assertFalse(pm.buttons("running")["start"])
        self.assertTrue(pm.buttons("running")["pause"])
        self.assertTrue(pm.buttons("paused")["resume"])
        self.assertTrue(pm.buttons("warmup")["stop"])
        self.assertFalse(pm.buttons("warmup")["edit"])
        self.assertFalse(pm.buttons("starting")["pause"])
        self.assertTrue(pm.buttons("finished")["start"])
        self.assertTrue(pm.buttons("error")["edit"])


class ProtocolTests(unittest.TestCase):
    def test_payloads(self):
        plan = pm.blank_plan("payload")
        self.assertEqual(pm.hello_payload(), {"cmd": "hello"})
        self.assertEqual(pm.start_payload(plan)["plan"], plan.to_dict())
        self.assertEqual(pm.preview_payload(plan)["cmd"], "set_plan")
        self.assertEqual(pm.control_payload("pause"), {"cmd": "test_pause"})
        self.assertEqual(pm.control_payload("stop"), {"cmd": "test_stop"})
        self.assertEqual(pm.report_payload(7), {"cmd": "get_report", "id": "7"})
        self.assertEqual(pm.list_payload(), {"cmd": "list_reports"})
        with self.assertRaises(ValueError):
            pm.control_payload("launch")

    def test_x_runtime_payloads(self):
        self.assertEqual(pm.x_video_payload("A1"),
                         {"cmd": "x_video", "preset": "A1"})
        self.assertEqual(pm.x_video_payload("intra"),
                         {"cmd": "x_video", "preset": "intra"})
        self.assertIsNone(pm.x_video_payload("current"))
        self.assertEqual(pm.x_stats_payload(), {"cmd": "x_stats", "on": True})
        self.assertEqual(pm.x_stats_payload(False),
                         {"cmd": "x_stats", "on": False})
        self.assertEqual(pm.x_stop_payload(), {"cmd": "x_stop"})

    def test_parse_message(self):
        state = {"mode": "X", "rtt": 60, "test": {"state": "running"}}
        self.assertEqual(pm.parse_message(json.dumps(state))["kind"], "state")
        self.assertEqual(pm.parse_message(b'{"t": "hello", "reports": []}')["kind"],
                         "hello")
        self.assertEqual(pm.parse_message('{"t": "report", "report": {}}')["kind"],
                         "report")
        self.assertEqual(pm.parse_message('{"t": "error", "message": "x"}')["kind"],
                         "error")
        self.assertIsNone(pm.parse_message("not json"))
        self.assertIsNone(pm.parse_message("[1, 2]"))
        self.assertIsNone(pm.parse_message('{"t": "snap"}'))

    def test_phase_helper(self):
        self.assertEqual(pm.phase({}), "idle")
        self.assertEqual(pm.phase({"test": {"state": "paused"}}), "paused")


class ReportTests(unittest.TestCase):
    def test_summary_line(self):
        summary = {"e2e": {"n": 5, "p50": 79.24, "p90": 108.9},
                   "rtt": {"n": 5, "p50": 63.0}, "z_fps": {"n": 0}}
        line = pm.summary_line(summary)
        self.assertIn("e2e p50 79.2", line)
        self.assertIn("rtt p50 63.0", line)
        self.assertNotIn("z_fps", line)
        self.assertEqual(pm.summary_line({}), "-")

    def test_report_rows(self):
        rows = pm.report_rows([
            {"id": "20261123-153034", "date": "2026-11-23", "time": "15:30:34",
             "name": "WS1.3-A1", "summary": {"e2e": {"n": 1, "p50": 79.0}}},
            {"id": "x"},
        ])
        self.assertEqual(rows[0]["id"], "20261123-153034")
        self.assertEqual(rows[0]["when"], "2026-11-23 15:30:34")
        self.assertIn("e2e p50 79.0", rows[0]["detail"])
        self.assertEqual(rows[1]["detail"], "-")

    def test_report_csv(self):
        report = {"samples": [{"t": 0, "e2e": 10},
                              {"t": 1, "e2e": 20, "mode": "X"}]}
        lines = pm.report_csv(report).strip().splitlines()
        self.assertEqual(lines[0], "t,e2e,mode")
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[1].startswith("0,10"))
        self.assertEqual(pm.report_csv({}).strip(), "t")


class EndZTests(unittest.TestCase):
    def test_y_host(self):
        self.assertEqual(pm.y_host("ws://127.0.0.1:8002"), "127.0.0.1")
        self.assertEqual(pm.y_host("ws://192.168.0.182:8002/"), "192.168.0.182")
        self.assertEqual(pm.y_host("ws://[::1]:8002"), "::1")
        self.assertEqual(pm.y_host("192.168.0.5"), "192.168.0.5")
        self.assertEqual(pm.y_host(""), "")

    def test_z_env(self):
        env = pm.z_env({"SDL_VIDEODRIVER": "dummy", "PATH": "x"},
                       "ws://192.168.0.182:8002")
        self.assertEqual(env["FYP_TEST"], "1")
        self.assertEqual(env["FYP_Y_IP"], "192.168.0.182")
        self.assertNotIn("SDL_VIDEODRIVER", env)
        self.assertEqual(env["PATH"], "x")
        self.assertEqual(pm.z_env({}, "")["FYP_Y_IP"], "127.0.0.1")

    def test_z_command(self):
        command = pm.z_command(Path("C:/repo"))
        self.assertTrue(command[0].replace("\\", "/").endswith(
            "venv/Scripts/python.exe"))
        self.assertEqual(command[1:], ["-u", "z_client.py"])


if __name__ == "__main__":
    unittest.main()


