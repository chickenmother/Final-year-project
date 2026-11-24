"""Task-level placement model (WS3.1).

README's A-U task model is put into practice by a router on Middle Y.  This
module is the shared, dependency-free half so it can be unit-tested without
sockets:

- the task table and the placement patterns,
- validation (L is pinned to X; U never leaves End Z),
- a compact per-task timing collector plus a merge with X's p50s.

A pattern says which tier runs each task; "legacy" means the whole-pipeline
baseline where Y keeps a full copy and switches with RTT (`mode`).
"""
from __future__ import annotations

import collections

from common.testplan import percentile

TASKS = ("A", "B", "C", "D", "E", "L")
TIERS = ("X", "Y")
PINNED = {"L": "X"}                 # leaderboard store never moves
LOCAL_TASK = "U"                    # menu/overlay/leaderboard view lives on Z
# A-C run inside Game.step(), so the router measures them together as "sim"
# until profiling justifies a split (README: split only for a hotspot).
METRIC_TASKS = ("sim", "hit", "render", "encode", "net")

PATTERNS = {
    "legacy": None,                 # whole-pipeline RTT fallback (mode)
    "all_cloud": {"A": "X", "B": "X", "C": "X", "D": "X", "E": "X", "L": "X"},
    "offload_ab": {"A": "Y", "B": "Y", "C": "X", "D": "X", "E": "X", "L": "X"},
    "all_edge": {"A": "Y", "B": "Y", "C": "Y", "D": "Y", "E": "Y", "L": "X"},
}
PATTERN_NAMES = tuple(PATTERNS)


class PlacementError(ValueError):
    """Invalid placement; the message is meant for the control panel."""


def pattern_table(name):
    """Placement table for a pattern name; ``None`` for ``legacy``."""
    key = str(name or "").strip().lower()
    if key not in PATTERNS:
        raise PlacementError(
            f"placement must be one of {', '.join(PATTERN_NAMES)}")
    table = PATTERNS[key]
    return None if table is None else dict(table)


def validate(tasks, require_all=False):
    """Validate a placement table and return a tier-only copy.

    ``require_all`` is used for a full pattern (every task A-E/L present);
    a partial table is what Y forwards to X (only the tasks X owns).
    """
    if not isinstance(tasks, dict) or not tasks:
        raise PlacementError("placement must be a non-empty task table")
    clean = {}
    for task, tier in tasks.items():
        name = str(task).strip().upper()
        where = str(tier).strip().upper()
        if name == LOCAL_TASK:
            raise PlacementError("U is local to End Z and cannot be placed")
        if name not in TASKS:
            raise PlacementError(f"unknown task {task!r}; use {', '.join(TASKS)}")
        if where not in TIERS:
            raise PlacementError(f"task {name} must run on X or Y")
        if name in PINNED and where != PINNED[name]:
            raise PlacementError(f"task {name} is pinned to {PINNED[name]}")
        clean[name] = where
    if require_all:
        missing = [task for task in TASKS if task not in clean]
        if missing:
            raise PlacementError(f"placement is missing {', '.join(missing)}")
    return clean


def owners(tasks, tier):
    """Sorted task ids a tier owns in ``tasks``."""
    tier = str(tier).strip().upper()
    return [task for task in TASKS if (tasks or {}).get(task) == tier]


def render_tier(tasks):
    """Tier that renders in ``tasks`` (D), or ``None`` when unknown.

    A placement experiment must render where the pattern says, otherwise the
    legacy RTT fallback would move rendering to Y and invalidate the run
    (e.g. "All Cloud" measured with Y rendering).
    """
    return (tasks or {}).get("D")


def remote_ab(tasks):
    """True when A and B run on Y, i.e. Y must ship the state up (WS3.2)."""
    return bool(tasks) and (tasks.get("A") == "Y" and tasks.get("B") == "Y")


def describe(tasks):
    """Human-readable summary for the panel/status line."""
    if not tasks:
        return "legacy whole-pipeline"
    groups = {}
    for task, tier in tasks.items():
        groups.setdefault(tier, []).append(task)
    parts = [f"{'/'.join(sorted(names))} on {tier}"
             for tier, names in sorted(groups.items())]
    return ", ".join(parts) + ", U on Z"


class TaskStats:
    """p50/p95 of per-task timings per tier (Y's own measurements)."""

    def __init__(self, window=120):
        self.window = max(5, int(window))
        self._samples = collections.defaultdict(
            lambda: collections.deque(maxlen=self.window))

    def add(self, task, ms, tier="Y"):
        key = str(task).strip().lower()
        if key not in METRIC_TASKS:
            raise PlacementError(f"unknown metric task {task!r}")
        try:
            value = float(ms)
        except (TypeError, ValueError):
            return
        if value < 0 or value != value:      # negative or NaN
            return
        self._samples[(key, str(tier).strip().upper())].append(value)

    def reset(self):
        self._samples.clear()

    def snapshot(self):
        out = {}
        for (task, tier), values in self._samples.items():
            if not values:
                continue
            data = sorted(values)
            out.setdefault(task, {})[tier] = {
                "n": len(data),
                "p50": round(percentile(data, 0.50), 2),
                "p95": round(percentile(data, 0.95), 2),
            }
        return out


def merge_metrics(local, x_stats=None, rtt=None, rtt_zy=None):
    """Combine Y's timings with X's p50s and the measured hop times.

    ``local`` is :meth:`TaskStats.snapshot`; ``x_stats`` is the WS2.3 payload
    from Cloud X; ``rtt``/``rtt_zy`` are the X<->Y and Z<->Y round trips.
    """
    merged = {task: dict(tiers) for task, tiers in (local or {}).items()}
    x_stats = x_stats or {}
    for task, key in (("sim", "sim_p50"), ("hit", "hit_p50"),
                      ("render", "render_p50"), ("encode", "encode_p50")):
        value = x_stats.get(key)
        if isinstance(value, (int, float)):
            entry = merged.setdefault(task, {})
            entry["X"] = {"n": int(x_stats.get("frames") or 0),
                          "p50": round(float(value), 2)}
    if rtt:
        merged.setdefault("net", {})["X"] = {"n": 1, "p50": round(float(rtt), 2)}
    if rtt_zy:
        merged.setdefault("net", {})["Z"] = {"n": 1, "p50": round(float(rtt_zy), 2)}
    return merged
