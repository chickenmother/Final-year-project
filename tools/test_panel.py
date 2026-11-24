"""WS2.2 Tk control panel: edit a test plan, drive Y's TestRunner, read reports.

Run it next to Middle Y (dashboard websocket on port 8002):

    .\\venv\\Scripts\\python.exe tools\\test_panel.py
    .\\venv\\Scripts\\python.exe tools\\test_panel.py --y ws://192.168.0.182:8002 ^
        --plan tools\\plans\\ws2_1_smoke.json

The panel never talks to X directly: Y owns the run state machine, the timeline
and the report.  WS2.3 adds X's runtime video/stats/stop commands; until then
the X encoder settings stay fixed by FYP_X_* and only the preset name is
recorded in the plan/report.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.testplan import (  # noqa: E402  (after the sys.path fix)
    INPUT_PATTERNS,
    MODES,
    PLACEMENTS,
    PlanError,
    VIDEO_PRESETS,
    WORKLOADS,
)
from tools import panel_model as pm  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402

PLAN_DIR = ROOT / "tools" / "plans"
Z_CAPTION = "Z - end node"          # pygame window caption set by z_client.py


class YLink(threading.Thread):
    """Background dashboard client: one connection at a time, auto-reconnect.

    Frames are parsed on the socket thread and pushed as ``panel_model``
    dictionaries into a ``queue.Queue`` the Tk thread polls, so no Tk call ever
    happens off the main thread.
    """

    def __init__(self, uri, inbox):
        super().__init__(daemon=True)
        self.uri = uri
        self.inbox = inbox
        self._stop = threading.Event()
        self._loop = asyncio.new_event_loop()
        self._out = None
        self._ws = None
        self._ready = threading.Event()

    def run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())
        self._loop.close()

    async def _main(self):
        self._out = asyncio.Queue()
        self._ready.set()
        while not self._stop.is_set():
            try:
                async with connect(self.uri, max_size=8 << 20,
                                   compression=None) as ws:
                    self._ws = ws
                    self.inbox.put({"kind": "link", "connected": True,
                                    "detail": self.uri})
                    await ws.send(json.dumps(pm.hello_payload()))
                    tasks = {asyncio.create_task(self._read(ws)),
                             asyncio.create_task(self._write(ws))}
                    done, pending = await asyncio.wait(
                        tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
                    for task in done:
                        try:
                            task.result()
                        except (asyncio.CancelledError, Exception):
                            pass
            except Exception as exc:
                self.inbox.put({"kind": "link", "connected": False,
                                "detail": f"{type(exc).__name__}: {exc}"})
            finally:
                self._ws = None
            if self._stop.is_set():
                break
            await asyncio.sleep(2.0)
        self.inbox.put({"kind": "link", "connected": False, "detail": "closed"})

    async def _read(self, ws):
        async for raw in ws:
            item = pm.parse_message(raw)
            if item is not None:
                self.inbox.put(item)

    async def _write(self, ws):
        while not self._stop.is_set():
            payload = await self._out.get()
            if payload is None:
                return
            await ws.send(json.dumps(payload))

    def send(self, payload):
        if not self._ready.wait(1.0) or self._out is None:
            return False
        self._loop.call_soon_threadsafe(self._out.put_nowait, dict(payload))
        return True

    def close(self):
        self._stop.set()
        if self._out is not None:
            try:
                self._loop.call_soon_threadsafe(self._out.put_nowait, None)
            except RuntimeError:
                pass
        ws = self._ws
        if ws is not None:
            try:
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(ws.close()))
            except RuntimeError:
                pass


class PanelApp:
    """Tk shell around ``tools.panel_model`` and one :class:`YLink`."""

    POLL_MS = 120

    def __init__(self, root, uri=pm.DEFAULT_Y_URI, plan=None):
        self.root = root
        self.inbox = queue.Queue()
        self.link = None
        self.state = {}
        self.reports = []
        self.report_cache = {}
        self.plan = plan or pm.blank_plan()
        self.z_process = None
        self.pending_csv = None
        self._last_state = {}
        self.uri_var = tk.StringVar(value=uri or pm.DEFAULT_Y_URI)
        self.link_var = tk.StringVar(value="disconnected")
        self.status_var = tk.StringVar(value="ready")
        self.progress_var = tk.StringVar(value="idle")
        self.next_var = tk.StringVar(value="-")
        self.report_var = tk.StringVar(value="-")
        self.plan_file_var = tk.StringVar(value="")
        self.form_vars = {}
        self.event_vars = {}
        self.metric_vars = {}
        self.controls = {}
        self._build()
        self._load_plan_into_form(self.plan)
        self._refresh_plan_views()
        self._refresh_buttons("idle")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(self.POLL_MS, self._poll)
        self.on_connect()

    # -- layout ------------------------------------------------------

    def _build(self):
        self.root.title("FYP test control panel (WS2.2)")
        self.root.geometry("1200x860")
        self.root.minsize(980, 700)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        self._build_topbar()
        body = ttk.Frame(self.root, padding=(8, 0, 8, 6))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)
        self._build_plan_frame(left)
        self._build_tasks_frame(left)
        self._build_events_frame(left)
        self._build_timeline_frame(left)
        self._build_run_frame(right)
        self._build_metrics_frame(right)
        self._build_reports_frame(right)
        status = ttk.Frame(self.root, padding=(8, 2, 8, 6))
        status.grid(row=2, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var,
                  anchor="w").grid(row=0, column=0, sticky="ew")
        ttk.Label(status, textvariable=self.report_var,
                  anchor="e").grid(row=0, column=1, sticky="e")

    def _build_topbar(self):
        bar = ttk.Frame(self.root, padding=8)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        ttk.Label(bar, text="Middle Y:").grid(row=0, column=0, sticky="w")
        ttk.Entry(bar, textvariable=self.uri_var).grid(
            row=0, column=1, sticky="ew", padx=(4, 8))
        self.controls["connect"] = ttk.Button(bar, text="Connect",
                                              command=self.on_connect)
        self.controls["connect"].grid(row=0, column=2, padx=2)
        ttk.Button(bar, text="Disconnect",
                   command=self.on_disconnect).grid(row=0, column=3, padx=2)
        ttk.Label(bar, textvariable=self.link_var, width=30, anchor="e").grid(
            row=0, column=4, padx=(8, 4))
        ttk.Button(bar, text="Browser dashboard",
                   command=self.on_browser).grid(row=0, column=5, padx=(4, 0))

    def _build_plan_frame(self, parent):
        frame = ttk.LabelFrame(parent, text="Plan", padding=6)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        def field(row, column, label, key, values=None):
            ttk.Label(frame, text=label).grid(row=row, column=column,
                                              sticky="w", padx=(0, 4))
            var = tk.StringVar()
            self.form_vars[key] = var
            if values:
                widget = ttk.Combobox(frame, textvariable=var, values=values,
                                      width=12, state="readonly")
            else:
                widget = ttk.Entry(frame, textvariable=var, width=12)
            widget.grid(row=row, column=column + 1, sticky="ew",
                        padx=(0, 10), pady=2)
            return widget

        ttk.Label(frame, text="Name").grid(row=0, column=0, sticky="w")
        name_var = tk.StringVar()
        self.form_vars["name"] = name_var
        ttk.Entry(frame, textvariable=name_var).grid(
            row=0, column=1, columnspan=3, sticky="ew", padx=(0, 10), pady=2)
        field(1, 0, "Warm-up s", "warmup_s")
        field(1, 2, "Duration s", "duration_s")
        field(2, 0, "Seed", "seed")
        field(2, 2, "Workload", "workload", WORKLOADS)
        field(3, 0, "Mode", "mode", MODES)
        field(3, 2, "Video preset", "video_preset", VIDEO_PRESETS)
        field(4, 0, "Input", "input_pattern", INPUT_PATTERNS)
        self.placement_combo = field(4, 2, "Placement", "placement", PLACEMENTS)
        self.placement_combo.bind("<<ComboboxSelected>>",
                                  self.on_placement_preset)

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        self.controls["apply"] = ttk.Button(buttons, text="Apply",
                                            command=self.on_apply)
        self.controls["apply"].pack(side="left")
        ttk.Button(buttons, text="Load\u2026",
                   command=self.on_load).pack(side="left", padx=4)
        ttk.Button(buttons, text="Save as\u2026",
                   command=self.on_save).pack(side="left")
        self.controls["preview"] = ttk.Button(buttons, text="Preview",
                                              command=self.on_preview)
        self.controls["preview"].pack(side="left", padx=4)
        self.controls["apply_video"] = ttk.Button(
            buttons, text="Apply video to X", command=self.on_apply_video)
        self.controls["apply_video"].pack(side="left")
        self.controls["apply_placement"] = ttk.Button(
            buttons, text="Apply placement", command=self.on_apply_placement)
        self.controls["apply_placement"].pack(side="left", padx=4)
        files = [path.name for path in pm.plan_files(PLAN_DIR)]
        self.plan_picker = ttk.Combobox(buttons, textvariable=self.plan_file_var,
                                        values=files, width=22,
                                        state="readonly")
        self.plan_picker.pack(side="right")
        self.plan_picker.bind("<<ComboboxSelected>>", self.on_pick_plan)
        ttk.Label(buttons, text="bundled:").pack(side="right", padx=(0, 4))

    def _build_tasks_frame(self, parent):
        """WS3.5: per-stage placement rows (A-E + L) with a cost label."""
        frame = ttk.LabelFrame(parent, text="Task placement (X / Y)", padding=6)
        frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        for column in range(4):
            frame.columnconfigure(column, weight=1)
        self.task_vars = {}
        self.task_combos = {}
        for index, task in enumerate(pm.TASK_ROWS):
            row, column = divmod(index, 3)
            title = pm.stage_title(task)
            ttk.Label(frame, text=title).grid(row=row, column=column * 2,
                                              sticky="w", padx=(0, 4), pady=1)
            var = tk.StringVar(value="X")
            combo = ttk.Combobox(frame, textvariable=var, width=5,
                                 values=pm.TIER_CHOICES, state="normal")
            if task == "L":
                combo.configure(state="disabled")   # pinned to X by design
            combo.grid(row=row, column=column * 2 + 1, sticky="w",
                       padx=(0, 10), pady=1)
            combo.bind("<<ComboboxSelected>>", self.on_task_changed)
            self.task_vars[task] = var
            self.task_combos[task] = combo
        ttk.Label(frame, text="U → Z (fixed)", foreground="#666").grid(
            row=2, column=0, columnspan=2, sticky="w")
        self.chain_var = tk.StringVar(value="0 crossing(s) · stream from X")
        ttk.Label(frame, textvariable=self.chain_var,
                  foreground="#375").grid(row=2, column=2, columnspan=4,
                                          sticky="w")

    def _tasks_from_form(self):
        return {task: var.get().strip().upper() or "X"
                for task, var in self.task_vars.items()}

    def _set_task_vars(self, tasks):
        for task, var in self.task_vars.items():
            if task in tasks:
                var.set(str(tasks[task]).upper())
        self._update_chain_label()

    def _update_chain_label(self):
        tasks = self._tasks_from_form()
        self.chain_var.set(pm.chain_summary(tasks))

    def _custom_selected(self):
        return self.form_vars["placement"].get().strip().lower() == "custom"

    def on_task_changed(self, _event=None):
        self._update_chain_label()
        if not self._custom_selected():
            # touching a row means the user wants the custom table
            self.form_vars["placement"].set("custom")
        self._refresh_task_states()

    def on_placement_preset(self, _event=None):
        preset = self.form_vars["placement"].get().strip().lower()
        if preset != "custom":
            self._set_task_vars(pm.preset_tasks(preset))
        self._refresh_task_states()

    def _refresh_task_states(self):
        editable = self._custom_selected() and pm.buttons(pm.phase(self.state))["edit"]
        for task, combo in self.task_combos.items():
            if task == "L":
                combo.configure(state="disabled")   # pinned to X
            else:
                combo.configure(state="normal" if editable else "disabled")

    def _build_events_frame(self, parent):
        frame = ttk.LabelFrame(parent, text="Timeline events", padding=6)
        frame.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.event_tree = ttk.Treeview(frame, columns=("at", "kind", "label"),
                                       show="headings", height=6,
                                       selectmode="browse")
        for column, title, width in (("at", "at_s", 70), ("kind", "kind", 90),
                                     ("label", "value", 320)):
            self.event_tree.heading(column, text=title)
            self.event_tree.column(column, width=width, anchor="w")
        self.event_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical",
                               command=self.event_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.event_tree.configure(yscrollcommand=scroll.set)

        row = ttk.Frame(frame)
        row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.event_vars["at_s"] = tk.StringVar()
        self.event_vars["kind"] = tk.StringVar(value="delay")
        self.event_vars["value"] = tk.StringVar()
        self.event_vars["hold_s"] = tk.StringVar()
        ttk.Label(row, text="at s").pack(side="left")
        ttk.Entry(row, textvariable=self.event_vars["at_s"], width=6).pack(
            side="left", padx=(4, 8))
        ttk.Combobox(row, textvariable=self.event_vars["kind"],
                     values=("delay", "mode", "pattern", "pause"), width=8,
                     state="readonly").pack(side="left")
        ttk.Label(row, text="value").pack(side="left", padx=(8, 0))
        ttk.Entry(row, textvariable=self.event_vars["value"], width=10).pack(
            side="left", padx=(4, 8))
        ttk.Label(row, text="hold s").pack(side="left")
        ttk.Entry(row, textvariable=self.event_vars["hold_s"], width=6).pack(
            side="left", padx=(4, 8))
        ttk.Button(row, text="Add", command=self.on_add_event).pack(side="left")
        self.controls["remove_event"] = ttk.Button(row, text="Remove",
                                                   command=self.on_remove_event)
        self.controls["remove_event"].pack(side="left", padx=4)

    def _build_timeline_frame(self, parent):
        frame = ttk.LabelFrame(parent, text="Timeline", padding=6)
        frame.grid(row=2, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        self.timeline = tk.Text(frame, height=7, wrap="none",
                                font=("Consolas", 9))
        self.timeline.grid(row=0, column=0, sticky="ew")
        ttk.Label(frame, text=pm.timeline_legend(), foreground="#666").grid(
            row=1, column=0, sticky="w", pady=(2, 0))

    def _build_run_frame(self, parent):
        frame = ttk.LabelFrame(parent, text="Run", padding=6)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, textvariable=self.progress_var,
                  font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        self.bar = ttk.Progressbar(frame, maximum=1.0)
        self.bar.grid(row=1, column=0, sticky="ew", pady=4)
        info = ttk.Frame(frame)
        info.grid(row=2, column=0, sticky="ew")
        ttk.Label(info, text="next event:").pack(side="left")
        ttk.Label(info, textvariable=self.next_var).pack(side="left",
                                                         padx=(4, 0))
        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        for key, text, command in (("start", "Start", self.on_start),
                                   ("pause", "Pause", self.on_pause),
                                   ("resume", "Resume", self.on_resume),
                                   ("stop", "Terminate", self.on_stop)):
            self.controls[key] = ttk.Button(buttons, text=text, command=command)
            self.controls[key].pack(side="left", padx=(0, 4))

    def _build_metrics_frame(self, parent):
        frame = ttk.LabelFrame(parent, text="Live metrics", padding=6)
        frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        titles = (("mode", "active tier"), ("linked", "X linked"),
                  ("paused", "paused"), ("rtt", "RTT X<->Y ms"),
                  ("delay", "injected ms"), ("e2e", "input->display ms"),
                  ("rtt_zy", "RTT Z<->Y ms"), ("x_fps", "X fps"),
                  ("y_fps", "Y fps"), ("z_fps", "Z fps"),
                  ("x_encode", "X encode p50 ms"), ("x_encode_p95", "p95 ms"),
                  ("x_kf", "X keyframes/s"), ("x_kb", "frame KB"),
                  ("x_video", "X video"), ("placement", "placement"),
                  ("chain", "chain (WS3.5)"),
                  ("task_sim", "sim p50 X / Y"), ("task_hit", "hit p50 X / Y"),
                  ("task_render", "render p50 X / Y"),
                  ("task_encode", "encode p50 X / Y"),
                  ("offload", "offload (A/B state)"), ("z_decode", "Z decode ms"))
        for index, (key, title) in enumerate(titles):
            row, column = divmod(index, 2)
            ttk.Label(frame, text=title).grid(row=row, column=column * 2,
                                              sticky="w", padx=(0, 4), pady=1)
            var = tk.StringVar(value="-")
            self.metric_vars[key] = var
            ttk.Label(frame, textvariable=var, width=16, anchor="w",
                      font=("Consolas", 9)).grid(row=row, column=column * 2 + 1,
                                                 sticky="w", padx=(0, 14),
                                                 pady=1)
        ttk.Label(frame, text="intra-refresh needs Z started with "
                              "FYP_X_INTRA_REFRESH=1",
                  foreground="#666").grid(row=11, column=0, columnspan=4,
                                          sticky="w", pady=(4, 0))

    def _build_reports_frame(self, parent):
        frame = ttk.LabelFrame(parent, text="Reports", padding=6)
        frame.grid(row=2, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.report_tree = ttk.Treeview(
            frame, columns=("id", "when", "name", "detail"), show="headings",
            height=7, selectmode="browse")
        for column, title, width in (("id", "id", 130), ("when", "when", 145),
                                     ("name", "plan", 170),
                                     ("detail", "summary", 260)):
            self.report_tree.heading(column, text=title)
            self.report_tree.column(column, width=width, anchor="w")
        self.report_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical",
                               command=self.report_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        hscroll = ttk.Scrollbar(frame, orient="horizontal",
                                command=self.report_tree.xview)
        hscroll.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.report_tree.configure(yscrollcommand=scroll.set,
                                   xscrollcommand=hscroll.set)
        row = ttk.Frame(frame)
        row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(row, text="Refresh", command=self.on_refresh_reports).pack(
            side="left")
        ttk.Button(row, text="Open JSON", command=self.on_open_report).pack(
            side="left", padx=4)
        ttk.Button(row, text="Export CSV",
                   command=self.on_export_csv).pack(side="left")
        ttk.Separator(row, orient="vertical").pack(side="left", fill="y",
                                                   padx=8)
        self.controls["launch_z"] = ttk.Button(row, text="Launch Z (test)",
                                              command=self.on_launch_z)
        self.controls["launch_z"].pack(side="left")
        ttk.Button(row, text="Focus Z", command=self.on_focus_z).pack(
            side="left", padx=4)

    # -- plan form ---------------------------------------------------

    def _load_plan_into_form(self, plan):
        for key in pm.PLAN_FIELDS:
            value = getattr(plan, key)
            text = f"{float(value):g}" if key in ("warmup_s",
                                                  "duration_s") else str(value)
            self.form_vars[key].set(text)
        self._set_task_vars(pm.tasks_for(plan))
        self._refresh_task_states()

    def _form_fields(self):
        return {key: var.get() for key, var in self.form_vars.items()}

    def _plan_error(self, exc):
        self.status_var.set(f"plan error: {exc}")
        messagebox.showerror("Plan error", str(exc), parent=self.root)
        return None

    def on_apply(self):
        """Validate the form and make it the active plan (``None`` on error)."""
        try:
            plan = pm.build_plan(self._form_fields(),
                                 self.plan.to_dict()["events"],
                                 self._tasks_from_form())
        except PlanError as exc:
            return self._plan_error(exc)
        self.plan = plan
        self._load_plan_into_form(plan)
        self._refresh_plan_views()
        self.status_var.set(f"plan applied: {plan.name} "
                            f"[{pm.chain_summary(self._tasks_from_form())}]")
        return plan

    def on_pick_plan(self, _event=None):
        name = self.plan_file_var.get()
        if name:
            self._open_plan(PLAN_DIR / name)

    def on_load(self):
        path = filedialog.askopenfilename(
            parent=self.root, initialdir=str(PLAN_DIR), title="Open test plan",
            filetypes=[("plan JSON", "*.json"), ("all files", "*.*")])
        if path:
            self._open_plan(Path(path))

    def _open_plan(self, path):
        try:
            plan = pm.load_plan(path)
        except (PlanError, OSError) as exc:
            return self._plan_error(exc)
        self.plan = plan
        self._load_plan_into_form(plan)
        self._refresh_plan_views()
        self.plan_file_var.set(Path(path).name)
        self.status_var.set(f"loaded {Path(path).name}")

    def on_save(self):
        plan = self.on_apply()
        if plan is None:
            return None
        path = filedialog.asksaveasfilename(
            parent=self.root, initialdir=str(PLAN_DIR), defaultextension=".json",
            initialfile=f"{plan.name.replace(' ', '_')}.json",
            title="Save test plan", filetypes=[("plan JSON", "*.json")])
        if not path:
            return None
        try:
            pm.save_plan(path, plan)
        except OSError as exc:
            return self._plan_error(exc)
        self._refresh_picker()
        self.plan_file_var.set(Path(path).name)
        self.status_var.set(f"saved {Path(path).name}")
        return plan

    def _refresh_picker(self):
        self.plan_picker.configure(
            values=[path.name for path in pm.plan_files(PLAN_DIR)])

    def on_preview(self):
        plan = self.on_apply()
        if plan is not None:
            self._send(pm.preview_payload(plan), "preview plan")

    def on_apply_video(self):
        """Apply the selected preset to Cloud X without starting a run (WS2.3)."""
        preset = self.form_vars["video_preset"].get()
        payload = pm.x_video_payload(preset)
        if payload is None:
            self.status_var.set("video preset 'current': X keeps its "
                                "startup encoder")
            return
        self._send(payload, f"apply video {preset} to X")

    def on_apply_placement(self):
        """Switch Y's router placement without starting a run (WS3.1/WS3.5)."""
        pattern = self.form_vars["placement"].get().strip().lower()
        target = (self._tasks_from_form() if pattern == "custom" else pattern)
        try:
            payload = pm.placement_payload(target)
        except PlanError as exc:
            return self._plan_error(exc)
        self._send(payload, f"placement {pattern}")

    def _refresh_plan_views(self):
        self.event_tree.delete(*self.event_tree.get_children())
        for row in pm.event_rows(self.plan):
            self.event_tree.insert("", "end", iid=str(row["index"]),
                                   values=(row["at_s"], row["kind"],
                                           row["label"]))
        self.timeline.configure(state="normal")
        self.timeline.delete("1.0", "end")
        for row in pm.timeline_rows(self.plan, width=40):
            self.timeline.insert(
                "end", f"{row['kind']:<8}{row['bar']}  {row['labels']}\n")
        self.timeline.configure(state="disabled")

    def on_add_event(self):
        plan = self.on_apply()
        if plan is None:
            return
        try:
            plan = pm.add_event(plan, self.event_vars["at_s"].get(),
                                self.event_vars["kind"].get(),
                                self.event_vars["value"].get() or None,
                                self.event_vars["hold_s"].get() or None)
        except PlanError as exc:
            return self._plan_error(exc)
        self.plan = plan
        self._refresh_plan_views()
        self.status_var.set(f"{len(plan.events)} event(s) in the plan")

    def on_remove_event(self):
        selection = self.event_tree.selection()
        if not selection:
            self.status_var.set("select an event to remove")
            return
        try:
            self.plan = pm.remove_event(self.plan, int(selection[0]))
        except PlanError as exc:
            return self._plan_error(exc)
        self._refresh_plan_views()
        self.status_var.set(f"{len(self.plan.events)} event(s) in the plan")

    def _refresh_buttons(self, current):
        state = pm.buttons(current)
        for key in ("start", "pause", "resume", "stop"):
            widget = self.controls.get(key)
            if widget is not None:
                widget.configure(state="normal" if state[key] else "disabled")
        for key in ("apply", "preview", "remove_event", "launch_z"):
            widget = self.controls.get(key)
            if widget is not None:
                widget.configure(state="normal" if state["edit"] else "disabled")
        if hasattr(self, "task_combos"):
            self._refresh_task_states()

    # -- Y link and run controls -------------------------------------

    def on_connect(self):
        uri = self.uri_var.get().strip() or pm.DEFAULT_Y_URI
        self.on_disconnect()
        self.link_var.set(f"connecting {uri}")
        self.link = YLink(uri, self.inbox)
        self.link.start()
        self.status_var.set(f"connecting to {uri}")

    def on_disconnect(self):
        link, self.link = self.link, None
        if link is not None:
            link.close()
        self.link_var.set("disconnected")

    def _send(self, payload, what):
        if self.link is None or not self.link.send(payload):
            self.status_var.set(f"{what}: not connected to Y")
            return False
        self.status_var.set(f"{what} sent to Y")
        return True

    def on_start(self):
        plan = self.on_apply()
        if plan is not None:
            self._send(pm.start_payload(plan), f"start {plan.name}")

    def on_pause(self):
        self._send(pm.control_payload("pause"), "pause")

    def on_resume(self):
        self._send(pm.control_payload("resume"), "resume")

    def on_stop(self):
        self._send(pm.control_payload("stop"), "terminate")

    def on_browser(self):
        page = ROOT / "web" / "dashboard.html"
        host = pm.y_host(self.uri_var.get()) or "127.0.0.1"
        if not page.is_file():
            self.status_var.set(f"missing {page}")
            return
        webbrowser.open(f"{page.as_uri()}?ip={host}")
        self.status_var.set(f"opened browser dashboard for {host}")

    # -- live state --------------------------------------------------

    def _poll(self):
        try:
            while True:
                self._handle(self.inbox.get_nowait())
        except queue.Empty:
            pass
        self.root.after(self.POLL_MS, self._poll)

    def _handle(self, item):
        kind = item.get("kind")
        message = item.get("message") or item
        if kind == "link":
            connected = bool(item.get("connected"))
            detail = str(item.get("detail") or "")[:48]
            self.link_var.set(("connected  " if connected else "offline  ") +
                              detail)
            if not connected:
                self._refresh_buttons("idle")
        elif kind == "state":
            self.state = message
            self._apply_state()
        elif kind == "hello":
            self.reports = message.get("reports") or []
            self._refresh_reports()
            self.status_var.set("connected to Y (panel hello accepted)")
        elif kind == "reports":
            self.reports = message.get("reports") or []
            self._refresh_reports()
            self.status_var.set(f"{len(self.reports)} report(s) on Y")
        elif kind == "error":
            self.status_var.set(
                f"Y error ({message.get('command')}): {message.get('message')}")
        elif kind == "report":
            report = message.get("report") or {}
            report_id = str(report.get("id") or "")
            self.report_cache[report_id] = report
            if self.pending_csv == report_id:
                self.pending_csv = None
                self._save_csv(report)
            else:
                self._show_report(report)

    def _apply_state(self):
        view = pm.progress(self.state)
        self.progress_var.set(view["label"])
        self.bar.configure(value=view["progress"])
        self.next_var.set(view["next"])
        if view["report_id"]:
            self.report_var.set(f"report {view['report_id']}")
        values = pm.metrics(self.state)
        for key, var in self.metric_vars.items():
            var.set(values.get(key, "-"))
        previous = pm.phase(self._last_state)
        self._refresh_buttons(view["state"])
        if view["state"] == "finished" and previous != "finished":
            self.on_refresh_reports()
        self._last_state = self.state

    # -- reports -----------------------------------------------------

    def on_refresh_reports(self):
        if self.link is not None:
            self._send(pm.list_payload(), "list reports")

    def _selected_report_id(self):
        selection = self.report_tree.selection()
        return selection[0] if selection else ""

    def on_open_report(self):
        report_id = self._selected_report_id()
        if not report_id:
            self.status_var.set("select a report first")
            return
        cached = self.report_cache.get(report_id)
        if cached is not None:
            self._show_report(cached)
        else:
            self._send(pm.report_payload(report_id), f"fetch report {report_id}")

    def on_export_csv(self):
        report_id = self._selected_report_id()
        if not report_id:
            self.status_var.set("select a report first")
            return
        cached = self.report_cache.get(report_id)
        if cached is not None:
            self._save_csv(cached)
        else:
            self.pending_csv = report_id
            self._send(pm.report_payload(report_id), f"fetch report {report_id}")

    def _save_csv(self, report):
        path = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".csv",
            initialfile=f"{report.get('id', 'report')}.csv",
            title="Export report samples",
            filetypes=[("CSV", "*.csv"), ("all files", "*.*")])
        if not path:
            return None
        try:
            Path(path).write_text(pm.report_csv(report), encoding="utf-8")
        except OSError as exc:
            self.status_var.set(f"CSV export failed: {exc}")
            return None
        self.status_var.set(f"CSV saved: {path}")
        return path

    def _show_report(self, report):
        window = tk.Toplevel(self.root)
        window.title(f"Report {report.get('id', '?')}")
        window.geometry("820x600")
        bar = ttk.Frame(window, padding=(6, 6))
        bar.pack(side="bottom", fill="x")
        ttk.Button(bar, text="Export CSV\u2026",
                   command=lambda: self._save_csv(report)).pack(side="left")
        ttk.Button(bar, text="Close", command=window.destroy).pack(side="right")
        text = tk.Text(window, wrap="none", font=("Consolas", 9))
        text.pack(side="top", fill="both", expand=True)
        text.insert("1.0", json.dumps(report, indent=2))
        text.configure(state="disabled")
        self.status_var.set(f"report {report.get('id', '?')} loaded")

    def _refresh_reports(self):
        self.report_tree.delete(*self.report_tree.get_children())
        for row in pm.report_rows(self.reports):
            iid = row["id"]
            if self.report_tree.exists(iid):
                continue
            self.report_tree.insert("", "end", iid=iid,
                                    values=(row["id"], row["when"],
                                            row["name"], row["detail"]))

    # -- End Z -------------------------------------------------------

    def on_launch_z(self):
        if self.z_process is not None and self.z_process.poll() is None:
            return self.on_focus_z()
        command = pm.z_command(ROOT)
        if not Path(command[0]).is_file():
            messagebox.showerror("Launch Z",
                                 f"python not found: {command[0]}",
                                 parent=self.root)
            return
        env = pm.z_env(os.environ, self.uri_var.get())
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        try:
            self.z_process = subprocess.Popen(command, cwd=str(ROOT), env=env,
                                              creationflags=flags)
        except OSError as exc:
            messagebox.showerror("Launch Z", str(exc), parent=self.root)
            return
        self.status_var.set("End Z started in test mode (pid "
                            f"{self.z_process.pid}, FYP_TEST=1)")

    def on_focus_z(self):
        if focus_window(Z_CAPTION):
            self.status_var.set("End Z window focused")
        else:
            self.status_var.set("End Z window not found (looked for "
                                f"'{Z_CAPTION}')")

    # -- shutdown ----------------------------------------------------

    def on_close(self):
        self.on_disconnect()
        self.root.destroy()


def focus_window(fragment):
    """Bring the first visible window whose title contains ``fragment`` up."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd, _param):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                if fragment.lower() in buffer.value.lower():
                    found.append(hwnd)
                    return False
            return True

        user32.EnumWindows(callback, 0)
        if not found:
            return False
        user32.ShowWindow(found[0], 9)          # SW_RESTORE
        user32.SetForegroundWindow(found[0])
        return True
    except Exception:
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--y", default=pm.DEFAULT_Y_URI,
                        help="Middle Y dashboard websocket (default: %(default)s)")
    parser.add_argument("--plan", default=None,
                        help="plan JSON to open on start (default: built-in)")
    args = parser.parse_args(argv)
    plan = None
    if args.plan:
        try:
            plan = pm.load_plan(args.plan)
        except (PlanError, OSError) as exc:
            print(f"cannot open {args.plan}: {exc}")
            return 2
    root = tk.Tk()
    PanelApp(root, uri=args.y, plan=plan)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())







