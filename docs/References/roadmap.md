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
- **WS4 Validation & reporting** - local/lab validation, comparison report, docs/archive.

## Schedule (sequence, not calendar dates)

| Order | Item | Work | Exit criterion | Effort |
|---|---|---|---|---|
| **Now** | WS1.3 | Post-fix smoke on the pulled lab X; one Y/Z; `ws1_3_a1.json`; report + X log | p50/p90/p99, keyframes, encode vs WS1.1 | 1 session |
| **Next** | WS2.2 | `tools/test_panel.py` Tk panel | start/pause/resume/terminate, timeline, live metrics, reports, Z window | 2-3 sessions |
| **Then** | WS2.3 | X `video` / `stats` / `stop` | panel switches presets without restarting X | 1-2 sessions |
| **Then** | WS3.1 | Y task router + All Cloud | A-E/L tasks placed; per-task metrics | 2 sessions |
| **Then** | WS3.2 | Offload A/B | A/B on Y; C-E/L on X; comparison report | 2 sessions |
| **Then** | WS3.3 | All Edge + Pinned L | edge result; leaderboard authority | 2 sessions |
| **Then** | WS3.4 | L SQLite + U leaderboard view + metrics | leaderboard displayed; per-task data | 2 sessions |
| **Final** | WS4.2 | Comparison report | FYP-ready WS1.1/WS1.3 and WS3.1-WS3.3 results | 2-3 sessions |
| **Final** | WS4.3 | Docs/archive/final report | README/AGENTS/sync and report complete | ongoing |

Dependencies: WS1.3 needs the lab X plus one Y/Z and the WS1.1 data (already archived).
WS2.2 can be built locally while X is prepared. WS2.3 depends on WS2.2. WS3.1 depends on
WS2.2; WS3.2 follows WS3.1; WS3.3/WS3.4 follow WS3.2. WS4.2 depends on WS1.3 and WS3.2/3.3.
WS4.1 and WS4.3 run throughout. Adjust the sequence to the FYP deadline.

## Current state (verified 2026-11-23)

- Repo `feature/Cloud_X`, HEAD `f334298`; this naming/docs change is uncommitted.
- Lab X is at `cda0f52` (contains the WS1.2 fix); `x_server` is listening on 8001 (Tailscale, verified 2026-11-23).
- Home Y is running (PID 3764, ports 8000/8002); one Y; no Z or test runner visible.
- Reports: WS1.1 A0/A1/A2 and WS1.3-A1 `20261123-153034` (mode X; e2e p50 79.2 / p90 108.94).
  WS1.3 is worse than WS1.1-A1 (62.4 / 85.8); the current RTT is higher (p50 63 / p90 82).
- Validation gate for this change: 27 unit tests, selftest hash, and all test plans load.

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
| WS2.2 Tk panel | **Next build** | `tools/test_panel.py` |
| WS2.3 X runtime video | Planned | `video`/`stats`/`stop` |
| WS3.1 Router + All Cloud | Planned | task table; A-E/L placement |
| WS3.2 Offload A/B | Planned | local A/B copies on Y |
| WS3.3 All Edge + Pinned L | Planned | edge render; L on X |
| WS3.4 L/U + metrics | Planned | SQLite L; leaderboard view; per-task data |
| WS4.1 Local/lab validation | Ongoing | repeatable runs; duplicate-process hygiene |
| WS4.2 Comparison report | Planned | after WS1.3 and WS3.2/3.3 |
| WS4.3 Docs/archive | Ongoing | this roadmap; README/AGENTS/sync |

### WS1.1 baseline results (archived)

- A0 GOP30/720p: e2e p50 62.6 / p90 83.96 ms; ~2.0 keyframes/s; keyframes 99-224 KB.
- A1 GOP120/720p: e2e p50 62.4 / p90 85.8 ms; raw X log lost.
- A2 GOP120/540p: e2e p50 53.2 / p90 77.54 ms; ~0.5 keyframes/s; keyframes ~205 KB; one 321 ms outlier.

### WS1.2 local verification (earlier isolated test)

60.2 fps, 0 skipped ticks, 0.55 keyframes/s, 97-117 KB frames, encode ~5.5 ms,
first-frame e2e ~13.1 ms, decode ~3.9 ms; intra-refresh max frame ~17 KB.

## Next step

1. Keep the WS1.3 report `20261123-153034` with the WS1.1 archive; copy the lab X log when available.
2. Build WS2.2 (`tools/test_panel.py`): plan/timeline editor, Start/Pause/Resume/Terminate, live metrics, reports, Z window.
3. Use the panel for the next WS1.3 repeat after the network/RTT is recalibrated.

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
- `docs/test-panel.md` - protocol/report schema and WS2.2/WS2.3 plan.
- `docs/References/context.md` - topology, machines, current status.
- `docs/References/commands.md` - setup/run/test commands.
- `AGENTS.md` - universal rules and references.
- `sync.txt` - cross-tier handoff log.
- `docs/References/branches.md` - branch model and node packaging.