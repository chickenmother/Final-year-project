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

- WS2.1 test runner/CLI shipped; WS1.1 (video presets A0/A1/A2) archived under `logs/raw`.
- Lab X pulled to `cda0f52` (WS1.2); `x_server` not currently listening. Home Y is running (PID 3764; 8000/8002); no local X on 8001.
- Next: WS1.3 post-fix verification, WS2.2 Tk panel, WS2.3 X runtime video, WS3 task router/placement. Roadmap/schedule: `docs/References/roadmap.md`.
