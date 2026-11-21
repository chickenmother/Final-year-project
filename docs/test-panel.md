# Test Control Panel

Status: **Phase 1 implemented** (commit `1c20dce`). Phase 2 is the Tk panel;
Phase 3 adds runtime X video switching. This document is the protocol/report
reference; the README has the short version.

## Purpose

The panel turns a measurement into a **reproducible plan**: choose the test
mode/pattern, duration, warm-up and a timeline of delay/pause/mode/input events,
watch progress, pause or stop the run, and get a report with date/time, RTT,
injected delay, FPS and input→display latency.

## Roles

```
Tk panel (Phase 2) ──WebSocket──► Middle Y (TestRunner)
                                      │  timeline, samples, report
                                      ├──► Cloud X (start/pause/resume/stop; Phase 3: video/stats)
                                      └──► End Z test mode (input patterns, overlay, FPS/decode stats)
```

- **Y** owns the test state machine and writes the report. It already sits
  between Z and X, owns the `DelayLine` and has the dashboard socket.
- **Z** runs with `FYP_TEST=1`: it opens its normal pygame window, connects to
  Y, sends `hello`, and waits for test commands instead of showing the menu.
- **X** is started normally. Phase 1 treats its encoder settings as fixed by
  the `FYP_X_*` environment; Phase 3 can change them at runtime.

## Test plans

A plan is plain JSON. The full example lives in
`tools/plans/phase1_smoke.json`.

```json
{
  "name": "A1 delay sweep",
  "warmup_s": 5,
  "duration_s": 60,
  "seed": 12345,
  "workload": "light",
  "mode": "auto",
  "video_preset": "A1",
  "input_pattern": "strafe",
  "events": [
    {"at_s": 10, "kind": "delay",   "delay_ms": 100, "hold_s": 15},
    {"at_s": 25, "kind": "delay",   "delay_ms": 0},
    {"at_s": 35, "kind": "mode",    "mode": "edge",  "hold_s": 10},
    {"at_s": 50, "kind": "pause",   "hold_s": 5},
    {"at_s": 55, "kind": "pattern", "pattern": "shoot"}
  ]
}
```

| Field | Values | Meaning |
|---|---|---|
| `workload` | `light`, `medium`, `heavy` | game profile (bots/obstacles/bullets) |
| `mode` (legacy) | `auto`, `cloud`, `edge` | Y whole-pipeline: RTT auto-switch, force X, force Y |
| `placement` (planned) | `all_cloud`, `offload_ab`, `all_edge`, `pinned` | task-level placement; task router planned |
| `video_preset` | `current`, `A0`, `A1`, `A2`, `intra` | recorded in Phase 1; applied to X in Phase 3 |
| `input_pattern` | `idle`, `strafe`, `circle`, `figure8`, `shoot` | deterministic Z input |
| `warmup_s` | 0–60 | excluded from the measurement |
| `duration_s` | 0.1–600 | measurement window |
| `events[].at_s` | 0–`duration_s` | relative to the measurement start |

Event kinds:

- **delay** — sets the injected X↔Y RTT (`0–400 ms`). Holds until the next delay
  event or `hold_s`.
- **mode** — temporarily overrides Y’s RTT auto-switch; reverts to the plan’s
  `mode` after `hold_s`.
- **pause** — freezes the game/clock for `hold_s`; paused samples are excluded
  from summaries.
- **pattern** — changes the Z input pattern; persists until the next pattern.

## Safe / unattended runs

The test config should make the match unable to end. Use the isolated config
from `tools/autoplay_z.ps1` (`player.max_hp=1000`, zero obstacle/bot damage,
`light` workload) and point Z at it with `FYP_GAME_CONFIG`. `FYP_TEST=1` then
runs the scripted inputs; the game window stays open.

## Protocol

The panel connects to Y’s dashboard WebSocket (port `8002`) and sends
`{"cmd":"hello"}` first so Y treats it as a panel (the legacy browser dashboard
keeps receiving the plain state push).

Panel → Y:

| Command | Payload | Effect |
|---|---|---|
| `test_start` | `{plan: {...}}` | validate + start a run |
| `test_pause` | — | pause clock/game/inputs |
| `test_resume` | — | resume |
| `test_stop` | — | stop, finalise report, return Z to ready |
| `set_plan` | `{plan: {...}}` | validate/preview without starting |
| `list_reports` | — | reply `{"t":"reports","reports":[...]}` |
| `get_report` | `{id}` | reply `{"t":"report","report":{...}}` |
| `delay_ms` | number | legacy manual slider |

Y → Z (inside the normal data socket, on a control queue ahead of frames):

```json
{"t":"test","cmd":"start","workload":"light","seed":12345,
 "pattern":"strafe","plan":"A1 delay sweep"}
{"t":"test","cmd":"pause"}
{"t":"test","cmd":"resume"}
{"t":"test","cmd":"pattern","pattern":"shoot"}
{"t":"test","cmd":"stop"}
```

Y → X uses the existing `start`/`pause`/`resume`; the X↔Y `DelayLine` carries
the timeline delay events. The Y state (`state["test"]`) is pushed at 5 Hz:

```json
{"state":"running","name":"A1 delay sweep","warmup_s":5,"duration_s":60,
 "elapsed_s":12.3,"remaining_s":47.7,"progress":0.205,
 "mode":"X","mode_override":null,"pattern":"strafe","video_preset":"A1",
 "next_event":{"at_s":25,"kind":"delay","value":0,"label":"delay 0 ms"},
 "events":[...],"report_id":"20261119-173549","error":""}
```

### Z test mode

- Start with `FYP_TEST=1` (the launcher may be `run_z.cmd <Y_IP>`).
- The window opens normally and shows `TEST READY`, then `TEST RUNNING` /
  `TEST PAUSED` with the elapsed time.
- Manual ESC pause is disabled; the panel controls pause/stop.
- Input patterns are deterministic and can change mid-run.
- FPS/decode are sent with every input message so Y can record them.

## Reports

Y writes `logs/reports/<id>.json` and `.csv`:

- **meta** — id, date/time, start/end, duration, plan, environment
  (thresholds, game config, Y version, video preset/runtime, paused total).
- **events** — applied timeline events with elapsed/wall times.
- **samples** — 5 Hz: `t`, mode, RTT, injected delay, e2e, Z↔Y RTT, X/Y/Z FPS,
  X encode (Phase 3), Z decode, tick/score/HP, paused flag.
- **summary** — `n`, mean, p50, p90, p99, max for RTT, delay, e2e, X/Y/Z FPS,
  encode/decode; paused samples excluded.

The raw per-frame logs remain in `logs/log_x.csv`, `logs/log_y.csv`,
`logs/log_z.csv`. Historical root logs are archived under `logs/raw/`.

## CLI (Phase 1)

```powershell
$env:FYP_TEST = "1"
.\run_z.cmd <Y_IP>

.\venv\Scripts\python.exe tools\test_cli.py `
    --y ws://<Y_IP>:8002 --plan tools\plans\phase1_smoke.json
```

`test_cli.py` prints the plan, progress and final summary, and fetches the
report after the run. Ctrl+C sends `test_stop`.

## Phase 2 — Tk panel

`tools/test_panel.py` (Tk 8.6, stdlib) will provide:

- plan/preset editor, workload/mode/input/video/placement selectors (placement once the router lands)
- timeline editor and visual markers
- Start / Pause / Resume / Terminate, progress and phase
- live Y/X/Z metrics and the current event
- report history, JSON open and CSV export
- Z process launch/focus (the pygame window is the actual game)
- optional browser dashboard link for remote monitoring

## Phase 3 — X runtime video

After Phase A captures are finished, add to `x_server.py`:

- `{"t":"video","gop":...,"size":[...],"bitrate":...,"intra_refresh":...}`:
  rebuild the H.264 encoder, force an IDR; the Z decoder handles the new size.
- `{"t":"stats",...}` every 1 s: fps, encode p50/p95, keyframes, bytes.
- `{"t":"stop"}`: stop stepping/streaming without killing the process.

The panel’s A0/A1/A2/intra presets then apply without restarting X. Until then
the X encoder is whatever `FYP_X_GOP`, `FYP_X_SIZE`, `FYP_X_BITRATE` and
`FYP_X_INTRA_REFRESH` were set to at X startup; the report records
`video_runtime: current`.

## Environment

| Variable | Tier | Meaning |
|---|---|---|
| `FYP_TEST=1` | Z | unattended test mode; no menu; waits for Y commands |
| `FYP_GAME_CONFIG` | Z | alternate game config (the immortal test config) |
| `FYP_X_GOP`, `FYP_X_SIZE`, `FYP_X_BITRATE` | X | encoder preset at startup (Phase 1/2) |
| `FYP_X_INTRA_REFRESH=1` | X and Z | intra-refresh; must match on both |
| `FYP_X_STREAM_EVERY`, `FYP_Y_STREAM_EVERY` | sender and Z | frame stride; must match |
| `FYP_HIGH_MS`, `FYP_LOW_MS`, `FYP_BAD_COUNT`, `FYP_RECOVER_S` | Y | RTT mode-switch thresholds |
| `FYP_Z_INPUT_HZ` | Z | input sample rate (default 120) |

The test config used by the unattended runs should keep the player alive:
`player.max_hp=1000`, `player.obstacle_damage=0`, `player.bot_damage=0`, and a
`light` workload. `tools/autoplay_z.ps1` generates this in
`%TEMP%\fyp_phaseA\game_config.json` and can start Z with it.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `test_start` replies “no End Z is connected” | Z not in test mode / not connected | start Z with `FYP_TEST=1`; check Y’s “Z connected” |
| Test pauses immediately / no frames | duplicate Y or Z processes sharing ports | kill all but one Y and one Z; check `Get-NetTCPConnection -LocalPort 8000,8002` |
| Report has no X encode | Phase 3 X stats not implemented yet | expected in Phase 1/2; use `log_x.csv` |
| Pause does not resume | `pause` event with `hold_s`, or panel still paused | resume from the panel; verify `state["test"]["state"]` |
| Delay does not appear | event at/after `duration_s`, or next delay event resets it | check `events` and `state["delay_ms"]` |
| Z freezes after an intra-refresh gap | Z env missing `FYP_X_INTRA_REFRESH=1` | start X and Z with the same value |
| Report `duration_s` > plan duration | wall time includes warm-up + pauses | compare `plan.duration_s` and sample `t` |

## Files

- `common/testplan.py` — plan/event validation, presets, timeline, summary math.
- `common/report.py` — report JSON/CSV, history, safe load.
- `y_gateway.py` — `TestRunner`, dashboard commands, delay/mode timeline,
  Z control queue, X/Y FPS windows, report finalisation.
- `z_client.py` — `FYP_TEST=1`, test commands, input patterns, overlay, stats.
- `tools/test_cli.py` — Phase 1 driver.
- `tools/plans/phase1_smoke.json` — example plan.
- `tests/test_testplan.py`, `tests/test_report.py` — unit tests.


