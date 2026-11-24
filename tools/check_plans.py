"""Load every bundled test plan (regression gate for plan-schema changes)."""
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.testplan import TestPlan

bad = 0
for path in sorted(glob.glob(str(ROOT / "tools" / "plans" / "*.json"))):
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    try:
        plan = TestPlan.from_dict(raw)
        plan.validate()
        table = plan.placement_table()
        print(f"OK   {path}  placement={plan.placement}"
              f"{' ' + str(table) if table else ''}")
    except Exception as exc:                      # noqa: BLE001 - report all
        bad += 1
        print(f"FAIL {path}: {exc}")
sys.exit(1 if bad else 0)
