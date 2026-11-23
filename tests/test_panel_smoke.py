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
    from tools import test_panel
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
            self.assertEqual(len(app.form_vars), 8)
            # the controls follow the phase helper
            app._refresh_buttons("running")
            self.assertEqual(str(app.controls["start"]["state"]), "disabled")
            self.assertEqual(str(app.controls["pause"]["state"]), "normal")
        finally:
            app.on_close()

    def test_focus_window_is_safe(self):
        self.assertIn(test_panel.focus_window("no-such-window-title"), (True, False))


if __name__ == "__main__":
    unittest.main()
