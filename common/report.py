"""Per-test report files shared by Y and the Tk control panel.

A report is one JSON file plus a CSV export of the same samples.  The JSON is
what the panel shows and downloads; the CSV is convenient for spreadsheets and
matches the raw log workflow.

The modules deliberately avoid pygame/av so they can be imported by tests and
by the Y tier without pulling in video dependencies.
"""
from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path

from common.testplan import TestPlan, summarize


def report_dir(root=None):
    """Return (and create) the report directory."""
    path = Path(root or ".") / "logs" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_id(when=None):
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(when))


def build(plan, started_at, ended_at, samples, events, environment=None,
          report_id=None):
    """Build the JSON-serialisable report dictionary."""
    if not isinstance(plan, TestPlan):
        raise TypeError("plan must be a TestPlan")
    start = time.time() if started_at is None else float(started_at)
    end = time.time() if ended_at is None else float(ended_at)
    local = time.localtime(start)
    return {
        "id": report_id or new_id(start),
        "date": time.strftime("%Y-%m-%d", local),
        "time": time.strftime("%H:%M:%S", local),
        "ended_time": time.strftime("%H:%M:%S", time.localtime(end)),
        "started_unix": round(start, 3),
        "ended_unix": round(end, 3),
        "duration_s": round(max(0.0, end - start), 2),
        "plan": plan.to_dict(),
        "environment": environment or {},
        "events": events or [],
        "samples": samples or [],
        "summary": summarize(samples or []),
    }


def _csv_fields(report):
    keys = []
    for sample in report.get("samples", []):
        for key in sample:
            if key not in keys:
                keys.append(key)
    return keys or ["t"]


def write(directory, report):
    """Atomically write report.json and report.csv; return both paths."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    report_id = str(report["id"])
    json_path = directory / f"{report_id}.json"
    csv_path = directory / f"{report_id}.csv"
    tmp = json_path.with_name(json_path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, json_path)

    fields = _csv_fields(report)
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for sample in report.get("samples", []):
            writer.writerow(sample)
    return {"json": str(json_path), "csv": str(csv_path)}


def _meta(report):
    plan = report.get("plan") or {}
    return {
        "id": report.get("id"),
        "date": report.get("date"),
        "time": report.get("time"),
        "duration_s": report.get("duration_s"),
        "name": plan.get("name"),
        "mode": plan.get("mode"),
        "workload": plan.get("workload"),
        "video_preset": plan.get("video_preset"),
        "summary": report.get("summary", {}),
    }


def list_reports(directory, limit=50):
    """Newest-first metadata for the panel/report history."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("*.json"), key=lambda p: p.name, reverse=True):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(report, dict):
            continue
        meta = _meta(report)
        meta["file"] = str(path)
        out.append(meta)
        if len(out) >= limit:
            break
    return out


def load(directory, report_id):
    """Load one report by id (a bare id or a filename)."""
    directory = Path(directory)
    name = Path(str(report_id)).name
    if not name.endswith(".json"):
        name += ".json"
    path = directory / name
    with open(path, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    if not isinstance(report, dict):
        raise ValueError(f"{path} is not a report object")
    return report
