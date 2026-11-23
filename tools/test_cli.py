"""Drive a test plan through Y's dashboard socket without the Tk panel.

Examples
--------
    python tools/test_cli.py --y ws://127.0.0.1:8002
    python tools/test_cli.py --y ws://127.0.0.1:8002 --plan tools/plans/ws2_1_smoke.json

The CLI sends a panel hello, starts the plan, prints the test progress and live
metrics, and stops the test on Ctrl+C.  Reports are written by Y to
logs/reports/<id>.json (+ .csv).
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from websockets.asyncio.client import connect

from common.testplan import TestPlan, demo_plan


def _load_plan(path):
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            return TestPlan.from_dict(json.load(handle))
    return demo_plan()


def _fmt(value, digits=0):
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _print_state(state, last):
    test = state.get("test") or {}
    phase = test.get("state", "-")
    if phase != last:
        print(f"\n== test {phase} ==")
    print(f"  t={_fmt(test.get('elapsed_s'), 1)}/{_fmt(test.get('duration_s'), 1)}s "
          f"mode={state.get('mode')} rtt={_fmt(state.get('rtt'))} "
          f"delay={_fmt(state.get('delay_ms'))} e2e={_fmt(state.get('e2e'))} "
          f"x={_fmt(state.get('x_fps'), 1)} y={_fmt(state.get('y_fps'), 1)} "
          f"z={_fmt((state.get('z_stats') or {}).get('fps'), 1)} "
          f"next={((test.get('next_event') or {}).get('label') or '-')}")
    if test.get("error"):
        print(f"  error: {test['error']}")
    return phase


async def run(args):
    plan = _load_plan(args.plan)
    print(f"plan: {plan.name} ({plan.warmup_s:g}+{plan.duration_s:g}s, "
          f"{plan.workload}, mode {plan.mode}, input {plan.input_pattern})")
    async with connect(args.y, max_size=4 << 20, compression=None) as ws:
        await ws.send(json.dumps({"cmd": "hello"}))
        await ws.send(json.dumps({"cmd": "test_start",
                                  "plan": plan.to_dict()}))
        last = None
        try:
            async for raw in ws:
                message = json.loads(raw)
                if not isinstance(message, dict):
                    continue
                kind = message.get("t")
                if kind == "error":
                    print(f"Y error: {message.get('message')}")
                    if message.get("command") == "test_start":
                        return 2
                    continue
                if kind in ("hello", "reports"):
                    continue
                if kind == "report":
                    report = message.get("report") or {}
                    print(f"report {report.get('id')} {report.get('date')} "
                          f"{report.get('time')} duration={report.get('duration_s')}s")
                    for key in ("e2e", "rtt", "z_fps", "x_fps"):
                        summary = (report.get("summary") or {}).get(key) or {}
                        if summary.get("n"):
                            print(f"  {key:6s} p50={summary['p50']} "
                                  f"p90={summary['p90']} max={summary['max']}")
                    return 0
                test = message.get("test")
                if not test:
                    continue
                last = _print_state(message, last)
                if last in ("finished", "error"):
                    report_id = test.get("report_id")
                    if report_id:
                        await ws.send(json.dumps({"cmd": "get_report",
                                                  "id": report_id}))
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\nstopping test...")
            await ws.send(json.dumps({"cmd": "test_stop"}))
            await asyncio.sleep(0.5)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--y", default="ws://127.0.0.1:8002",
                        help="Y dashboard websocket (default: %(default)s)")
    parser.add_argument("--plan", default=None,
                        help="plan JSON file; omit for the built-in smoke plan")
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
