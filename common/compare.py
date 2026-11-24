"""WS4.2: compare test reports across placement patterns.

The research question is "where should each task run?", so the comparison has
to line up the same workload/video preset under All Cloud, Offload A/B and All
Edge and show latency, per-task compute and the upload cost side by side.

Kept free of sockets/pygame so it is unit-testable and can run anywhere the
reports are copied to.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

PLACEMENT_ORDER = {"legacy": 0, "all_cloud": 1, "offload_ab": 2, "all_edge": 3}
FIELDS = (
    "id", "placement", "placement_applied", "workload", "video_preset",
    "mode_final", "duration_s", "samples",
    "e2e_p50", "e2e_p90", "e2e_p99", "rtt_p50", "rtt_p90",
    "x_fps", "y_fps", "z_fps", "x_encode_p50", "x_encode_p95", "z_decode_p50",
    "sim_x", "sim_y", "hit_x", "hit_y", "render_x", "render_y",
    "encode_x", "encode_y", "net_x", "net_z", "offload_kb_s", "offload_total",
)


def load(path):
    with open(path, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    if not isinstance(report, dict):
        raise ValueError(f"{path} is not a report object")
    return report


def summarise(report):
    """Flatten one report into the columns the comparison needs."""
    env = report.get("environment") or {}
    plan = report.get("plan") or {}
    summary = report.get("summary") or {}
    tasks = env.get("task_stats") or {}
    offload = env.get("offload") or {}

    def metric(key, field="p50"):
        return (summary.get(key) or {}).get(field)

    def task(name, tier):
        return (((tasks.get(name) or {}).get(tier)) or {}).get("p50")

    return {
        "id": report.get("id"),
        "placement": env.get("placement") or plan.get("placement") or "legacy",
        "placement_applied": bool(env.get("placement_applied")),
        "workload": plan.get("workload"),
        "video_preset": plan.get("video_preset"),
        "mode_final": env.get("mode_final"),
        "duration_s": report.get("duration_s"),
        "samples": len(report.get("samples") or []),
        "e2e_p50": metric("e2e"),
        "e2e_p90": metric("e2e", "p90"),
        "e2e_p99": metric("e2e", "p99"),
        "rtt_p50": metric("rtt"),
        "rtt_p90": metric("rtt", "p90"),
        "x_fps": metric("x_fps"),
        "y_fps": metric("y_fps"),
        "z_fps": metric("z_fps"),
        "x_encode_p50": metric("x_encode"),
        "x_encode_p95": metric("x_encode_p95"),
        "z_decode_p50": metric("z_decode"),
        "sim_x": task("sim", "X"),
        "sim_y": task("sim", "Y"),
        "hit_x": task("hit", "X"),
        "hit_y": task("hit", "Y"),
        "render_x": task("render", "X"),
        "render_y": task("render", "Y"),
        "encode_x": task("encode", "X"),
        "encode_y": task("encode", "Y"),
        "net_x": task("net", "X"),
        "net_z": task("net", "Z"),
        "offload_kb_s": offload.get("kb_s"),
        "offload_total": offload.get("total"),
    }


def pick(reports, placements=None, workload=None):
    """One report per placement (the newest), optionally filtered by workload."""
    chosen = {}
    for report in reports:
        row = summarise(report) if "summary" in report else dict(report)
        if workload and row.get("workload") != workload:
            continue
        placement = row.get("placement") or "legacy"
        if placements and placement not in placements:
            continue
        # report ids are timestamps, so the larger id is the newer run
        current = chosen.get(placement)
        if current is None or str(row.get("id")) > str(current.get("id")):
            chosen[placement] = row
    return sorted(chosen.values(),
                  key=lambda row: PLACEMENT_ORDER.get(row["placement"], 99))


def add_deltas(rows, baseline="all_cloud"):
    """Add ``e2e_p50_delta`` / ``e2e_pct`` against the baseline row."""
    base = next((row for row in rows if row["placement"] == baseline), None)
    out = []
    for row in rows:
        row = dict(row)
        base_p50 = (base or {}).get("e2e_p50")
        if base_p50 and row.get("e2e_p50") is not None:
            row["e2e_p50_delta"] = round(row["e2e_p50"] - base_p50, 2)
            row["e2e_pct"] = round((row["e2e_p50"] / base_p50 - 1) * 100, 1)
        else:
            row["e2e_p50_delta"] = None
            row["e2e_pct"] = None
        out.append(row)
    return out


def _fmt(value, digits=1, suffix=""):
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return str(value)


def _tier(x_value, y_value):
    parts = []
    if x_value is not None:
        parts.append(f"X {_fmt(x_value, 2)}")
    if y_value is not None:
        parts.append(f"Y {_fmt(y_value, 2)}")
    return " / ".join(parts) or "—"


def markdown(rows):
    """Comparison table (latency, pipeline tier, per-task, upload)."""
    lines = [
        "| Pattern | Report | e2e p50 | Δ vs baseline | p90 | X / Y / Z fps "
        "| render p50 | encode p50 | upload |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        delta = row.get("e2e_p50_delta")
        pct = row.get("e2e_pct")
        delta_text = ("—" if delta is None
                      else f"{delta:+.2f} ms ({pct:+.1f}%)")
        upload = ("—" if not row.get("offload_kb_s")
                  else _fmt(row["offload_kb_s"], 1, " KB/s"))
        lines.append(
            f"| {row['placement']} | `{row['id']}` "
            f"| {_fmt(row.get('e2e_p50'), 2, ' ms')} | {delta_text} "
            f"| {_fmt(row.get('e2e_p90'), 2, ' ms')} "
            f"| {_fmt(row.get('x_fps'), 0)} / {_fmt(row.get('y_fps'), 0)} / "
            f"{_fmt(row.get('z_fps'), 0)} "
            f"| {_tier(row.get('render_x'), row.get('render_y'))} "
            f"| {_tier(row.get('encode_x'), row.get('encode_y'))} "
            f"| {upload} |")
    return "\n".join(lines)


def csv_text(rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(FIELDS) + ["e2e_p50_delta",
                                                           "e2e_pct"],
                            extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return out.getvalue()


def compare(reports, baseline="all_cloud", placements=None, workload=None):
    """Rows with deltas, ready for markdown()/csv_text()."""
    return add_deltas(pick(reports, placements, workload), baseline=baseline)


def write_outputs(rows, markdown_path=None, csv_path=None):
    paths = {}
    if markdown_path:
        path = Path(markdown_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown(rows) + "\n", encoding="utf-8")
        paths["markdown"] = str(path)
    if csv_path:
        path = Path(csv_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(csv_text(rows), encoding="utf-8")
        paths["csv"] = str(path)
    return paths
