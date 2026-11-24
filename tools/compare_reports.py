"""WS4.2: build the cross-pattern comparison from Y's reports.

Examples
--------
    python tools/compare_reports.py --workload medium
    python tools/compare_reports.py --ids 20261124-120640,20261124-115317 ^
        --out logs/reports/comparison.md --csv logs/reports/comparison.csv

By default it picks the newest report per placement from ``logs/reports`` and
prints a markdown table (e2e latency, the tier that rendered/encoded, per-task
p50s and the Offload A/B upload).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common import compare as cmp  # noqa: E402


def _load_dir(directory):
    reports = []
    for path in sorted(Path(directory).glob("*.json")):
        try:
            reports.append(cmp.load(path))
        except (OSError, ValueError):
            continue
    return reports


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", default=str(ROOT / "logs" / "reports"),
                        help="report directory (default: %(default)s)")
    parser.add_argument("--ids", default=None,
                        help="comma-separated report ids (skip auto-selection)")
    parser.add_argument("--placement", default=None,
                        help="comma-separated placements to include")
    parser.add_argument("--workload", default=None,
                        help="only reports for this workload (light/medium/heavy)")
    parser.add_argument("--baseline", default="all_cloud",
                        help="placement used for the deltas (default: %(default)s)")
    parser.add_argument("--out", default=None,
                        help="write the markdown table here")
    parser.add_argument("--csv", default=None, help="write the CSV here")
    parser.add_argument("--json", action="store_true",
                        help="print the rows as JSON instead of markdown")
    args = parser.parse_args(argv)

    directory = Path(args.reports)
    if args.ids:
        reports = [cmp.load(directory / f"{name.strip()}.json")
                   for name in args.ids.split(",") if name.strip()]
        rows = cmp.add_deltas([cmp.summarise(report) for report in reports],
                              baseline=args.baseline)
    else:
        placements = (tuple(part.strip() for part in args.placement.split(","))
                      if args.placement else None)
        rows = cmp.compare(_load_dir(directory), baseline=args.baseline,
                           placements=placements, workload=args.workload)

    if not rows:
        print("no reports matched")
        return 2
    print(json.dumps(rows, indent=2) if args.json else cmp.markdown(rows))
    paths = cmp.write_outputs(rows, args.out, args.csv)
    for kind, path in paths.items():
        print(f"{kind}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
