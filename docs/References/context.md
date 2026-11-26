# Project context

- 3-tier: Cloud X → Edge Y → Client Z. Input Z→Y→X; video X→Y→Z.
- Runtime: X runs A–E + render/stream; Y is the decision proxy + fallback and holds the task
  router; Z is U; L is pinned to X. A plan can now place each stage of A–E on either tier.
- The README has the full architecture, task model A–E/L/U, and placement patterns (including the
  WS3.5 chain model and the D→E pixels channel).

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
  (`common/leaderboard.py`, `ui/leaderboard.py`); WS3.4.1 safe test overlay shipped.
- WS3.5 free placement shipped on `dev` (`feature/ws3.5-free-placement` fast-forwarded):
  `Chain`/`resolve_chain` (`common/placement.py`), `common/pipeline.py` (routing, counters,
  `stage`/`final`/`stride`/`pixels` wire format, `report_fields`), `step_a`/`step_b`
  (`game/simulation.py`), generic chain executors in `y_gateway.py`/`x_server.py`, panel A–E rows
  + a full-width `chain (WS3.5)` line, report `crossings`/`stream_tier`/`pixels_format`/
  `channels`/`stalls`/`encode_fps`/`stage_p50` (present on preset runs too, as 0/empty), and
  build stamps (`Y_BUILD`/`X_BUILD`) with a `chain_warning` when an old X accepts a custom table
  without confirming chain support. 155 tests; `tools/check_plans.py` loads all 18 plans.
- Lab X pulled to `cda0f52` (WS1.2) and needs a pull for WS2.3/WS3.x/WS3.5; those E2Es used a
  local X. No X/Y/Z left running (the E2E tiers were stopped). One Y and one Z at a time.
- WS1.3 complete: `20261123-153034`. WS2.2: `20261123-161423`. WS2.3: `20261123-164025`.
  WS3.1: `20261124-111232`. WS3.2: `20261124-115317` (536 KB/s upload). WS3.3: `20261124-120713`
  (X idle, Y 60 fps). WS3.4: L store + U view (direct submit rank 1, Z fetch through Y, 1-HP
  game-over row `20261124-124706`). Matched medium comparison: All Cloud `20261124-120640`
  e2e p50 14.85, Offload 15.70, All Edge 13.10 on one PC.
- WS3.5 local matrix (isolated ports 8010-8012, loopback): All Cloud 16.1 ms / Offload A/B 16.6 /
  All Edge 17.6 / A-B on X + C-E on Y 13.4 / split A/B 15.5 / A-D on X + E on Y (JPEG, 30 s
  medium) 28.1 at 60 fps / A-D on Y + E on X (raw) 30.0 at ~47 fps / A-E on Y 12.4. Reports:
  `20261124-143954`, `-144012`, `-144129`, `-144414`, `-144629`, `-145508`, `-145259`, `-144955`.
- Next: WAN runs of the three presets — pull **X and Y** (and Z) to the current commit first, since
  WS3.5 changed both gateways and Z's frame handling — then `tools/compare_reports.py
  --workload medium`; then the WS3.5 chain matrix over the WAN and the chain columns in the
  comparison tool (F3). Fine tuning and the release tag come after that.
  Roadmap/schedule: `docs/References/roadmap.md`.
