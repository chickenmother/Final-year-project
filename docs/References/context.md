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
  `tools/panel_model.py`); WS2.3 X runtime `video`/`stats`/`stop` shipped (`common/xstats.py`);
  WS3.1 All Cloud, WS3.2 Offload A/B and WS3.3 All Edge shipped (`common/placement.py`,
  `game/simulation.py` A+B/C split); WS3.4 L (SQLite on X) + U leaderboard view shipped
  (`common/leaderboard.py`, `ui/leaderboard.py`). WS1.1 (A0/A1/A2) archived under `logs/raw`.
- Lab X pulled to `cda0f52` (WS1.2) and needs a pull for WS2.3/WS3.x; those E2Es used a local X.
  No X/Y/Z left running (the E2E tiers were stopped). One Y and one Z at a time.
- WS1.3 complete: `20261123-153034`. WS2.2: `20261123-161423`. WS2.3: `20261123-164025`.
  WS3.1: `20261124-111232`. WS3.2: `20261124-115317` (536 KB/s upload). WS3.3: `20261124-120713`
  (X idle, Y 60 fps). WS3.4: L store + U view (direct submit rank 1, Z fetch through Y, 1-HP
  game-over row `20261124-124706`). Matched medium comparison: All Cloud `20261124-120640`
  e2e p50 14.85, Offload 15.70, All Edge 13.10 on one PC. Next: WS4.2 comparison report.
  Roadmap/schedule: `docs/References/roadmap.md`.
