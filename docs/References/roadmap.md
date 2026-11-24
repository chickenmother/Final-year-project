# Roadmap, schedule and workstreams

Status: 2026-11-23. Branch `feature/Cloud_X`, HEAD `57e2fe5`. This file is the single
source of truth for workstreams, schedule and current progress. The WS naming/docs and
WS1.3 are committed; the dev/feature/release model is in `docs/References/branches.md`.

## Naming

- Workstreams: **WS0 Foundation**, **WS1 System performance**, **WS2 Test tooling**,
  **WS3 Task placement**, **WS4 Validation & reporting**.
- Item IDs are `WS<t>.<n>` (for example `WS2.2`). An experiment adds the video preset:
  `WS1.1-A0`, `WS1.3-A1`. A report is identified by its workstream/preset and timestamp.
- `A0`, `A1`, `A2`, `intra`, `current` are **video presets**, not phases or workstreams.
- Historical labels (`Phase A/B`, `Phase 1/2/3`, `Milestones 1-6`) are retained only
  in archived evidence; the mapping is below.

## Overview

- **WS0 Foundation** - game core, menu/overlay, baseline 3-tier pipeline.
- **WS1 System performance** - X video/latency: baseline, keyframe fix, post-fix, network.
- **WS2 Test tooling** - runner/CLI, Tk control panel, X runtime control.
- **WS3 Task placement** - router, All Cloud / Offload A/B / All Edge / Pinned L, L/U metrics.
- **WS3.5 Free placement** - any A-E split as a stage chain (5 stages, 32 assignments), pixels
  channel for D→E, panel row editor, per-run crossing/stall counters.
- **WS4 Validation & reporting** - local/lab validation, comparison report, docs/archive.

## Schedule (sequence, not calendar dates)

| Order | Item | Work | Exit criterion | Effort |
|---|---|---|---|---|
| **Done** | WS1.3 | Post-fix smoke on the pulled lab X; one Y/Z; `ws1_3_a1.json`; report + X log | report `20261123-153034`; p50 79.2 / p90 108.94 vs WS1.1-A1 62.4 / 85.8 | 1 session |
| **Done** | WS2.2 | `tools/test_panel.py` Tk panel | start/pause/resume/terminate, timeline, live metrics, reports, Z window; E2E run `20261123-161423` | 2-3 sessions |
| **Done** | WS2.3 | X `video` / `stats` / `stop` | panel switches presets without restarting X; E2E `20261123-164025` (live A1→A2, 60 fps) | 1-2 sessions |
| **Done** | WS3.1 | Y task router + All Cloud | A-E/L placed on X; per-task metrics; E2E `20261124-111232` | 2 sessions |
| **Done** | WS3.2 | Offload A/B | A/B on Y; C-E/L on X; E2E `20261124-115317`; comparison report | 2 sessions |
| **Done** | WS3.3 | All Edge + Pinned L | C/D/E on Y; L on X; E2E `20261124-120713` | 2 sessions |
| **Done** | WS3.4 | L SQLite + U leaderboard view | store on X, submit/top through Y, ranked screen on Z | 2 sessions |
| **Now** | WS4.2 | Comparison report | tooling done (`tools/compare_reports.py`); WAN runs pending | 2-3 sessions |
| **Final** | WS4.3 | Docs/archive/final report | README/AGENTS/sync and report complete | ongoing |

Dependencies: WS1.3 is done (report archived) but a repeat is worth doing once the network/RTT is
recalibrated. WS2.2, WS2.3 and WS3.1–WS3.4 are done: all three placement patterns run with per-task
metrics and (for Offload A/B) the upload cost, and L/U provide the leaderboard. WS4.2 (the formal
comparison report) is the remaining research deliverable; WS4.3 runs throughout.
Adjust the sequence to the FYP deadline.

## Current state (verified 2026-11-24)

- Repo on `feature/ws3.5-free-placement` (branched from `dev` @ `388b468`).
- WS3.4.1 (safe test overlay) is pushed and fast-forwarded on `dev`; WS3.5 (free task
  placement) is implemented and validated locally on this branch.
- Lab X is at `cda0f52` (WS1.2) and must be pulled to the current commit for the next lab run;
  the WS3.1–WS3.5 checks used a local X.
- No X/Y/Z left running: the E2E tiers were stopped after the run (AGENTS cleanup rule).
- Reports: WS1.1 A0/A1/A2, WS1.3-A1 `20261123-153034`, WS2.2 `20261123-161423`, WS2.3
  `20261123-164025`, WS3.1 All Cloud `20261124-111232`, WS3.2 Offload A/B `20261124-115317`,
  WS3.3 All Edge `20261124-120713`, the 1-HP game-over run `20261124-124706` and the WS3.5
  chain matrix (below).
  Matched medium comparison on one PC: All Cloud `20261124-120640` e2e p50 14.85,
  Offload A/B 15.70 (536 KB/s upload), All Edge 13.10 (Y render 1.68 ms, encode 3.06 ms).
- WS3.4 evidence: direct X submit → rank 1; Z `leaderboard_get` → same row through Y;
  1-HP match → second row with `source: test`; U screen rendered both rows.
- WS3.5 evidence (isolated ports 8010-8012, 1280x720 H.264, local loopback):

  | chain | crossings | Z fps | e2e p50 | report |
  |---|---|---|---|---|
  | All Cloud (regression) | 0 | 60.0 | 16.1 | `20261124-143954` |
  | Offload A/B (regression) | 1 state | 60.0 | 16.6 | `20261124-144012` |
  | All Edge (regression) | 0 | 30.0 | 17.6 | `20261124-144129` |
  | A/B on X, C/D/E on Y | 1 state | 60.0 | 13.4 | `20261124-144414` |
  | A on X, B on Y, C/D/E on X | 2 state | 60.0 | 15.5 | `20261124-144629` |
  | A-D on X, E on Y (pixels, 30 s medium) | 1 pixels | 60.0 | 28.1 | `20261124-145508` |
  | A-D on Y, E on X (pixels raw) | 1 pixels | ~47 | 30.0 | `20261124-145259` |
  | A-E on Y | 0 | 60.0 | 12.4 | `20261124-144955` |

  The JPEG D→E hop costs ~15 ms of e2e at 1280x720/60 (88 KB per frame); raw costs
  ~120 MB/s and drops Z to ~47 fps without a stall or an IDR loop, because the sender
  declares its stride so Z never mistakes a gap for a lost packet.
- Validation gate: 150 unit tests, selftest hash `30f043...`, and all test plans load.

## Current progress

| Item | Status | Notes |
|---|---|---|
| WS0.1 Game core | Done | task-oriented core, entities, waves, snapshot/restore |
| WS0.2 Menu/overlay/game-over | Partial | leaderboard view still a placeholder |
| WS0.3 Baseline 3-tier | Done | X authoritative + Y fallback + Z display |
| WS1.1 Baseline | Done/archived | presets A0/A1/A2 under `logs/raw/phaseA_*` |
| WS1.2 Keyframe fix | Code done | `7d54592`; lab X at `cda0f52`; local 60 fps, 0 skips, 0.55 kf/s |
| WS1.3 Post-fix verification | Done | report `20261123-153034` (mode X); e2e p50 79.2 / p90 108.94; WS1.1-A1 was 62.4 / 85.8 |
| WS1.4 Network/adaptive | Planned | delay timeline exists; adaptive bitrate later |
| WS2.1 Test runner/CLI | Done | `1c20dce`; 27 tests; plan/report protocol |
| WS2.2 Tk panel | Done | `tools/test_panel.py` + `panel_model.py`; 28 new tests; E2E run `20261123-161423` |
| WS2.3 X runtime video | Done | `video`/`stats`/`stop` + `common/xstats.py`; E2E `20261123-164025` |
| WS3.1 Router + All Cloud | Done | `common/placement.py`; All Cloud applied, L pinned; E2E `20261124-111232` |
| WS3.2 Offload A/B | Done | `step_ab`/`step_c` split, `state` upload, `offload` metrics; E2E `20261124-115317` |
| WS3.3 All Edge + Pinned L | Done | A-E on Y, X idle (L only), no upload; E2E `20261124-120713` |
| WS3.4 L/U + metrics | Done | SQLite L on X, submit/top via Y, U screen on Z; 107 tests |
| WS3.4.1 Safe test overlay | Done | `safe` config on `test_start`, Z deep-merges; `FYP_TEST_SAFE=0` opt-out |
| WS3.5 Free placement (F1) | Done | `Chain`/`resolve_chain`/`describe_chain`, `placement: custom` + `placement_tasks`, panel A-E rows, L pinned |
| WS3.5 Chain executor (F2) | Done | `common/pipeline.py` routing + wire format, `step_a`/`step_b`, Y/X generic executors, pixels channel (JPEG/raw), stride declaration |
| WS4.1 Local/lab validation | Ongoing | repeatable runs; duplicate-process hygiene |
| WS4.2 Comparison report | Tooling done | `common/compare.py` + `tools/compare_reports.py`; 9 tests; local table generated; WAN runs pending |
| WS4.3 Docs/archive | Ongoing | this roadmap; README/AGENTS/sync |

### WS1.1 baseline results (archived)

- A0 GOP30/720p: e2e p50 62.6 / p90 83.96 ms; ~2.0 keyframes/s; keyframes 99-224 KB.
- A1 GOP120/720p: e2e p50 62.4 / p90 85.8 ms; raw X log lost.
- A2 GOP120/540p: e2e p50 53.2 / p90 77.54 ms; ~0.5 keyframes/s; keyframes ~205 KB; one 321 ms outlier.

### WS1.2 local verification (earlier isolated test)

60.2 fps, 0 skipped ticks, 0.55 keyframes/s, 97-117 KB frames, encode ~5.5 ms,
first-frame e2e ~13.1 ms, decode ~3.9 ms; intra-refresh max frame ~17 KB.

## Next step

1. Keep the WS1.3 `20261123-153034`, WS2.2 `20261123-161423`, WS2.3 `20261123-164025`, WS3.1 `20261124-111232`, WS3.2 `20261124-115317`, WS3.3 `20261124-120713`, comparison `20261124-120640`, game-over `20261124-124706` and WS3.5 matrix reports with the archive.
2. Run the three patterns over the real WAN (pull the lab X to the current commit first), then
   `tools/compare_reports.py --workload medium --out logs\reports\comparison_wan.md`.
3. Repeat the WS3.5 chain matrix over the WAN (the two-tier hops are where the crossings cost real
   RTT), and add the chain columns to the comparison tool (F3).
4. WS4.3: fold the WAN table into the README/docs and tag the release.

## Old -> new mapping

| Old name | New name |
|---|---|
| Phase A | **WS1.1 Baseline** |
| A0 / A1 / A2 | **video presets** used by `WS1.1-A0/-A1/-A2` (not phases) |
| Phase B | **WS1.2 Keyframe fix** + **WS1.3 Post-fix verification** |
| Phase 1 | **WS2.1 Test runner** |
| Phase 2 | **WS2.2 Tk panel** |
| Phase 3 | **WS2.3 X runtime control** |
| Task placement / Milestones 3-5 | **WS3.1-WS3.4** |
| Milestone 1 / 2 | **WS0.1 / WS0.2** |
| Milestone 6 | **WS3.5 (stretch)** |
| Final report | **WS4.1-WS4.3** |

## Historical names (retained, not rewritten)

- `logs/raw/phaseA_*` and `logs/raw/phaseA_README.md` - raw WS1.1 evidence; git-ignored.
- `logs/reports/2026*` - historical report data; the old `plan.name` values remain inside.
- `docs/archive/GAME_MVP_PLAN.md` - historical Milestones 1-6 plan.
- Existing `sync.txt` entries and commit messages - handoff/commit history.

Active docs, code, plans and new reports use WS names. The historical paths are kept so the
evidence stays traceable; this file is the mapping.

## Risks / blockers

- Duplicate Y/Z processes invalidate runs; only one pair at a time (AGENTS cleanup rule).
- WS1.3 needs the lab X listening and a stable A1/Z configuration for comparison.
- The task router/placement (WS3) is the largest remaining block; L and U are placeholders.
- Final report needs WS1.3 and WS3.2/3.3 results; do not overrun the FYP schedule.
- No commit/push unless explicitly requested; lab X no pull until asked.

## Related docs

- `README.md` - architecture, baseline, task model, commands.
- `docs/test-panel.md` - protocol/report schema, WS2.2 panel guide, WS2.3 plan.
- `docs/References/context.md` - topology, machines, current status.
- `docs/References/commands.md` - setup/run/test commands.
- `AGENTS.md` - universal rules and references.
- `sync.txt` - cross-tier handoff log.
- `docs/References/branches.md` - branch model and node packaging.