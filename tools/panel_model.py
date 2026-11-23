"""Headless logic behind the WS2.2 Tk control panel.

Kept free of tkinter and websockets so the panel's plan editing, progress
formatting and dashboard-message handling can be unit-tested without a display
or a running Middle Y.  ``tools/test_panel.py`` is the thin Tk/socket shell on
top of this module.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from common.testplan import (
    EVENT_KINDS,
    PlanError,
    TestPlan,
)

DEFAULT_Y_URI = "ws://127.0.0.1:8002"
# Phases in which Y owns the run and the plan must not be edited underneath it.
BUSY_STATES = ("starting", "warmup", "running", "paused")
PLAN_FIELDS = ("name", "warmup_s", "duration_s", "seed", "workload", "mode",
               "video_preset", "input_pattern")
TIMELINE_CHARS = {"delay": "=", "mode": "M", "pattern": "i", "pause": "x"}
CONTROLS = {"pause": "test_pause", "resume": "test_resume", "stop": "test_stop"}
SUMMARY_KEYS = ("e2e", "rtt", "z_fps")


def blank_plan(name="WS2.2 panel run"):
    """A valid starting point for the panel form."""
    return TestPlan(name=name, warmup_s=5.0, duration_s=60.0, seed=12345,
                    workload="light", mode="auto", video_preset="current",
                    input_pattern="strafe", events=[])


# -- plan editing -------------------------------------------------------

def build_plan(fields, events=()):
    """Turn form values (usually strings) into a validated plan."""
    raw = {key: fields[key] for key in PLAN_FIELDS if key in fields}
    raw["events"] = [dict(event) for event in events]
    return TestPlan.from_dict(raw)


def update_plan(plan, fields):
    """Apply changed form values to ``plan``, keeping its events."""
    events = plan.to_dict()["events"]
    raw = plan.to_dict()
    raw.update({key: value for key, value in fields.items() if key in PLAN_FIELDS})
    return build_plan(raw, events)


def plan_text(plan):
    return json.dumps(plan.to_dict(), indent=2) + "\n"


def plan_from_text(text, source="plan"):
    if isinstance(text, str):
        text = text.lstrip("\ufeff")      # tolerate a BOM from Notepad/PowerShell
    try:
        raw = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise PlanError(f"{source}: invalid JSON ({exc})") from None
    return TestPlan.from_dict(raw)


def load_plan(path):
    path = Path(path)
    return plan_from_text(path.read_text(encoding="utf-8"), source=str(path))


def save_plan(path, plan):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan_text(plan), encoding="utf-8")
    return path


def plan_files(directory):
    """Sorted plan JSON files, for the panel's file picker."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"), key=lambda item: item.name)


def add_event(plan, at_s, kind, value=None, hold_s=None):
    """Append one timeline event and return a new validated plan."""
    kind = str(kind or "").strip().lower()
    if kind not in EVENT_KINDS:
        raise PlanError(f"event kind must be one of {', '.join(EVENT_KINDS)}")
    event = {"at_s": at_s, "kind": kind}
    if kind == "delay":
        event["delay_ms"] = 0 if value in (None, "") else value
    elif kind == "mode":
        event["mode"] = value or plan.mode
    elif kind == "pattern":
        event["pattern"] = value or plan.input_pattern
    if hold_s not in (None, ""):
        event["hold_s"] = hold_s
    return build_plan(plan.to_dict(), plan.to_dict()["events"] + [event])


def remove_event(plan, index):
    """Drop the event at ``index`` (sorted order) and return a new plan."""
    events = plan.to_dict()["events"]
    if not 0 <= int(index) < len(events):
        raise PlanError("select an event to remove")
    del events[int(index)]
    return build_plan(plan.to_dict(), events)


def event_rows(plan):
    return [{"index": index, "at_s": f"{event.at_s:g}", "kind": event.kind,
             "label": event.label()}
            for index, event in enumerate(plan.sorted_events())]


def timeline_rows(plan, width=60):
    """One ASCII bar per event kind, scaled to the measurement window."""
    width = max(8, int(width))
    duration = float(plan.duration_s) or 1.0
    segments = plan.segments()
    rows = []
    for kind in EVENT_KINDS:
        cells = [" "] * width
        labels = []
        for segment in segments:
            if segment.kind != kind:
                continue
            start = max(0, min(width, int(round(width * segment.start_s / duration))))
            stop = max(0, min(width, int(round(width * segment.end_s / duration))))
            for cell in range(start, max(start + 1, stop)) if stop > start else ():
                cells[cell] = TIMELINE_CHARS.get(kind, "#")
            labels.append(f"{segment.start_s:g}-{segment.end_s:g}s "
                          f"{_segment_label(kind, segment.value)}")
        rows.append({"kind": kind, "bar": "".join(cells),
                     "labels": " | ".join(labels)})
    return rows


def timeline_legend():
    return "  ".join(f"{TIMELINE_CHARS[kind]}= {kind}" for kind in EVENT_KINDS)


def _segment_label(kind, value):
    if kind == "delay":
        return f"{int(value)} ms"
    if kind == "pause":
        return "paused"
    return str(value)


# -- live state ---------------------------------------------------------

def fmt(value, digits=0):
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def phase(state):
    test = (state or {}).get("test") or {}
    return test.get("state") or "idle"


def progress(state):
    """Progress-bar model for one Y state push."""
    test = (state or {}).get("test") or {}
    current = test.get("state") or "idle"
    duration = _number(test.get("duration_s"))
    elapsed = _number(test.get("elapsed_s"))
    remaining = _number(test.get("remaining_s"))
    fraction = _number(test.get("progress"))
    if current == "warmup":
        label = f"warm-up {fmt(test.get('warmup_left_s'), 1)} s left"
    elif current in ("running", "paused"):
        label = f"{current} {fmt(elapsed, 1)}/{fmt(duration, 1)} s"
    elif test.get("error"):
        label = f"error: {test['error']}"
    elif current == "finished":
        label = f"finished after {fmt(elapsed, 1)} s"
    else:
        label = current
    return {
        "state": current,
        "label": label,
        "progress": max(0.0, min(1.0, fraction)),
        "elapsed_s": elapsed,
        "remaining_s": remaining,
        "elapsed": f"{fmt(elapsed, 1)} s",
        "remaining": f"{fmt(remaining, 1)} s",
        "next": ((test.get("next_event") or {}).get("label")) or "-",
        "report_id": test.get("report_id") or "",
        "error": test.get("error") or "",
    }


def metrics(state):
    """Formatted live metrics (Y state + Z stats) for the panel labels."""
    state = state or {}
    z_stats = state.get("z_stats") or {}
    return {
        "mode": state.get("mode") or "-",
        "linked": "yes" if state.get("linked") else "no",
        "paused": "yes" if state.get("paused") else "no",
        "rtt": fmt(state.get("rtt")),
        "delay": fmt(state.get("delay_ms")),
        "e2e": fmt(state.get("e2e")),
        "rtt_zy": fmt(state.get("rtt_zy")),
        "x_fps": fmt(state.get("x_fps"), 1),
        "y_fps": fmt(state.get("y_fps"), 1),
        "z_fps": fmt(z_stats.get("fps"), 1),
        "x_encode": fmt(state.get("x_encode"), 1),
        "z_decode": fmt(z_stats.get("decode"), 1),
    }


def buttons(current):
    """Which controls make sense in ``current`` (a test phase name)."""
    current = current or "idle"
    busy = current in BUSY_STATES
    return {
        "start": not busy,
        "pause": current in ("warmup", "running"),
        "resume": current == "paused",
        "stop": busy,
        "edit": not busy,
    }


# -- dashboard protocol -------------------------------------------------

def hello_payload():
    return {"cmd": "hello"}


def start_payload(plan):
    return {"cmd": "test_start", "plan": plan.to_dict()}


def preview_payload(plan):
    return {"cmd": "set_plan", "plan": plan.to_dict()}


def control_payload(action):
    if action not in CONTROLS:
        raise ValueError(f"unknown control {action!r}")
    return {"cmd": CONTROLS[action]}


def report_payload(report_id):
    return {"cmd": "get_report", "id": str(report_id)}


def list_payload():
    return {"cmd": "list_reports"}


def parse_message(raw):
    """Classify one dashboard frame; ``None`` for frames the panel ignores.

    Returns ``{"kind": "state"|"hello"|"report"|"reports"|"error",
    "message": {...}}`` and keeps the raw message so the caller can use any
    field it needs.
    """
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    try:
        message = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(message, dict):
        return None
    kind = message.get("t")
    if kind in ("hello", "report", "reports", "error"):
        return {"kind": kind, "message": message}
    if kind is None and ("test" in message or "mode" in message or
                         "rtt" in message):
        return {"kind": "state", "message": message}
    return None


# -- reports ------------------------------------------------------------

def summary_line(summary):
    parts = []
    for key in SUMMARY_KEYS:
        stats = (summary or {}).get(key) or {}
        if stats.get("n"):
            parts.append(f"{key} p50 {fmt(stats.get('p50'), 1)}")
    return ", ".join(parts) or "-"


def report_rows(reports):
    rows = []
    for report in reports or []:
        when = " ".join(part for part in (report.get("date"),
                                          report.get("time")) if part)
        rows.append({"id": report.get("id") or "-",
                     "when": when or "-",
                     "name": report.get("name") or "-",
                     "detail": summary_line(report.get("summary"))})
    return rows


def report_csv(report):
    """CSV text of a report's samples (mirrors common/report.write)."""
    fields = []
    for sample in (report or {}).get("samples", []):
        for key in sample:
            if key not in fields:
                fields.append(key)
    fields = fields or ["t"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore",
                            lineterminator="\n")
    writer.writeheader()
    for sample in (report or {}).get("samples", []):
        writer.writerow(sample)
    return out.getvalue()


# -- End Z window -------------------------------------------------------

def y_host(uri):
    """Host part of a dashboard URI, used as End Z's FYP_Y_IP."""
    text = str(uri or "").strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    host = text.split("/", 1)[0]
    if host.startswith("["):
        return host.split("]", 1)[0].lstrip("[")
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def z_env(base_env, uri):
    env = dict(base_env or {})
    env["FYP_TEST"] = "1"
    env["FYP_Y_IP"] = y_host(uri) or "127.0.0.1"
    env.pop("SDL_VIDEODRIVER", None)      # Z is the only tier needing a display
    return env


def z_command(root, python=None):
    root = Path(root)
    exe = Path(python) if python else root / "venv" / "Scripts" / "python.exe"
    return [str(exe), "-u", "z_client.py"]


