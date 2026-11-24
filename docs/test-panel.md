# Test Control Panel

Status: **WS2.1 implemented** (`1c20dce`), **WS2.2 implemented**
(`tools/test_panel.py`), **WS2.3 implemented** (X runtime `video`/`stats`/`stop`),
**WS3.1 implemented** (task router + All Cloud), **WS3.2 implemented**
(Offload A/B with the A+B/C split and the state upload) and **WS3.3 implemented**
(All Edge: X idle, L only).
This document is the protocol/report reference; the README has the short
version.

## Purpose

The panel turns a measurement into a **reproducible plan**: choose the test
mode/pattern, duration, warm-up and a timeline of delay/pause/mode/input events,
watch progress, pause or stop the run, and get a report with date/time, RTT,
injected delay, FPS and input→display latency.

## Roles

```
Tk panel (WS2.2) ──WebSocket──► Middle Y (TestRunner)
                                      │  timeline, samples, report
                                      ├──► Cloud X (start/pause/resume/stop; WS2.3: video/stats)
                                      └──► End Z test mode (input patterns, overlay, FPS/decode stats)
```

- **Y** owns the test state machine and writes the report. It already sits
  between Z and X, owns the `DelayLine` and has the dashboard socket.
- **Z** runs with `FYP_TEST=1`: it opens its normal pygame window, connects to
  Y, sends `hello`, and waits for test commands instead of showing the menu.
- **X** is started normally and listens for `video`/`stats`/`stop` from Y, so its
  encoder settings can change without a restart (WS2.3); the `FYP_X_*` values
  are only the startup defaults.

## Test plans

A plan is plain JSON. The full example lives in
`tools/plans/ws2_1_smoke.json`.

```json
{
  "name": "WS1.3-A1 delay sweep",
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
| `placement` | `legacy`, `all_cloud`, `offload_ab`, `all_edge` | WS3.1–WS3.3 task table (all three patterns live) |
| `video_preset` | `current`, `A0`, `A1`, `A2`, `intra` | recorded in WS2.1; applied to X at runtime (WS2.3) |
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
| `x_video` | `{preset}` | WS2.3: `A0`/`A1`/`A2`/`intra` → forward `video` to X |
| `x_stats` | `{on}` | WS2.3: subscribe/unsubscribe X encoder stats |
| `x_stop` | — | WS2.3: stop X stepping/streaming (process stays up) |
| `placement` | `{pattern}` or `{tasks:{...}}` | WS3.1: switch the router table; forwards the X-owned tasks to X |
| `delay_ms` | number | legacy manual slider |

Y → Z (inside the normal data socket, on a control queue ahead of frames):

```json
{"t":"test","cmd":"start","workload":"light","seed":12345,
 "pattern":"strafe","plan":"WS1.3-A1 delay sweep"}
{"t":"test","cmd":"pause"}
{"t":"test","cmd":"resume"}
{"t":"test","cmd":"pattern","pattern":"shoot"}
{"t":"test","cmd":"stop"}
```

Y → X uses the existing `start`/`pause`/`resume`; the X↔Y `DelayLine` carries
the timeline delay events. WS2.3 adds the runtime control channel:

```json
{"t":"video","gop":120,"size":[960,540],"bitrate":4000000,"intra_refresh":false}
{"t":"stats","on":true}
{"t":"stop"}
{"t":"placement","tasks":{"A":"X","B":"X","C":"X","D":"X","E":"X","L":"X"}}
{"t":"state","tick":1234,"seq":77,"keys":"d ","s":{"tick":1234,"bots":[...], ...}}
```

The last one is WS3.2's Offload A/B channel: Y steps A+B and ships its post-A+B snapshot
(`game.snapshot()`, including the `contacts` queue), X restores it, runs C and streams. `in`
keeps its WS1 meaning (A+B+C on X).

X answers `{"t":"video_ok","encoder":"libx264","gop":120,"size":[960,540],
"bitrate":4000000,"intra_refresh":false}` (or `{"t":"error","command":"video",
"message":"..."}` while keeping the previous encoder), pushes
`{"t":"x_stats","fps":60.0,"encode_p50":5.0,"encode_p95":5.6,"keyframes_s":0.5,
"frame_kb":4.3,"frames":120}` at 1 Hz while `stats` is on, and replies
`{"t":"stopped"}`. Y copies `x_stats` into `state["x_stats"]`, `video_ok` into
`state["x_video"]`, and both into the report samples/environment.

The Y state (`state["test"]`) is pushed at 5 Hz:

```json
{"state":"running","name":"WS1.3-A1 delay sweep","warmup_s":5,"duration_s":60,
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
  (thresholds, game config, Y version, video preset/runtime/applied, placement table/applied,
  per-task `task_stats`, Offload A/B `offload`, paused total).
- **events** — applied timeline events with elapsed/wall times.
- **samples** — 5 Hz: `t`, mode, RTT, injected delay, e2e, Z↔Y RTT, X/Y/Z FPS,
  `x_encode`/`x_encode_p95`/`x_kf` (WS2.3), Z decode, tick/score/HP, paused flag.
- **summary** — `n`, mean, p50, p90, p99, max for RTT, delay, e2e, X/Y/Z FPS,
  X encode p50/p95, X keyframes/s, decode; paused samples excluded.

The raw per-frame logs remain in `logs/log_x.csv`, `logs/log_y.csv`,
`logs/log_z.csv`. Historical root logs are archived under `logs/raw/`.

## CLI (WS2.1)

```powershell
$env:FYP_TEST = "1"
.\run_z.cmd <Y_IP>

.\venv\Scripts\python.exe tools\test_cli.py `
    --y ws://<Y_IP>:8002 --plan tools\plans\ws2_1_smoke.json
```

`test_cli.py` prints the plan, progress and final summary, and fetches the
report after the run. Ctrl+C sends `test_stop`.

## WS2.2 — Tk panel

`tools/test_panel.py` (Tk 8.6, stdlib) is the desktop front end for the protocol
above; `tools/panel_model.py` is its headless half (plan building/validation,
timeline rows, progress/metrics formatting, dashboard payloads and message
parsing) and is covered by `tests/test_panel_model.py`.

```powershell
$env:FYP_TEST = "1"
.\run_z.cmd <Y_IP>

.\venv\Scripts\python.exe tools\test_panel.py `
    --y ws://<Y_IP>:8002 --plan tools\plans\ws2_1_smoke.json
```

The panel:

- edits the plan (name, warm-up/duration, seed, workload, mode, video preset,
  placement, input pattern) with Apply/Load/Save and the bundled plans in
  `tools/plans/`;
- edits timeline events (delay/mode/pattern/pause) and previews the timeline as
  ASCII bars, one row per event kind;
- sends `test_start` / `test_pause` / `test_resume` / `test_stop`, shows a
  progress bar, elapsed/remaining and the next event;
- shows live metrics from Y's state push (active tier, RTT both legs, injected
  delay, input→display, X/Y/Z fps, X encode p50/p95, keyframes/s, frame KB,
  placement table, per-task p50 for sim/render/encode, Z decode);
- lists reports from Y, opens one as JSON and exports its samples as CSV;
- launches End Z in test mode (`FYP_TEST=1`, `FYP_Y_IP` from the panel's Y
  address) and focuses the pygame window by its caption;
- links to `web/dashboard.html?ip=<Y_IP>` for remote monitoring.

Notes:

- The panel talks only to Y. It does not connect to X or Z itself.
- A websocket reader thread does the I/O and hands parsed messages to the Tk
  thread through a queue, so no Tk call happens off the main thread.
- The reader reconnects every 2 s while the panel is open; **Disconnect** stops
  it.
- `video_preset` applies at `test_start` and via **Apply video to X** (WS2.3);
  `placement` applies at `test_start` and via **Apply placement** (WS3.1).

## WS2.3 — X runtime video/stats/stop

Implemented in `x_server.py` (+ `common/xstats.py` for the rolling numbers):

- `{"t":"video",...}`: rebuilds the H.264 encoder in a worker thread
  (`asyncio.to_thread`), drops queued frames and forces an IDR. A size change
  (A2) is safe mid-stream because End Z resets its decoder on that keyframe.
  A failed rebuild keeps the previous encoder and returns `error`.
- `{"t":"stats","on":true}`: `x_stats` once per second with `fps`,
  `encode_p50`, `encode_p95`, `keyframes_s`, `frame_kb`, `frames`. Snapshots
  younger than 0.5 s are skipped so a forced IDR right after a swap cannot
  read as 4 keyframes/s.
- `{"t":"stop"}`: stops stepping/streaming but keeps the process and the socket.

Y applies `plan.video_command()` at `test_start`, subscribes to stats, records
`environment.video_runtime`/`video_applied`, and samples `x_encode`,
`x_encode_p95` and `x_kf`. The panel shows X fps, encode p50/p95, keyframes/s,
frame KB and the confirmed preset.

Caveats:

- `intra` has no periodic IDR: End Z must already run with
  `FYP_X_INTRA_REFRESH=1`.
- The preset is applied at the start of a run; a mid-run switch is deliberate
  (panel button / `x_video`) and intended for WS1-style keyframe experiments.

## WS3.1 — task router + All Cloud

`common/placement.py` is the shared model; Y (`y_gateway.py`) is the router and
`x_server.py` accepts `{"t":"placement","tasks":{...}}`.

- Patterns: `legacy` (whole-pipeline), `all_cloud`, `offload_ab`, `all_edge`.
  A plan's `placement` field applies at `test_start`; the live command
  `{"cmd":"placement","pattern":"all_cloud"}` (or `{"tasks":{...}}`) switches it.
- Validation: `L` is pinned to X and a table that moves it is rejected; `U` is
  local to Z and cannot appear in a table; unknown tasks/tiers are rejected.
- X confirms with `placement_ok` (Y stores `state["x_placement"]` and
  `placement_applied: true`) or an `error`. X accepts C/D/E with all-or-neither
  of A/B, and the All Edge table (L only).
- Per-task metrics: Y times `sim` (A+B) and `hit` (C) plus its fallback
  `render`/`encode`, and merges X's `sim_p50`/`hit_p50`/`render_p50`/
  `encode_p50` plus the X↔Y and Z↔Y hops into `state["task_stats"]`, e.g.
```json
{"sim": {"Y": {"n": 120, "p50": 0.06, "p95": 0.08}, "X": {"n": 121, "p50": 0.02}},
 "hit": {"Y": {"n": 120, "p50": 0.01}, "X": {"n": 121, "p50": 0.01}},
 "render": {"X": {"n": 121, "p50": 0.6}},
 "encode": {"X": {"n": 121, "p50": 5.65}},
 "net": {"X": {"n": 1, "p50": 1.98}, "Z": {"n": 1, "p50": 1.9}}}
```

`x_stats.encode_p50` stays "render + encode" (the WS1/WS2 log column) for
comparability; `render_p50`, `sim_p50` and `hit_p50` are the splits.

When `mode: auto`, a non-legacy placement pins rendering to the pattern's D tier
(`render_tier()`), so the RTT fallback cannot move D to Y mid-run and turn an
All Cloud capture into a Y-rendered one.

The report records `environment.placement`, `placement_table`,
`placement_applied`, `task_stats` and (Offload A/B) `offload`, so All Cloud can
be compared with the later patterns.

## WS3.2 — Offload A/B

`Game.step()` is split into `step_ab()` and `step_c()`; `step()` still calls both,
and `tests/test_game_core.py` proves the split is behaviourally identical (600
ticks of medium workload, plus a remote-C tick-for-tick comparison).

- Y steps A+B every tick, ships the post-A+B snapshot as
  `{"t":"state","tick","seq","keys","s"}`, then applies C to its own copy so the
  fallback stays valid. Pending damage found during A/B travels in `s["contacts"]`.
- X restores the snapshot (`restore(state, effects=False)` keeps X's own
  particles), runs C, then renders/encodes D/E as usual.
- `state["offload"]` = `{"n", "bytes", "kb_s", "total"}`; the report stores it in
  `environment.offload`. Medium workload costs ~9 KB per tick (~530 KB/s at
  60 Hz) — that upload is the price of keeping A/B at the edge.
- C runs on **both** tiers (X applies it from the upload, Y applies it locally to
  stay authoritative); the duplication is deliberate and needed for the
  pre-placed fallback copy.

## WS3.3 — All Edge

`placement: all_edge` puts A–E on Y and leaves only **L** on X.

- Y sends the All Edge table; X replies `placement_ok` with `{L: X}`, clears its
  queues, stops streaming and stays idle (`edge_mode`) — a later `start` does
  not wake it.
- Y sends neither `start` nor `in` to X, so there is no frame traffic and no
  state upload (`environment.offload` stays zero).
- Rendering is pinned to Y by `render_tier()`, so Y's fallback encoder streams
  to Z. `FYP_Y_STREAM_EVERY=1` gives 60 fps (default 2 gives 30).
- Y owns the `game_over` event in this pattern and broadcasts it to Z.
- The plan's `video_preset` is inert here: WS2.3's runtime `video` command only
  controls X, and X is idle. Y's encoder is fixed by `FYP_Y_*` at startup.

## Environment

| Variable | Tier | Meaning |
|---|---|---|
| `FYP_TEST=1` | Z | unattended test mode; no menu; waits for Y commands |
| `FYP_GAME_CONFIG` | Z | alternate game config (the immortal test config) |
| `FYP_X_GOP`, `FYP_X_SIZE`, `FYP_X_BITRATE` | X | encoder defaults at startup (WS2.3 can change them at runtime) |
| `FYP_X_INTRA_REFRESH=1` | X and Z | intra-refresh; must match on both |
| `FYP_X_STREAM_EVERY`, `FYP_Y_STREAM_EVERY` | sender and Z | frame stride; must match |
| `FYP_HIGH_MS`, `FYP_LOW_MS`, `FYP_BAD_COUNT`, `FYP_RECOVER_S` | Y | RTT mode-switch thresholds |
| `FYP_Z_INPUT_HZ` | Z | input sample rate (default 120) |

The test config used by the unattended runs should keep the player alive:
`player.max_hp=1000`, `player.obstacle_damage=0`, `player.bot_damage=0`, and a
`light` workload. `tools/autoplay_z.ps1` generates this in
`%TEMP%\fyp_ws1\game_config.json` and can start Z with it.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `test_start` replies “no End Z is connected” | Z not in test mode / not connected | start Z with `FYP_TEST=1`; check Y’s “Z connected” |
| Test pauses immediately / no frames | duplicate Y or Z processes sharing ports | kill all but one Y and one Z; check `Get-NetTCPConnection -LocalPort 8000,8002` |
| Report has no X encode | X not linked, or `stats` never subscribed | WS2.3: the panel subscribes on start; check `x_stats` in Y's state and `X stats: on` in X's log |
| `x_video` replies “Cloud X is not linked” | Y has no X connection (mode Y) | start/reconnect X; presets then apply without restarting X |
| `video_ok` never arrives | encoder rebuild failed | check X's log for `video: encoder rebuild failed`; the previous encoder keeps streaming |
| Placement shows `applied: false` | X rejected the table | All Cloud and Offload A/B are supported; All Edge is not yet (WS3.3) |
| `offload` shows `-` | the run is not using Offload A/B | set `placement: offload_ab`; All Cloud has no state upload |
| `task_stats` empty | no X link, or the run has not started | start a plan with X linked; `sim` comes from Y's tick loop |
| Active tier flips to Y during a placement run | a placement run now pins rendering to its D tier | if it still flips, check `mode` is `auto` and the placement table is non-legacy |
| Pause does not resume | `pause` event with `hold_s`, or panel still paused | resume from the panel; verify `state["test"]["state"]` |
| Delay does not appear | event at/after `duration_s`, or next delay event resets it | check `events` and `state["delay_ms"]` |
| Z freezes after an intra-refresh gap | Z env missing `FYP_X_INTRA_REFRESH=1` | start X and Z with the same value |
| Report `duration_s` > plan duration | wall time includes warm-up + pauses | compare `plan.duration_s` and sample `t` |

## Files

- `common/testplan.py` — plan/event validation, presets, timeline, summary math.
- `common/report.py` — report JSON/CSV, history, safe load.
- `common/xstats.py` — WS2.3 rolling encoder stats (fps, encode p50/p95, keyframes/s).
- `common/placement.py` — WS3.1 task table, patterns, per-task timings.
- `game/simulation.py` — WS3.2 `step_ab()` / `step_c()` split (`step()` = both).
- `x_server.py` — game engine, H.264 renderer and the WS2.3 `video`/`stats`/`stop`
  handlers plus the WS3.1 `placement` acknowledgement.
- `y_gateway.py` — `TestRunner`, dashboard commands, delay/mode timeline,
  Z control queue, X/Y FPS windows, report finalisation, X preset/placement
  forwarding and the task router.
- `z_client.py` — `FYP_TEST=1`, test commands, input patterns, overlay, stats.
- `tools/test_cli.py` — WS2.1 driver.
- `tools/test_panel.py` — WS2.2 Tk panel (Tk + websocket shell).
- `tools/panel_model.py` — WS2.2 headless plan/progress/protocol logic.
- `tools/plans/ws2_1_smoke.json` — example plan.
- `tests/test_testplan.py`, `tests/test_report.py` — unit tests.
- `tests/test_panel_model.py`, `tests/test_panel_smoke.py` — WS2.2 tests.
- `tests/test_xstats.py` — WS2.3 encoder-stats tests.
- `tests/test_placement.py` — WS3.1 placement model tests.


