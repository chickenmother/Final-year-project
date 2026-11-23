# Project context

- 3-tier: Cloud X → Edge Y → Client Z. Input Z→Y→X; video X→Y→Z.
- Runtime: X runs A–E + render/stream; Y is the decision proxy + fallback
  (task router planned); Z is U; L is pinned to X and planned.
- The README has the full architecture, task model A–E/L/U, and placement patterns.

## Machines (current assignment; not fixed)

| Machine | Role | Notes |
|---|---|---|
| Home desktop (chicken-mother) | Y (sometimes Z) | confirm current assignment |
| Lab desktop (matslabsungky) | X | pulled to `cda0f52` |
| Laptop1 (andoryuuuspc) | Y or Z | |
| Laptop2 (pc23-148d) | Z | |

Only one Y and one Z at a time. Placement is not fixed; I test combinations.

## Current status

- WS2.1 test runner/CLI shipped; WS2.2 Tk control panel shipped (`tools/test_panel.py` +
  `tools/panel_model.py`); WS2.3 X runtime `video`/`stats`/`stop` shipped (`common/xstats.py`).
  WS1.1 (video presets A0/A1/A2) archived under `logs/raw`.
- Lab X pulled to `cda0f52` (WS1.2) and needs a pull for WS2.3; the WS2.3 E2E used a local X.
  No X/Y/Z left running (the E2E tiers were stopped). One Y and one Z at a time.
- WS1.3 complete: report `20261123-153034` (mode X; e2e p50 79.2 / p90 108.94). WS2.2 complete:
  `20261123-161423`. WS2.3 complete: `20261123-164025` (A1 → A2 mid-run, 60 fps, encode p50
  4.96 / p95 5.56 ms). Next: WS3.1 task router + All Cloud.
  Roadmap/schedule: `docs/References/roadmap.md`.
