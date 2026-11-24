"""Smoke test: build the Tk panel, pump the event loop, close it.

Skips on machines without a display (CI); the headless logic lives in
``tools/panel_model.py`` and is covered by ``tests/test_panel_model.py``.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import tkinter as tk
    from tools import panel_model, test_panel
    TK_AVAILABLE = True
except Exception:            # pragma: no cover - headless environments
    TK_AVAILABLE = False


@unittest.skipUnless(TK_AVAILABLE, "tkinter is not available")
class PanelSmokeTests(unittest.TestCase):
    def test_window_builds_and_closes(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:      # no display / Tcl without Tk
            self.skipTest(f"no Tk display: {exc}")
        root.withdraw()                 # do not flash a window during tests
        app = test_panel.PanelApp(root, uri="ws://127.0.0.1:9", plan=None)
        try:
            for _ in range(5):
                root.update()
            self.assertIn(app.plan.name, ("WS2.2 panel run",))
            self.assertEqual(len(app.form_vars), len(panel_model.PLAN_FIELDS))
            # the controls follow the phase helper
            app._refresh_buttons("running")
            self.assertEqual(str(app.controls["start"]["state"]), "disabled")
            self.assertEqual(str(app.controls["pause"]["state"]), "normal")
        finally:
            app.on_close()

    def test_focus_window_is_safe(self):
        self.assertIn(test_panel.focus_window("no-such-window-title"), (True, False))

    def test_task_rows_follow_preset_and_custom(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:      # no display / Tcl without Tk
            self.skipTest(f"no Tk display: {exc}")
        root.withdraw()
        app = test_panel.PanelApp(root, uri="ws://127.0.0.1:9", plan=None)
        try:
            root.update()
            # default plan is legacy -> rows show all-Cloud, pinned L disabled
            self.assertEqual(app.task_vars["A"].get(), "X")
            self.assertEqual(str(app.task_combos["L"]["state"]), "disabled")
            self.assertEqual(str(app.task_combos["A"]["state"]), "disabled")

            # picking a preset fills the rows and keeps them read-only
            app.form_vars["placement"].set("offload_ab")
            app.on_placement_preset()
            self.assertEqual(app.task_vars["A"].get(), "Y")
            self.assertEqual(app.task_vars["B"].get(), "Y")
            self.assertEqual(app.task_vars["C"].get(), "X")
            self.assertEqual(str(app.task_combos["A"]["state"]), "disabled")
            self.assertIn("1 crossing", app.chain_var.get())
            self.assertIn("stream from X", app.chain_var.get())

            # picking custom unlocks A-E, never L, and rows drive the label
            app.form_vars["placement"].set("custom")
            app._refresh_task_states()
            self.assertEqual(str(app.task_combos["A"]["state"]), "normal")
            self.assertEqual(str(app.task_combos["L"]["state"]), "disabled")
            app.task_vars["E"].set("Y")
            app.on_task_changed()
            self.assertIn("pixels channel", app.chain_var.get())

            # Apply stores the table on the plan and Save serialises it
            plan = app.on_apply()
            self.assertIsNotNone(plan)
            self.assertEqual(plan.placement, "custom")
            self.assertEqual(plan.placement_tasks["E"], "Y")
            self.assertEqual(plan.to_dict()["placement_tasks"]["E"], "Y")

            # editing a row outside custom switches the axis for the user
            app.form_vars["placement"].set("all_cloud")
            app._refresh_task_states()
            app.task_vars["B"].set("Y")
            app.on_task_changed()
            self.assertEqual(app.form_vars["placement"].get(), "custom")
        finally:
            app.on_close()


if __name__ == "__main__":
    unittest.main()
