# 3-Tier Vertical Cloud Gaming Latency Simulator

**Mitigating the main drawback of cloud gaming — latency — with edge computing**

| | |
|---|---|
| **Author** | Andrew Sung |
| **Supervisor** | Noriko Matsumoto |
| **Institution** | Kyushu Sangyo University, Department of Information Science |
| **Programme** | Final Year Project |
| **Academic Year** | 2025/2026 |
| **Status** | Working prototype — Python 3.13.9 on Windows; WS2.1 test runner/CLI shipped; WS1.3 post-fix smoke completed (`20261123-153034`); WS2.2 Tk panel next; task-level placement (WS3) planned |

A final year project modelling a **3-tier vertical cloud gaming architecture** — **End Node (Z) → Middle Edge Gateway (Y) → Cloud Server (X)** — under simulated network latency degradation.

Cloud gaming's main weakness is latency: every frame is rendered far away and must travel to the player, so a degraded cloud link directly hurts responsiveness. This simulator shows how an intermediate **edge** tier mitigates that. While the path to the cloud is healthy, Cloud X runs the game and streams high-quality frames. When the measured round-trip time degrades, Middle Y — which keeps a deterministic copy of the game running at all times — takes over rendering locally at lower quality, cutting the player out of the slow cloud leg. The active tier, the measured RTT, the cloud lag and the end-to-end input→display latency are observable live in a browser dashboard, and the test control panel can run scripted measurement plans.

---

## Architecture

### Baseline (implemented)

```
End Node (Z)  ──►  Middle Edge Gateway (Y)  ──►  Cloud Server (X)
 input sampler       decision proxy /             heavy game-state +
 + latency monitor   local fallback renderer      execution engine
        ◄────────────────  video frames  ────────────────
```

| Tier | Process | Endpoint | Role |
|------|---------|----------|------|
| **Cloud X** | `x_server.py` | `ws://X_IP:8001` | **Baseline:** A–E game engine, 1280×720 H.264 render/stream (JPEG fallback). Planned: pinned L; in Offload/All Edge it may run only C–E or L |
| **Middle Y** | `y_gateway.py` | `ws://Y_IP:8000` (to Z)<br>`ws://Y_IP:8002` (dashboard/test) | **Baseline:** decision proxy, sequencer, full A–E fallback, RTT/dashboard/test runner. Planned: task router/placement table + local A/B copies |
| **End Z** | `z_client.py` | connects to `ws://Y_IP:8000` | **Baseline:** input sampler (120 Hz), latency monitor, display. U (menu/overlay/leaderboard) is local to Z; leaderboard view planned |

Input travels **up** the chain (Z → Y → X) and video travels **down** (X → Y → Z). This is the **whole-pipeline baseline**. The task-level patterns below move individual tasks (A–E) between X and Y, while **U stays on Z** and **L is pinned to X**. Z contains no game logic and no image assets — it only samples input and blits frames. X and Y run the same deterministic runtime core (`game/simulation.py`), which is what makes the fallback seamless. `common/game.py` is the legacy deterministic game kept only as the `selftest.py` cross-tier oracle.

#### Message flow

1. **Input up** — every tick, Z sends JSON `{"keys": "...", "n": <seq>, "e2e": <ms>, "fps": ..., "decode": ...}` to Y.
2. **Sequencing** — Y advances its own copy of the game, then forwards `{"t":"in","tick":<n>,"keys":"...","seq":<n>}` to X. X only steps when `tick == game.tick + 1`; a larger jump triggers `need_snap` and a full state resync.
3. **Frames down** — every frame starts with a source byte: `X`/`Y` = JPEG (`source + struct.pack("!II", tick, seq) + JPEG bytes`), `x`/`y` = H.264 (`source + keyframe byte + struct.pack("!II", tick, seq) + H.264 bytes`). Z advertises support with `{"t":"hello","h264":true}`; Y relays the combined capability to X as `{"t":"caps","h264":…}`, so X uses H.264 only when every connected Z can decode it. On an H.264 tick gap Z waits for a keyframe and sends `want_idr`, which Y relays as `{"t":"need_idr"}` so X emits an IDR.
4. **Telemetry** — Y pings X and pushes dashboard state every 0.2 s. Z measures the **Z↔Y** hop itself: every 6th input (`FYP_Z_PING_EVERY`) carries `{"pts": <clock>}`, Y echoes it, and Z reports both its end-to-end latency and `rzy` in the next input so the dashboard can show both legs separately.
5. **Test control** — a panel connects to Y on 8002, sends `{"cmd":"hello"}`, then `test_start`/`test_pause`/`test_resume`/`test_stop` with a JSON plan. Y runs the timeline, drives Z/X, applies the X↔Y `DelayLine` and writes a report. See [docs/test-panel.md](docs/test-panel.md).

#### Middle Y — decision proxy + local fallback

- **Data path (`tick_loop`)** — while a game is active, Y advances its own game every tick, forwards the input to X and renders a lower-quality fallback while in `EDGE Y`.
- **Monitoring path (`ping_loop`)** — pings X every 0.2 s, smooths the RTT and switches modes with `HIGH_MS`/`LOW_MS`/`BAD_COUNT`/`RECOVER_S`.
- **Delay injection** — the `DelayLine` pair holds every X-facing message by `RTT/2` in each direction. The dashboard slider and the test timeline both use it.
- **Real link loss** — if X disappears, Y switches to `EDGE Y` immediately, re-dials every 2 s and resumes with an IDR when the cloud link returns.

### Task model (A–U)

The archived plan defines these semantic tasks; the count is not fixed — split only if profiling shows a hotspot.

| ID | Task | State | Default placement | Current code |
|----|------|-------|-------------------|--------------|
| **A** | World simulation: movement, spawning, physics, HP, score | Stateful | X (movable) | `game/simulation.py` (waves/HP/score; pathfinding is B) |
| **B** | AI / pathfinding / bot decisions | Needs A state | X (movable candidate) | Simple bot movement/fire in `game/simulation.py`; no pathfinding |
| **C** | Hit registration: bullets vs bots/player/obstacles | Entity state | X (movable) | `game/hitreg.py` |
| **D** | Rendering: world, HP bars, particles | Stateful visual | X (movable) | `game/render.py` |
| **E** | Video encoding: JPEG/H.264 | Stateless per frame | X (movable) | `common/video.py` |
| **L** | Leaderboard / results store | Persistent SQLite | **X pinned** | Not implemented |
| **U** | UI / menu / leaderboard display | Local | **Z (not offloaded)** | `ui/menu.py`, `ui/overlay.py`, `ui/config_menu.py`; leaderboard placeholder |

Dependency graph:

```
Input -> A simulation -> B AI -> C hit registration -> A (HP/score)
                         -> D render -> E encode -> Z
Game over -> L submit/top -> U display
```

Rules:

- **L is pinned to X** — a placement message that tries to move it is rejected and logged.
- **U is local to Z** and never appears in the router table.
- **F–K and M–T are reserved** for future task splits; the semantic task count is not fixed.

### Placement patterns (planned)

The whole-pipeline baseline above stays as the implemented comparison mode. The target is task-level placement, with a placement table on Y and pre-placed local copies (no live code migration in the first version).

| Pattern | X responsibilities | Y responsibilities | Z | Status |
|---|---|---|---|---|
| **All Cloud** | A B C D E L | task router/relay | U | Planned |
| **Offload A/B** | C D E L | A B + router | U | Planned |
| **All Edge** | L | A B C D E + router | U | Planned |
| **Pinned L** | L (pinned) + the A–E pattern | router | U | Rule across patterns |
| **Legacy whole-pipeline** | A–E when healthy; idle in edge | A–E in `EDGE Y` | U | Implemented |

Router / protocol (planned):

- Y holds the placement table (`{"A":"X", ...}`) and dispatches local tasks directly, remote tasks over the existing WebSocket with a timeout.
- L is rejected from any placement that tries to move it; U never appears in the table.
- Messages: `{"t":"placement","tasks":{...}}`, `{"t":"task","id":"A",...}`, `{"t":"task_result",...}`, `{"t":"leaderboard",...}`.
- Per-task compute/network time is logged; the legacy `mode` stays a separate control.

### Pattern axes

| Axis | Values | Current |
|---|---|---|
| **Placement pattern** | All Cloud / Offload A/B / All Edge / Pinned L | Planned (router/table) |
| **Legacy mode** | `auto` / `cloud` / `edge` | Implemented (whole-pipeline fallback) |
| **Video preset** | A0 / A1 / A2 / intra / current | Recorded; runtime in WS2.3 |
| Workload | light / medium / heavy | Implemented |
| Input pattern | idle / strafe / circle / figure8 / shoot | WS2.1 |
| Delay timeline | delay / mode / pause | WS2.1 |

The test plan currently has `mode` (legacy) and `video_preset` (video); the planned placement axis will add `placement`/`pattern` alongside them. The test panel's "pattern" selector is therefore the placement pattern, not A0/A1/A2.

### Implementation status

- **Implemented:** whole-pipeline baseline; A–E game core; U menu/overlay/config (partial); H.264/JPEG; Y fallback; test runner/reports; Z test mode.
- **Partial:** B (no pathfinding); U (leaderboard placeholder); no L.
- **Planned:** Y task router/placement table; local A/B copies; L SQLite on X; leaderboard view; per-task metrics; test-panel placement axis; WS2.2 Tk panel; WS2.3 X runtime video.



---

## Directory Structure

```
FYP/
├── README.md                    # this file
├── requirements.txt             # pinned packages (identical on all 3 machines)
├── .gitignore                   # venv, caches, logs, secrets, IDE files
├── run_local.cmd                # single-PC demo: X, Y and Z on 127.0.0.1
├── run_x.cmd / run_y.cmd / run_z.cmd
├── selftest.py                  # determinism / resync check (run on X and Y)
├── game_config.json             # editable gameplay tuning
├── x_server.py                  # Cloud X — game engine + high-quality renderer
├── y_gateway.py                 # Middle Y — proxy, fallback renderer, RTT, dashboard + test runner
├── z_client.py                  # End Z — menu/test mode, input sampling, frame display
├── AGENTS.md                    # agent workflow, machine table, no-push/pull
├── sync.txt                     # live cross-tier handoff log (root)
├── common/
│   ├── config.py                # env-overridable addresses, ports, codecs, thresholds
│   ├── game.py                  # legacy deterministic core (selftest oracle only)
│   ├── net.py                   # LAN address helper for startup banners
│   ├── report.py                # test report JSON/CSV + history
│   ├── testplan.py              # plan/event validation, timeline, summary math
│   ├── video.py                 # PyAV H.264 encoder/decoder
│   └── win.py                   # 1 ms Windows timer helper
├── game/                        # runtime game core (used by X and Y)
│   ├── entities.py              # player, bot, obstacle, bullet, particle
│   ├── simulation.py            # HP, bullets, bots, waves, snapshot/restore
│   ├── hitreg.py                # spatial grid and damage helpers
│   ├── effects.py               # pooled explosion particles
│   ├── render.py                # world/HP/particle renderer
│   ├── settings.py              # game_config.json loader/validator
│   └── workload.py              # light / medium / heavy profiles
├── ui/                          # Z pygame menus and overlays
│   ├── menu.py
│   ├── config_menu.py
│   └── overlay.py
├── web/
│   └── dashboard.html           # live mode/RTT/lag/game state + latency slider
├── tools/
│   ├── test_cli.py              # WS2.1 test driver
│   ├── autoplay_z.ps1           # immortal config + unattended Z launcher
│   └── plans/
│       ├── ws1_1_a0.json        # WS1.1 baseline (preset A0)
│       ├── ws1_1_a1.json        # WS1.1 baseline (preset A1)
│       ├── ws1_1_a2.json        # WS1.1 baseline (preset A2)
│       ├── ws1_3_a1.json        # WS1.3 post-fix (preset A1)
│       └── ws2_1_smoke.json     # WS2.1 runner smoke
├── tests/
│   ├── test_game_core.py
│   ├── test_testplan.py
│   └── test_report.py
├── docs/
│   ├── test-panel.md            # test protocol, reports, WS2.2/WS2.3 plan (guide)
│   ├── notes/
│   │   ├── .gitkeep
│   │   └── latency-notes.md     # Wi-Fi/DERP findings and threshold calibration
│   ├── guides/
│   │   └── .gitkeep
│   ├── plans/
│   │   └── .gitkeep
│   ├── References/
│   │   ├── commands.md
│   │   ├── context.md
│   │   ├── implementation.md
│   │   ├── placement.md
│   │   ├── plans.md
│   │   ├── research.md
│   │   └── sync.md
│   └── archive/
│       └── GAME_MVP_PLAN.md     # historical milestone plan
├── images/                      # required on X and Y only (Z needs none)
│   ├── background.png
│   ├── bullet.png
│   ├── player.jpg
│   └── rock.png
└── logs/                        # git-ignored runtime data
    ├── .gitkeep
    ├── log_x.csv / log_y.csv / log_z.csv
    ├── reports/                 # test JSON/CSV reports
    └── raw/                     # archived historical logs
```

`venv/`, `__pycache__/`, `*.pyc`, `.env*`, `logs/*` and the generated `log_*.csv` files are excluded from version control — see `.gitignore`.

---

## Prerequisites

### Required on all three machines

- **Python 3.13.9.** X and Y run the same deterministic game, so the interpreter version must match (Python only guarantees `random.random()` — not `randrange` — across versions). Mixing versions can make the `selftest.py` hashes differ.
- **Packages** from `requirements.txt` on every machine:
  - `pygame==2.6.1` — display, input, surface scaling and JPEG decoding on Z
  - `Pillow==11.3.0` — JPEG encoding on X and Y
  - `websockets==15.0.1` — async client/server transport used by all three tiers
  - `av==19.0.2` — PyAV H.264 encoding on X/Y and decoding on Z; without it X/Y fall back to JPEG and Z cannot decode H.264
- **The four image assets** in `images/` — required on **X and Y**; Z does not load them.
- **Windows is recommended but not required.** `common/win.py` calls `timeBeginPeriod(1)` so 60 Hz ticks are not quantised to the default 15.6 ms timer.
- **A browser** on any machine for `web/dashboard.html`.
- **Three machines** on one LAN or reachable through a mesh overlay, with these ports free:

  | Port | Bound by | Purpose |
  |------|----------|---------|
  | `8001` | Cloud X | accepts the WebSocket from Middle Y |
  | `8000` | Middle Y | accepts the WebSocket from End Z |
  | `8002` | Middle Y | dashboard feed / test protocol (plain WebSocket, **not HTTP**) |

- **No full-tunnel VPN while testing.** Tailscale is the supported exception because it routes only the tailnet addresses.

### Network options

| Mode | When to use | Extra software |
|------|-------------|----------------|
| **Single LAN** | X, Y and Z are on the same network | none |
| **Mesh overlay** | X, Y and Z are on different networks | Tailscale (ZeroTier/NetBird work the same way) |

---

## Before You Start — Record Your Addresses

| Value | How to find it | Your value |
|-------|----------------|------------|
| `<X_LAN_IP>` | `ipconfig` on Cloud X | |
| `<Y_LAN_IP>` | `ipconfig` on Middle Y | |
| `<Z_LAN_IP>` | `ipconfig` on End Z | |
| `<X_TAILNET_NAME>` | `tailscale status` on Cloud X | |
| `<Y_TAILNET_NAME>` | `tailscale status` on Middle Y | |
| `<Z_TAILNET_NAME>` | `tailscale status` on End Z | |
| `<X_TAILNET_IP>` | `tailscale ip -4` on Cloud X | |
| `<Y_TAILNET_IP>` | `tailscale ip -4` on Middle Y | |
| `<Z_TAILNET_IP>` | `tailscale ip -4` on End Z | |

Then derive the addresses the commands need:

| Placeholder | Use this value |
|-------------|----------------|
| `<X_ADDRESS>` | X LAN IP on a same-LAN run; X tailnet name or tailnet IP over Tailscale |
| `<Y_ADDRESS>` | Y LAN IP on a same-LAN run; Y tailnet name or tailnet IP over Tailscale |
| `<Y_DASHBOARD_ADDRESS>` | `127.0.0.1` when the browser runs on Y; otherwise `<Y_ADDRESS>` |

On macOS/Linux use `ip addr` or `ifconfig` instead of `ipconfig`. If MagicDNS is disabled, use the `100.x` address from `tailscale ip -4`.

Each tier only dials the peer named in its launcher:

| Tier | Dials | Variable |
|------|-------|----------|
| Middle Y | Cloud X | `FYP_X_IP` = `<X_ADDRESS>` |
| End Z | Middle Y | `FYP_Y_IP` = `<Y_ADDRESS>` |

`common/config.py` is the same file everywhere; the `run_*.cmd` launchers set those variables.

---

## Start the System

### Firewall (once per machine)

On **Cloud X**, in an admin PowerShell:

```powershell
New-NetFirewallRule -DisplayName "FYP Cloud X 8001" -Direction Inbound `
    -Protocol TCP -LocalPort 8001 -Action Allow -Profile Private
```

On **Middle Y**:

```powershell
New-NetFirewallRule -DisplayName "FYP Edge Y 8000 8002" -Direction Inbound `
    -Protocol TCP -LocalPort 8000,8002 -Action Allow -Profile Private
```

If `Get-NetConnectionProfile` reports `Public`, run
`Set-NetConnectionProfile -InterfaceAlias "<name>" -NetworkCategory Private`.
The Tailscale adapter is normally Private. If your rule is Private-only and the active adapter
is Public, either change the category or create the rule with `-Profile Any` (Administrator).

### Start the tiers — in this order

Run from the repository root so the `common` package imports correctly and the CSV logs land in `logs/`.

```powershell
.\run_x.cmd
.\run_y.cmd <X_LAN_IP>            # Middle Y -> "connected to X at ws://..."
.\run_z.cmd <Y_LAN_IP>            # End Z     -> opens the 1280x720 menu
```

End Z starts with a local menu: VS Bot, workload selection (light/medium/heavy), disabled
Leaderboard/Multiplayer placeholders and Exit. Click **VS BOT** or press Enter/Space to start a
match. In game, `Esc` opens the pause overlay (Resume/Retry/Main Menu); `Esc`/`R` resumes,
`T` retries, `M` returns to the menu. Player death opens a game-over screen. The menu works even
when X/Y are down.

#### Tailscale / different networks

Run `tailscale up` once on each machine and confirm the peers are visible before starting. Then
use the tailnet names or `100.x` addresses:

```powershell
.\run_x.cmd
.\run_y.cmd <X_TAILNET_NAME>      # or <X_TAILNET_IP>
.\run_z.cmd <Y_TAILNET_NAME>      # or <Y_TAILNET_IP>
```

X and Y reconnect automatically, so the order is not critical; starting X first avoids an initial
`X link down` message. If `tailscale ping <peer>` reports `via DERP`, expect a higher baseline RTT
and tune the thresholds (see [Configuration](#configuration)).

### Single-machine demo

Easiest: run `.\run_local.cmd`, which opens X, Y and Z on `127.0.0.1` (and stops stale FYP
processes first). Or start the three tiers manually as `.\run_x.cmd`,
`.\run_y.cmd 127.0.0.1`, `.\run_z.cmd 127.0.0.1`.

For an unattended test run, also set `FYP_TEST=1` before starting Z (the game window stays
open; the window shows `TEST READY` and waits for Y’s test commands).

---

## Open the Dashboard

`web/dashboard.html` is a static page that opens a WebSocket to Y on port `8002`. Y does not
serve the page, and **`8002` is not an HTTP page** — do not browse to `http://<Y_ADDRESS>:8002`.
Open the file instead.

**Prerequisite:** Y must be running and listening:

```powershell
Get-NetTCPConnection -LocalPort 8002 -State Listen
```

### Method 1 — double-click

Open `web/dashboard.html`; when prompted, enter Y's address:

| Browser runs on | Enter |
|-----------------|-------|
| the same machine as Y | `127.0.0.1` |
| another LAN machine | `<Y_LAN_IP>` |
| another Tailscale machine | `<Y_TAILNET_NAME>` or `<Y_TAILNET_IP>` |

### Method 2 — URL with the `?ip=` query parameter

```text
web/dashboard.html?ip=<Y_DASHBOARD_ADDRESS>
```

When opening from disk, the query must be part of the file URL:

```text
file:///C:/path/to/FYP/web/dashboard.html?ip=127.0.0.1
```

### Method 3 — local HTTP server

From the repository root:

```powershell
.\venv\Scripts\python.exe -m http.server 8080
```

Then open:

```text
http://localhost:8080/web/dashboard.html?ip=127.0.0.1
```

Replace `127.0.0.1` with `<Y_LAN_IP>` or `<Y_TAILNET_NAME>` when the browser is on another
machine. Stop the server with `Ctrl+C` when done.

### What the Dashboard Shows

- **Active node** — `CLOUD X` (green) or `EDGE Y` (orange), updated every 0.2 s.
- **RTT X↔Y** — the smoothed round-trip time Y measures with its ping/pong loop (the cloud leg).
- **RTT Z↔Y** — measured by End Z and reported back to Y (the last-mile leg).
- **X lag** — how many ticks ahead Y's local simulation is compared with the newest X frame.
- **input→display (Z)** — end-to-end latency reported by End Z.
- **Cloud X link** — `up`/`DOWN`, whether Y currently holds a WebSocket to X.
- **dashboard** — whether the browser is connected to Y (it retries every second).
- **Injected X↔Y latency (RTT)** — a 0–400 ms slider (the same `DelayLine` used by test plans).

### Latency Injection

Moving the slider sends `{"delay_ms": value}` to Y, which sets both `DelayLine` instances to
`value / 2000` seconds — half the RTT per direction:

- **uplink** — every message Y sends to X (inputs, pings) is held for that delay;
- **downlink** — every message X sends to Y (pongs, snapshots, frames) is held for that delay.

Increase the slider past `HIGH_MS` and, after `BAD_COUNT` consecutive samples, Y switches to
`EDGE Y`; bring it below `LOW_MS` for `RECOVER_S` and the mode returns to `CLOUD X`. A real link
failure is handled too: if the X connection drops, Y switches to `EDGE Y` immediately and keeps
the game running; it re-dials X every 2 s and returns to `CLOUD X` once the RTT is healthy.
Because X asks for a snapshot on every connection, the game state continues instead of restarting.

---

## Test Control Panel

### WS2.1 — implemented

Y accepts a test protocol on the dashboard WebSocket (8002). A plan selects the workload, legacy
mode (`auto`/`cloud`/`edge`), X video preset (recorded now; applied at runtime in WS2.3), Z input
pattern (`idle`/`strafe`/`circle`/`figure8`/`shoot`), warm-up/measurement duration and a timeline
of events (`delay`, `mode`, `pause`, `pattern`). The **placement pattern** (All Cloud / Offload
A/B / All Edge / Pinned L) is a separate planned axis for the task router; until it exists,
`mode` only controls the legacy whole-pipeline fallback.

```powershell
# Cloud X and Middle Y run normally. Start Z in test mode:
$env:FYP_TEST = "1"
.\run_z.cmd <Y_ADDRESS>

# Drive a plan through Y:
.\venv\Scripts\python.exe tools\test_cli.py `
    --y ws://<Y_DASHBOARD_ADDRESS>:8002 --plan tools\plans\ws2_1_smoke.json
```

For unattended runs the match must be unable to end. The test config keeps the player alive
(`player.max_hp=1000`, zero obstacle/bot damage, `light` workload); point Z at it with
`FYP_GAME_CONFIG` (or let `tools\autoplay_z.ps1` generate it under `%TEMP%\fyp_ws1`).

Y writes `logs/reports/<id>.json` and `.csv`: date/time, plan, environment, applied events,
5 Hz samples (mode, RTT, injected delay, e2e, X/Y/Z FPS, decode/encode when available) and
p50/p90/p99/max summaries. Paused samples are excluded from the summaries. The CLI prints the
summary when the run finishes; the raw per-frame logs remain in `logs/log_x/y/z.csv`.

WS2.1 command reference and the report schema: [docs/test-panel.md](docs/test-panel.md).

### WS2.2 / WS2.3

- **WS2.2** — `tools/test_panel.py` (Tk 8.6, stdlib): plan/preset editor, workload/mode/input/
  video selectors, placement-pattern selector (once the task router lands), timeline, progress,
  Start/Pause/Resume/Terminate, live metrics, report history, and launch/focus of the Z pygame
  window. The browser dashboard stays available as a remote monitor.
- **WS2.3** — X runtime `video` command (GOP/resolution/bitrate/intra-refresh with encoder
  rebuild + IDR), X `stats` (fps/encode/keyframes) and X `stop`. The panel’s A0/A1/A2/intra
  presets then apply without restarting X. Until then X uses its startup `FYP_X_*` values and
  the report records `video_runtime: current`.

---

## Configuration

### Gameplay configuration

Gameplay values live in `game_config.json` and are loaded by `game/settings.py`. Start Z and press
**C** (or click **GAME CONFIG**) to open the visual editor. Changes are saved immediately, shown
on the dashboard, and applied on the next game start.

The editor groups settings by **World**, **Player**, **Bot**, **Obstacle**, **Effects** and the
selected **Profile**. Use Up/Down to select, Left/Right to change (Shift = 5x), 1/2/3 to edit a
workload profile, `S` to save, `R` to reload, `D` to make the current profile the default, and Esc
to return. Out-of-range values are clamped; missing values fall back to defaults. The `start`
message carries the config to Y and X, so all three tiers use the same values.

### Network and streaming configuration

Network and streaming tunables live in `common/config.py`:

| Constant | Env var | Default | Meaning |
|----------|---------|---------|---------|
| `X_HOST` | `FYP_X_HOST` | `0.0.0.0` | interface Cloud X binds |
| `Y_HOST` | `FYP_Y_HOST` | `0.0.0.0` | interface Middle Y binds |
| `X_IP` | `FYP_X_IP` | `127.0.0.1` | address Middle Y dials (Cloud X) |
| `Y_IP` | `FYP_Y_IP` | `127.0.0.1` | address End Z and the dashboard dial (Middle Y) |
| `X_PORT` | `FYP_X_PORT` | `8001` | port Cloud X listens on for Y |
| `Y_PORT_Z` | `FYP_Y_PORT_Z` | `8000` | port Middle Y listens on for Z |
| `Y_PORT_DASH` | `FYP_Y_PORT_DASH` | `8002` | dashboard/test port on Middle Y |
| `PING_INTERVAL`, `PING_TIMEOUT` | `FYP_PING_INTERVAL`, `FYP_PING_TIMEOUT` | `15`, `15` | WebSocket keepalive (s) |
| `RECONNECT_S` | — | `2.0` | wait before re-dialling a lost peer |
| `TICK_RATE` | — | `60` | simulation ticks per second |
| `X_STREAM_EVERY` | `FYP_X_STREAM_EVERY` | `1` | X renders every Nth tick (1 → 60 fps). **Z must match** |
| `Y_STREAM_EVERY` | `FYP_Y_STREAM_EVERY` | `2` | Y renders every Nth tick (30 fps). **Z must match** |
| `WIN_W`, `WIN_H` | `FYP_WIN_SIZE` | `1280x720` | window size on Z |
| `X_SIZE` | `FYP_X_SIZE` | `1280x720` | Cloud X capture size |
| `X_QUALITY` | `FYP_X_QUALITY` | `80` | Cloud X JPEG quality |
| `X_CODEC`, `X_ENCODER` | `FYP_X_CODEC`, `FYP_X_ENCODER` | `h264`, `libx264` | stream codec and encoder |
| `X_BITRATE` | `FYP_X_BITRATE` | `4000000` | target H.264 bitrate (4 Mbps) |
| `X_GOP` | `FYP_X_GOP` | `120` | keyframe interval; scene-cut IDRs disabled |
| `X_INTRA_REFRESH` | `FYP_X_INTRA_REFRESH` | off | no periodic IDR; **set the same value on Z** |
| `Y_SIZE` | `FYP_Y_SIZE` | `960x540` | Edge Y capture size |
| `Y_QUALITY` | `FYP_Y_QUALITY` | `55` | Edge Y JPEG quality |
| `Y_CODEC`, `Y_ENCODER` | `FYP_Y_CODEC`, `FYP_Y_ENCODER` | `h264`, `libx264` | fallback stream codec/encoder |
| `Y_BITRATE` | `FYP_Y_BITRATE` | `2000000` | Edge H.264 bitrate |
| `Y_GOP` | `FYP_Y_GOP` | `10` | Edge keyframe interval |
| `HIGH_MS` | `FYP_HIGH_MS` | `80` | RTT above which a sample is “bad” (X → Y) |
| `LOW_MS` | `FYP_LOW_MS` | `50` | RTT below which recovery can begin (Y → X) |
| `BAD_COUNT` | `FYP_BAD_COUNT` | `3` | consecutive bad samples before switching to Y |
| `RECOVER_S` | `FYP_RECOVER_S` | `3.0` | seconds below `LOW_MS` before returning to X |
| `Z_INPUT_HZ` | `FYP_Z_INPUT_HZ` | `120` | Z input sampling rate |
| `Z_PING_EVERY` | `FYP_Z_PING_EVERY` | `6` | every Nth input carries a Z↔Y probe |
| — | `FYP_TEST` | unset | Z test mode (`1`); waits for Y commands |
| — | `FYP_GAME_CONFIG` | unset | path to an alternate game config (test immortality) |

### Tune for your network

`HIGH_MS`/`LOW_MS` are calibrated for a healthy LAN (sub-millisecond RTT), where the mode changes
only when the slider injects delay. **Every deployment has a different baseline**, so measure it
before a run:

1. Start X and Y with the dashboard slider at `0`.
2. Watch `rtt_ms` on the dashboard or in `logs/log_y.csv` for ~30 s.
3. Set thresholds above that baseline:

   ```powershell
   $env:FYP_HIGH_MS   = "<baseline + 35>"
   $env:FYP_LOW_MS    = "<baseline + 15>"
   $env:FYP_RECOVER_S = "3.0"
   ```

   Use the same values on every run so results are comparable.

On a LAN the baseline is typically 1–5 ms. On Tailscale it may be 20–80 ms; if
`tailscale ping <peer>` reports `via DERP`, expect the higher end and set both thresholds above it.
Otherwise Y may sit in fallback permanently or flap. The same applies to
`FYP_BAD_COUNT` (require a longer bad streak on a noisy link).

---

## Output & Logs

All three tiers write into **`logs/`** (git-ignored except `.gitkeep`); files are truncated on each
start. `logs/reports/` holds test reports; `logs/raw/` holds archived historical logs.

`logs/log_x.csv` — written by Cloud X for every rendered frame:

| Column | Meaning |
|--------|---------|
| `unix_time` | wall-clock timestamp of the render |
| `tick` | game tick in the frame header |
| `seq` | input sequence in the frame header |
| `codec` | `h264` or `jpeg` |
| `key` | `1` for an IDR/keyframe |
| `encode_ms` | render + encode time |
| `frame_bytes` | encoded payload size |

`logs/log_y.csv` — written by Middle Y every 0.2 s:

| Column | Meaning |
|--------|---------|
| `unix_time` | wall-clock timestamp |
| `mode` | active tier (`X` or `Y`) |
| `rtt_ms` | smoothed X↔Y RTT |
| `injected_delay_ms` | current injected X↔Y delay |
| `e2e_ms_from_Z` | last input→display latency reported by Z |
| `rtt_zy_ms_from_Z` | Z↔Y RTT reported by Z |
| `x_link` | `1` while the WebSocket to X is up |

`logs/log_z.csv` — written by End Z for every displayed frame matching an input:

| Column | Meaning |
|--------|---------|
| `unix_time` | wall-clock timestamp of display |
| `source` | tier that produced the frame (`X`/`Y`) |
| `codec` | `h264` or `jpeg` |
| `tick` | game tick carried in the frame header |
| `first` | `1` for the first frame for this input seq |
| `e2e_ms` | input→display latency |
| `decode_ms` | decode time (H.264, off the event loop) |
| `rtt_zy_ms` | current Z↔Y RTT |

Use only `first=1` rows for latency statistics; repeats for the same input would inflate p50. The
`e2e_ms` sent to Y and shown on the dashboard is updated only on `first=1` frames. Y flushes on
every sample; Z flushes every 30 frames.

Test reports (`logs/reports/<id>.json` + `.csv`) contain the plan, environment, events, 5 Hz
samples and the p50/p90/p99/max summary; see [docs/test-panel.md](docs/test-panel.md).

---

## Verification

### Determinism / resync

Run on **both** Cloud X and Middle Y:

```powershell
.\venv\Scripts\python.exe selftest.py
```

It plays a fixed 3000-tick script, performs a JSON round-trip and restore on a differently-seeded
instance, and prints:

```
host: <machine> | <OS build>
python <ver> | pygame <ver> | pillow <ver> | websockets <ver>
ticks 3000 score <n> deaths <n> hash <md5>
resync OK
render bytes: <X bytes> (X) <Y bytes> (Y)
```

The **hash must be identical on both machines** and `resync OK` must be printed. Compare the
version lines too: a different Python version is the most likely reason for a mismatch.

### Unit tests

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Covers the game core, config clamping, snapshot/restore determinism, test-plan validation/timeline
and report writing.

### Test runner

```powershell
.\venv\Scripts\python.exe tools\test_cli.py `
    --y ws://127.0.0.1:8002 --plan tools\plans\ws2_1_smoke.json
```

### X capacity check

Start X alone, play for a minute, then inspect `logs/log_x.csv`: `encode_ms` is render+encode,
`frame_bytes` the encoded size, and `key` marks IDRs. On the reference machine (libx264 ultrafast,
GOP 120, VBV) render+encode is **~5–6 ms** at 720p/60, average bitrate **~3–4 Mbps**, and
keyframes are **~100–120 KB**.

A keyframe must fit the uplink's burst budget: 120 KB at 20 Mbps is ~48 ms, which is the periodic
hitch. GOP 120 makes those bursts rare (0.5/s); `FYP_X_INTRA_REFRESH=1` on X and Z removes them
entirely (max frame ~20–50 KB).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `X link down (ConnectionRefusedError ...)` on Y | X not running, wrong `FYP_X_IP`, wrong port, or firewall | Start X; `Test-NetConnection <X_ADDRESS> -Port 8001` from Y; add the inbound rule |
| Z shows `reconnecting to Y ...` | Y not running or port 8000 blocked | Start Y; `Test-NetConnection <Y_ADDRESS> -Port 8000` from Z |
| Dashboard says `disconnected - retrying` | Wrong address in `?ip=`, or port 8002 blocked | Re-open with `web/dashboard.html?ip=<Y_DASHBOARD_ADDRESS>`; check the Y firewall rule |
| Dashboard opens but stays `connecting` | Y not running, wrong address, or 8002 blocked | Run `Get-NetTCPConnection -LocalPort 8002 -State Listen` on Y; retry with `?ip=127.0.0.1` |
| `selftest.py` hashes differ | Different Python versions on X and Y (most likely), or a modified `common/game.py` | Install the same 3.13.x and the pinned `requirements.txt` on both, then re-run |
| Mode never switches when the slider moves | Slider on a dashboard attached to a different Y, or X link is down | Check the dashboard's `Cloud X link` field; edit `HIGH_MS`/`LOW_MS` only for a high real baseline |
| The startup banner shows a `10.x` address | A full-tunnel VPN owns the default route | Quit the full-tunnel VPN, then restart the tier. A `100.x` address is normal when Tailscale is connected. |
| `OSError: [WinError 10048]` (port in use) | Another instance or another app holds the port | `Get-NetTCPConnection -LocalPort 8001 -State Listen`, stop that process |
| **Two Ys or two Zs are running** | Duplicate launchers (or stale processes) share the dashboard/game state | `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` → kill all but **one** Y and **one** Z; `run_local.cmd` also clears stale FYP processes |
| Z window never appears, but the terminal is running | `SDL_VIDEODRIVER=dummy` inherited from a test shell, or an old X/Y holds the ports | Re-run `run_local.cmd`; for a manual Z start, `set SDL_VIDEODRIVER=` first |
| Frame rate drops, `encode_ms` above ~16 ms in `logs/log_x.csv` | X render+encode is the bottleneck | Set `X_STREAM_EVERY=2` (30 fps) **on X and Z**, or lower `X_SIZE`/`X_QUALITY` |
| Z shows ~3 fps or only keyframes in `EDGE Y` | `FYP_Y_STREAM_EVERY` differs between Y and Z | Use the same `FYP_Y_STREAM_EVERY` (and `FYP_X_STREAM_EVERY`) on the sender and Z |
| Periodic 50 fps hitch / latency spike every ~2 s | A 100–120 KB keyframe burst exceeds the uplink budget | Keep GOP 120 + VBV, try `FYP_X_SIZE=960x540`, or `FYP_X_INTRA_REFRESH=1` on **X and Z** |
| Intra-refresh: Z freezes after a gap | Z is not started with `FYP_X_INTRA_REFRESH=1` | Restart Z with the same value as X |
| Many X↔Y switches with a ~30 ms baseline | Default 80/50 thresholds are too tight for a WAN | Calibrate `FYP_HIGH_MS` ≈ p50 + 35, `FYP_LOW_MS` ≈ p50 + 15, raise `FYP_BAD_COUNT` |
| `test_start` replies “no End Z is connected” | Z not in test mode / not connected | Start Z with `FYP_TEST=1`; check Y’s `Z connected` |
| Test pauses immediately / no frames | Duplicate Y/Z processes or a paused runner | Kill duplicates; check `state["test"]["state"]`; resume from the panel |
| Report has no X encode | WS2.3 X `stats` not implemented yet | Expected in WS2.1/2.2; use `logs/log_x.csv` |
| Report `duration_s` > plan duration | Wall time includes warm-up and pauses | Compare `plan.duration_s` with sample `t` |

Keep the machines awake for the demo (`powercfg /change standby-timeout-ac 0`) and, if you merge
`logs/log_y.csv` with `logs/log_z.csv` by `unix_time`, synchronise the clocks (`w32tm /resync`).
The `rtt_ms` and `e2e_ms` columns are measured inside one process and do not depend on clock sync.

---

## Known Limitations

- **TCP transport.** All traffic is WebSocket over TCP. The simulator models *constant* one-way
  delay only — there is no packet loss, reordering or jitter, and a stalled TCP segment stalls
  every later frame (head-of-line blocking). A production cloud-gaming stack would use UDP/WebRTC.
- **Measured RTT includes X's own processing.** Pongs are answered from the same loop that renders
  frames, so a busy X inflates `rtt_ms`. This is realistic “cloud lag”, but it is not network-only.
- **Lock-step replay.** X advances only on inputs forwarded by Y, so in `CLOUD X` mode the frame Z
  displays corresponds to a state roughly one RTT old. Switching back from `EDGE Y` can therefore
  show a brief rewind.
- **Injection point.** The dashboard slider and the test timeline delay only the X↔Y leg — exactly
  the cloud leg the edge tier is meant to hide; the Z↔Y hop is untouched.
- **One game, one input.** Multiple Z clients can watch, but they share a single input state and
  there is one game instance per Y.
- **Fixed encoding settings until WS2.3.** X and Y use H.264 at a fixed target bitrate/GOP with
  JPEG fallback; there is no adaptive bitrate or congestion control. X uses a VBV buffer (0.5 s),
  no scene-cut IDRs, and optionally intra-refresh. A dropped frame is repaired by the next
  keyframe, or sooner when Z requests an IDR. The WS2.3 panel will switch GOP/resolution/
  intra-refresh at runtime.
- **Task-level placement not implemented.** The current X/Y behaviour is the whole-pipeline
  baseline; the task router, placement table, local A/B copies and pinned L are planned. `mode`
  is the legacy fallback; the test panel’s placement-pattern axis is future work.
- **Leaderboard / U partial.** The menu, overlays and config editor exist; the leaderboard display
  is a placeholder and L (SQLite on X) is not implemented.
- **Test panel UI.** WS2.1 is the protocol/CLI; the Tk panel is WS2.2, so progress and report
  access are currently terminal-based.
- **WS1.1 archive (historical).** A0/A1/A2 (GOP30 vs GOP120 vs 540p on the old X) are only reproducible with
  the old `4f189b9` code. The current lab X is at `cda0f52` (WS1.2); WS1.3 post-fix verification is pending.
  The `logs/raw/phaseA_*` folder names are historical; `docs/References/roadmap.md` maps them.

---

## Documentation

- [docs/test-panel.md](docs/test-panel.md) — test protocol, plan/report schema, WS2.2/WS2.3 plan.
- [docs/References/roadmap.md](docs/References/roadmap.md) — workstreams, schedule, current progress and next step.
- [docs/notes/latency-notes.md](docs/notes/latency-notes.md) — Wi-Fi/client-isolation/DERP findings and threshold calibration.
- [docs/References/context.md](docs/References/context.md) — topology, machines, current status.
- [docs/References/commands.md](docs/References/commands.md) — setup/run/test commands.
- [docs/References/placement.md](docs/References/placement.md) — folder rules and root-file policy.
- [docs/References/research.md](docs/References/research.md) — research/citation rules.
- [docs/References/plans.md](docs/References/plans.md) — plan template.
- [docs/References/sync.md](docs/References/sync.md) — sync entry format.
- [docs/References/implementation.md](docs/References/implementation.md) — implementation rules.
- [docs/archive/GAME_MVP_PLAN.md](docs/archive/GAME_MVP_PLAN.md) — historical milestone plan.
- `AGENTS.md` — agent workflow, current machine assignment, no-push/pull.
- `sync.txt` — live cross-tier handoff log (root; updated by the machines).

---

## License

Academic research project — provided as-is for educational use.







