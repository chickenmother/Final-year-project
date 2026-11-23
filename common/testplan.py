"""Test-plan model shared by the Y test runner and the control panel.

A plan is deliberately small and JSON-friendly: the panel edits it, Y validates
it, applies it to the running match, and the report embeds it so a capture can
be reproduced later.

Timeline values are relative to the start of the measurement window (after the
warm-up).  Events do not have to be written in order; validation sorts them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

WORKLOADS = ("light", "medium", "heavy")
MODES = ("auto", "cloud", "edge")
INPUT_PATTERNS = ("idle", "strafe", "circle", "figure8", "shoot")
EVENT_KINDS = ("delay", "mode", "pause", "pattern")
VIDEO_PRESETS = ("current", "A0", "A1", "A2", "intra")

MAX_DELAY_MS = 400
MAX_DURATION_S = 600.0
MAX_WARMUP_S = 60.0
MAX_HOLD_S = 600.0

MODE_OVERRIDE = {"auto": None, "cloud": "X", "edge": "Y"}

# Runtime X switching lands in WS2.3; the values are still recorded in the
# plan/report so a capture identifies which preset was intended.
VIDEO_SETTINGS = {
    "A0": {"gop": 30, "size": (1280, 720), "bitrate": 4_000_000,
           "intra_refresh": False},
    "A1": {"gop": 120, "size": (1280, 720), "bitrate": 4_000_000,
           "intra_refresh": False},
    "A2": {"gop": 120, "size": (960, 540), "bitrate": 4_000_000,
           "intra_refresh": False},
    "intra": {"gop": 120, "size": (1280, 720), "bitrate": 4_000_000,
              "intra_refresh": True},
}

SUMMARY_KEYS = ("rtt", "delay", "e2e", "rtt_zy", "x_fps", "y_fps", "z_fps",
                "x_encode", "x_encode_p95", "x_kf", "z_decode")

_PRESET_NAMES = {preset.lower(): preset for preset in VIDEO_PRESETS}


def video_payload(preset):
    """Cloud X runtime ``video`` command for a preset, or ``None``.

    ``None`` means "leave X alone": ``current`` keeps whatever FYP_X_* values
    X started with.  WS2.3 sends this to X; WS2.1/2.2 only recorded the name.
    """
    canonical = _PRESET_NAMES.get(str(preset or "").strip().lower())
    settings = VIDEO_SETTINGS.get(canonical)
    if settings is None:
        return None
    return {
        "t": "video",
        "gop": int(settings["gop"]),
        "size": [int(settings["size"][0]), int(settings["size"][1])],
        "bitrate": int(settings["bitrate"]),
        "intra_refresh": bool(settings["intra_refresh"]),
    }



class PlanError(ValueError):
    """Invalid plan; the message is meant for the control panel."""


def _num(raw, name, default=None):
    try:
        value = float(default if raw is None else raw)
    except (TypeError, ValueError):
        raise PlanError(f"{name} must be a number") from None
    if not math.isfinite(value):
        raise PlanError(f"{name} must be finite")
    return value


def _choice(raw, name, choices, default):
    value = str(raw if raw is not None else default).strip().lower()
    canonical = {str(choice).lower(): choice for choice in choices}
    if value not in canonical:
        raise PlanError(f"{name} must be one of {', '.join(choices)}")
    return canonical[value]


@dataclass
class Event:
    at_s: float
    kind: str
    delay_ms: int = 0
    mode: str = ""
    pattern: str = ""
    hold_s: float | None = None

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict):
            raise PlanError("each event must be an object")
        kind = _choice(raw.get("kind"), "event kind", EVENT_KINDS, "")
        if raw.get("at_s") is None:
            raise PlanError("event at_s is required")
        at_s = _num(raw.get("at_s"), "event at_s")
        hold = raw.get("hold_s")
        hold_s = None if hold is None else _num(hold, "event hold_s")
        ev = cls(at_s=at_s, kind=kind, hold_s=hold_s)
        if kind == "delay":
            try:
                ev.delay_ms = int(raw.get("delay_ms", 0))
            except (TypeError, ValueError):
                raise PlanError("delay_ms must be an integer") from None
        elif kind == "mode":
            ev.mode = _choice(raw.get("mode"), "event mode", MODES, "auto")
        elif kind == "pattern":
            ev.pattern = _choice(raw.get("pattern"), "event pattern",
                                 INPUT_PATTERNS, "idle")
        return ev

    def to_dict(self):
        out = {"at_s": round(float(self.at_s), 2), "kind": self.kind}
        if self.kind == "delay":
            out["delay_ms"] = int(self.delay_ms)
        elif self.kind == "mode":
            out["mode"] = self.mode
        elif self.kind == "pattern":
            out["pattern"] = self.pattern
        if self.hold_s is not None:
            out["hold_s"] = round(float(self.hold_s), 2)
        return out

    def value(self):
        if self.kind == "delay":
            return self.delay_ms
        if self.kind == "mode":
            return self.mode
        if self.kind == "pattern":
            return self.pattern
        return "pause"

    def label(self):
        if self.kind == "delay":
            return f"delay {self.delay_ms} ms"
        if self.kind == "mode":
            return f"mode {self.mode}"
        if self.kind == "pattern":
            return f"input {self.pattern}"
        return f"pause {self.hold_s or 0:g} s"


@dataclass
class Segment:
    """Display/runner-friendly part of the timeline."""

    kind: str
    start_s: float
    end_s: float
    value: object
    event_index: int = -1


@dataclass
class TestPlan:
    name: str = "untitled"
    warmup_s: float = 5.0
    duration_s: float = 60.0
    seed: int = 12345
    workload: str = "light"
    mode: str = "auto"
    video_preset: str = "current"
    input_pattern: str = "strafe"
    events: list[Event] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict):
            raise PlanError("plan must be a JSON object")
        name = str(raw.get("name") or "untitled").strip()[:80] or "untitled"
        try:
            seed = int(raw.get("seed", 12345))
        except (TypeError, ValueError):
            raise PlanError("seed must be an integer") from None
        events = [Event.from_dict(e) for e in (raw.get("events") or [])]
        plan = cls(
            name=name,
            warmup_s=_num(raw.get("warmup_s"), "warmup_s", 5.0),
            duration_s=_num(raw.get("duration_s"), "duration_s", 60.0),
            seed=seed,
            workload=_choice(raw.get("workload"), "workload", WORKLOADS, "light"),
            mode=_choice(raw.get("mode"), "mode", MODES, "auto"),
            video_preset=_choice(raw.get("video_preset"), "video_preset",
                                 VIDEO_PRESETS, "current"),
            input_pattern=_choice(raw.get("input_pattern"), "input_pattern",
                                  INPUT_PATTERNS, "strafe"),
            events=events,
        )
        plan.validate()
        return plan

    def to_dict(self):
        return {
            "name": self.name,
            "warmup_s": round(float(self.warmup_s), 2),
            "duration_s": round(float(self.duration_s), 2),
            "seed": int(self.seed),
            "workload": self.workload,
            "mode": self.mode,
            "video_preset": self.video_preset,
            "input_pattern": self.input_pattern,
            "events": [e.to_dict() for e in self.sorted_events()],
        }

    def validate(self):
        if not self.name:
            raise PlanError("plan name must not be empty")
        if not 0.0 <= self.warmup_s <= MAX_WARMUP_S:
            raise PlanError(f"warmup_s must be 0..{MAX_WARMUP_S:g}")
        if not 0.1 <= self.duration_s <= MAX_DURATION_S:
            raise PlanError(f"duration_s must be 0.1..{MAX_DURATION_S:g}")
        if self.workload not in WORKLOADS:
            raise PlanError("workload is invalid")
        if self.mode not in MODES:
            raise PlanError("mode is invalid")
        if self.video_preset not in VIDEO_PRESETS:
            raise PlanError("video_preset is invalid")
        if self.input_pattern not in INPUT_PATTERNS:
            raise PlanError("input_pattern is invalid")
        for ev in self.events:
            if not 0.0 <= ev.at_s <= self.duration_s:
                raise PlanError(
                    f"event at {ev.at_s:g}s is outside the measurement window")
            if ev.hold_s is not None and not 0.1 <= ev.hold_s <= MAX_HOLD_S:
                raise PlanError(f"event hold_s must be 0.1..{MAX_HOLD_S:g}")
            if ev.kind == "delay":
                if not 0 <= ev.delay_ms <= MAX_DELAY_MS:
                    raise PlanError(f"delay_ms must be 0..{MAX_DELAY_MS}")
            elif ev.kind == "mode":
                if ev.mode not in MODES:
                    raise PlanError("event mode is invalid")
            elif ev.kind == "pattern":
                if ev.pattern not in INPUT_PATTERNS:
                    raise PlanError("event pattern is invalid")
            elif ev.kind == "pause" and ev.hold_s is None:
                raise PlanError("pause events need hold_s")
        return self

    def sorted_events(self):
        return sorted(self.events, key=lambda e: (e.at_s, EVENT_KINDS.index(e.kind)))

    def mode_override(self):
        return MODE_OVERRIDE.get(self.mode)

    def video_settings(self):
        settings = VIDEO_SETTINGS.get(self.video_preset)
        return dict(settings) if settings else None

    def video_command(self):
        """Runtime X ``video`` command for this plan; ``None`` for ``current``."""
        return video_payload(self.video_preset)

    def segments(self):
        """Return non-overlapping display segments for the timeline UI."""
        events = self.sorted_events()
        result = []

        def add(kind, start, stop, value, index=-1):
            if stop > start:
                result.append(Segment(kind, round(start, 2), round(stop, 2),
                                      value, index))

        by_kind = {kind: [e for e in events if e.kind == kind] for kind in EVENT_KINDS}
        add("delay", 0.0, self.duration_s, 0)
        for i, ev in enumerate(by_kind["delay"]):
            stop = self.duration_s
            if i + 1 < len(by_kind["delay"]):
                stop = by_kind["delay"][i + 1].at_s
            if ev.hold_s is not None:
                stop = min(stop, ev.at_s + ev.hold_s)
            add("delay", ev.at_s, stop, ev.delay_ms, events.index(ev))
        add("mode", 0.0, self.duration_s, self.mode)
        for i, ev in enumerate(by_kind["mode"]):
            stop = self.duration_s
            if i + 1 < len(by_kind["mode"]):
                stop = by_kind["mode"][i + 1].at_s
            if ev.hold_s is not None:
                stop = min(stop, ev.at_s + ev.hold_s)
            add("mode", ev.at_s, stop, ev.mode, events.index(ev))
        add("pattern", 0.0, self.duration_s, self.input_pattern)
        for i, ev in enumerate(by_kind["pattern"]):
            stop = self.duration_s
            if i + 1 < len(by_kind["pattern"]):
                stop = by_kind["pattern"][i + 1].at_s
            add("pattern", ev.at_s, stop, ev.pattern, events.index(ev))
        for ev in by_kind["pause"]:
            add("pause", ev.at_s, min(self.duration_s, ev.at_s + ev.hold_s),
                "pause", events.index(ev))
        return result


def percentile(values, q):
    """Linear-interpolated percentile (q in 0..1); None for no values."""
    data = sorted(values)
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * max(0.0, min(1.0, q))
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return data[lo]
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def summarize(samples, keys=SUMMARY_KEYS):
    """p50/p90/p99/max for each metric, skipping paused/invalid samples."""
    result = {}
    for key in keys:
        values = []
        for sample in samples:
            if sample.get("paused"):
                continue
            value = sample.get(key)
            if value is None or isinstance(value, bool):
                continue
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                values.append(value)
        if not values:
            result[key] = {"n": 0}
            continue
        result[key] = {
            "n": len(values),
            "mean": round(sum(values) / len(values), 2),
            "p50": round(percentile(values, 0.50), 2),
            "p90": round(percentile(values, 0.90), 2),
            "p99": round(percentile(values, 0.99), 2),
            "max": round(max(values), 2),
        }
    return result


def demo_plan():
    """Small plan used by tools/test_cli.py and the smoke test."""
    return TestPlan(
        name="delay/pause smoke",
        warmup_s=2.0,
        duration_s=10.0,
        workload="light",
        mode="auto",
        input_pattern="strafe",
        events=[
            Event(at_s=2.0, kind="delay", delay_ms=100, hold_s=3.0),
            Event(at_s=6.0, kind="pause", hold_s=2.0),
        ],
    )

