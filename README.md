# 3-Tier Vertical Cloud Gaming Latency Simulator

**Mitigating the main drawback of cloud gaming — latency — with edge computing**

| | |
|---|---|
| **Author** | Andrew Sung |
| **Supervisor** | Noriko Matsumoto |
| **Institution** | Kyushu Sangyou Unisersity Department of Information Science|
| **Programme** | Final Year Project |
| **Academic Year** | [2025/2026] |
| **Status** | Working prototype — tested with Python 3.13.9 on Windows, 3 machines on one LAN |

A final year project modelling a **3-tier vertical cloud gaming architecture** — **End Node (Z) → Middle Edge Gateway (Y) → Cloud Server (X)** — under simulated network latency degradation.

Cloud gaming's main weakness is latency: every frame is rendered far away and must travel to the player, so a degraded cloud link directly hurts responsiveness. This simulator shows how an intermediate **edge** tier mitigates that. While the path to the cloud is healthy, Cloud X runs the game and streams high-quality frames. When the measured round-trip time degrades, Middle Y — which keeps a deterministic copy of the game running at all times — takes over rendering locally at lower quality, cutting the player out of the slow cloud leg. The active tier, the measured RTT, the cloud lag and the end-to-end input→display latency are all observable live in a browser dashboard.

---

## Architecture

```
End Node (Z)  ──►  Middle Edge Gateway (Y)  ──►  Cloud Server (X)
 input sampler       decision proxy /             heavy game-state +
 + latency monitor   local fallback renderer      execution engine
        ◄────────────────  video frames  ────────────────
```

| Tier | Process | Endpoint | Role |
|------|---------|----------|------|
| **Cloud X** | `x_server.py` | `ws://X_IP:8001` | Authoritative game-state execution engine; renders 960×540 JPEG at quality 80 |
| **Middle Y** | `y_gateway.py` | `ws://Y_IP:8000` (to Z)<br>`ws://Y_IP:8002` (dashboard) | Decision proxy + sequencer, local fallback renderer, RTT monitor, dashboard backend |
| **End Z** | `z_client.py` | connects to `ws://Y_IP:8000` | User input sampler (60 Hz), latency monitor, displays received footage |

Input travels **up** the chain (Z → Y → X) and video travels **down** (X → Y → Z). Z contains no game logic and no image assets — it only samples the keyboard and blits frames. Both X and Y import the same `common/game.py`, which is what makes the fallback seamless.

### Message flow

1. **Input up** — every tick, Z sends JSON `{"keys": "...", "n": <seq>, "e2e": <ms>}` to Y.
2. **Sequencing** — Y advances its own copy of the game, then forwards `{"t":"in","tick":<n>,"keys":"...","seq":<n>}` to X. X only steps when `tick == game.tick + 1`; a larger jump triggers `need_snap` and a full state resync.
3. **Frames down** — a frame is `1 byte source ('X' or 'Y') + struct.pack("!II", tick, seq) + JPEG bytes`. X and Y use the same layout, so Z needs no knowledge of which tier rendered it.
4. **Telemetry** — Y pings X and pushes dashboard state every 0.2 s; Z reports its latest end-to-end latency in the next input message.

### Middle Y — decision proxy + local fallback

Middle Y separates the **data path** from the **monitoring path** so the game never waits on measurement:

- **Data path (`tick_loop`):** Y advances its own copy of the game every tick (60 Hz), forwards the input to Cloud X with a sequence number, and — only while in `Y` mode — renders and broadcasts a 480×270 quality-40 frame every second tick (30 fps).
- **Monitoring path (`ping_loop`):** every 0.2 s Y sends `{"t":"ping"}` to X; X replies with a `pong` carrying the original timestamp, giving the Y↔X RTT. The value is smoothed with an EWMA (`0.7 × old + 0.3 × new`).
- **State machine (`update_mode`):** X → Y after **3 consecutive** RTT samples above **80 ms**; Y → X only after RTT has stayed below **50 ms** for **3 s**. The asymmetric thresholds and the recovery timer provide hysteresis, so the mode does not flap around a single threshold.
- **Frame fan-out (`broadcast` / `z_sender`):** each connected Z holds a single "latest frame" slot. New frames overwrite unsent ones, so a slow client never builds a backlog — it simply receives the newest frame.

### Deterministic lock-step and resync

For a fallback node to take over mid-game, both X and Y must hold identical state:

- `common/game.py` is a headless, deterministic port of the original game: all randomness comes from a **privately seeded RNG**, and input is passed in as a key string rather than read from a keyboard.
- The original ran at 240 fps; here each 60 Hz tick performs `SUBSTEPS = 4` original frames, so game behaviour matches the original while the network only carries 60 updates per second.
- `Game.snapshot()` serialises tick, score, deaths, player, rocks, bullets **and the RNG state**; `Game.restore()` rebuilds it. If X detects a gap (`m["tick"] > game.tick + 1`) it sends `need_snap`, Y replies with a full snapshot, and both sides converge again.
- `selftest.py` proves this: the same input script run on X and on Y must produce an identical MD5 digest, including after a JSON round-trip and restore on a differently-seeded instance.

---

## Directory Structure

```
FYP/
├── .gitignore                   # venv, Python caches, logs, secrets, IDE files
├── README.md                    # this file
├── requirements.txt             # pinned packages (identical on all 3 machines)
├── run_x.cmd                    # Cloud X launcher (activates venv, sets FYP_* vars)
├── run_y.cmd                    # Middle Y launcher (<Cloud X address>)
├── run_z.cmd                    # End Z launcher (<Middle Y address>)
├── venv/                        # local virtual environment (git-ignored)
├── x_server.py                  # Cloud X — game engine + high-quality renderer
├── y_gateway.py                 # Middle Y — proxy, fallback renderer, RTT monitor, dashboard
├── z_client.py                  # End Z — input sampling + frame display
├── selftest.py                  # determinism / resync check (run on X and Y)
├── dashboard.html               # live mode, RTT, lag and latency-injection dashboard
├── log_x.csv                    # generated by X at runtime: render cost + frame size (git-ignored)
├── log_y.csv                    # generated by Y at runtime (git-ignored)
├── log_z.csv                    # generated by Z at runtime (git-ignored)
├── common/                      # shared by X and Y
│   ├── __init__.py
│   ├── config.py                # env-overridable addresses, ports, tick rate, thresholds
│   ├── game.py                  # deterministic game logic + JPEG renderer
│   ├── net.py                   # LAN address helper used by the startup banners
│   └── win.py                   # 1 ms Windows timer helper
└── images/                      # required on X and Y only (Z does not need them)
    ├── background.png
    ├── bullet.png
    ├── player.jpg
    └── rock.png
```

`venv/`, `__pycache__/`, `*.pyc`, `.env*` and the generated `log_*.csv` files are excluded from version control — see `.gitignore`.

---

## Prerequisites

- **Python 3.13.9 on all three machines.** X and Y run the same deterministic game, so the
  interpreter version must match (Python only guarantees `random.random()` — not `randrange` —
  across versions). Mixing 3.10 and 3.13 can make the `selftest.py` hashes differ.
- **Python packages**, pinned in `requirements.txt` and installed on every machine:
  - `pygame==2.6.1` — display, input, surface scaling and JPEG decoding on Z
  - `Pillow==11.3.0` — JPEG encoding on X and Y
  - `websockets==15.0.1` — the async client/server transport used by all three tiers
- **The four image assets** in `images/` — `background.png`, `bullet.png`, `player.jpg`, `rock.png`. Required on **X and Y**; Z does not load them.
- **Three machines on the same LAN, wired where possible**, with these ports free:

  | Port | Bound by | Purpose |
  |------|----------|---------|
  | `8001` | Cloud X | accepts the WebSocket connection from Middle Y |
  | `8000` | Middle Y | accepts the WebSocket connection from End Z |
  | `8002` | Middle Y | dashboard feed (plain WebSocket) |

- **Windows is recommended but not required.** `common/win.py` calls `timeBeginPeriod(1)` so 60 Hz ticks are not quantised to the default 15.6 ms timer; on other platforms the call is swallowed and the OS timer is used as-is.
- **A browser** on any machine for `dashboard.html`.
- **No VPN on any of the three machines while testing.** VPN adapters (Surfshark, corporate, etc.)
  hijack the default route and can make LAN peers unreachable or add an unpredictable RTT.

---

## Quick Start — three machines on one LAN

The commands below use the example LAN `192.168.0.0/24` with Cloud X at `192.168.0.181`.
Replace the addresses with your own (`ipconfig` on each machine).

### 1. Install the same environment on all three machines

From the repository root on **each** machine:

```powershell
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python selftest.py
```

On macOS/Linux use `python3 -m venv venv` and `source venv/bin/activate`. Record the
`ticks ... hash ...` line printed by `selftest.py`: **the hash must be identical on X and Y**.
If it is not, stop — the two renderers would diverge the moment Y takes over. The self-test
also prints the Python/pygame/Pillow/websockets versions so a mismatch is easy to spot.

### 2. Provide the image assets

Copy `background.png`, `bullet.png`, `player.jpg` and `rock.png` into `images/` on **Cloud X**
and **Middle Y**. These four files are loaded at startup; Z does not need them.

### 3. Give each machine a stable address

Use a DHCP reservation or a static address, and switch the VPN off. Each tier only needs to
know the tier it connects to:

| Tier | Example address | Configuration needed |
|------|-----------------|----------------------|
| Cloud X | `192.168.0.181` | **none** — it listens on `0.0.0.0:8001` |
| Middle Y | `192.168.0.182` | `FYP_X_IP` = Cloud X's address |
| End Z | `192.168.0.183` | `FYP_Y_IP` = Middle Y's address |

`common/config.py` is the same file everywhere; the `run_*.cmd` launchers set those
environment variables. They are `.cmd` rather than `.ps1` on purpose: the default Windows
execution policy (`Restricted`) blocks local PowerShell scripts, but batch files always run.
If you prefer to start the Python scripts by hand, set the variables first:

```powershell
$env:FYP_X_IP = "192.168.0.181"   # only on Middle Y
$env:FYP_Y_IP = "192.168.0.182"   # only on End Z
```

### 4. Allow the ports through Windows Firewall (once per machine)

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

### 5. Start the tiers — in this order

Open one terminal per machine and **run from the repository root** so the `common` package
imports correctly and the CSV logs land beside the scripts:

```powershell
.\run_x.cmd                          # Cloud X   -> "X ready: ws://192.168.0.181:8001"
.\run_y.cmd 192.168.0.181            # Middle Y  -> "connected to X at ws://..."
.\run_z.cmd 192.168.0.182            # End Z     -> opens the 960x540 game window
```

The single argument is the address of the peer to dial, so the same launcher works on every
network without editing a file.

X and Y now reconnect automatically, so the order is no longer critical, but starting X first
avoids an initial `X link down` message and a couple of seconds in edge mode. The startup
banners print the LAN address each tier is reachable on — use those when configuring the next
machine.

### 6. Open the dashboard

Open `dashboard.html?ip=192.168.0.182` in a browser on any machine (the query parameter avoids
the prompt), or double-click the file and enter **Y's IP** when asked. The page reconnects by
itself if Y restarts.

### Single-machine demo

Start the three tiers in separate terminals as `.\run_x.cmd`, `.\run_y.cmd 127.0.0.1`,
`.\run_z.cmd 127.0.0.1` — the defaults in `common/config.py` are all `127.0.0.1`, so this
reproduces the original one-host setup.

---

## What the Dashboard Shows

- **Active node** — `CLOUD X` (green) or `EDGE Y` (orange), updated every 0.2 s.
- **RTT X↔Y** — the smoothed round-trip time Y measures with its ping/pong loop.
- **X lag** — how many ticks ahead Y's local simulation is compared with the newest frame received from X.
- **input→display (Z)** — end-to-end latency reported by End Z: how long it took between sending an input and displaying a frame produced from it.
- **Cloud X link** — `up`/`DOWN`, whether Middle Y currently holds a WebSocket to X.
- **dashboard** — whether the browser is connected to Y (it retries every second).
- **Injected X↔Y latency (RTT)** — a 0–400 ms slider.

## Latency Injection

The slider simulates a slower WAN link without touching the network stack. When you move it, the browser sends `{"delay_ms": value}` to Y, which sets both `DelayLine` instances to `value / 2000` seconds — half the RTT per direction:

- **uplink** — every message Y sends to X (inputs, pings) is held for that delay;
- **downlink** — every message X sends to Y (pongs, snapshots, frames) is held for that delay.

The `DelayLine` queues are ordered and non-blocking, so delay is applied per message without reordering. Increase the slider past roughly **80 ms** and, after three consecutive samples, Y switches to `EDGE Y`; bring it back under **50 ms** and the mode returns to `CLOUD X` after 3 s. The dashboard's RTT value and the overlay on Z (`CLOUD X (high quality)` → `EDGE Y (fallback)`) confirm the migration.

A real link failure is handled too: if the X connection drops (unplug Cloud X, restart it, or
lose Wi-Fi) Y switches to `EDGE Y` immediately and keeps the game running, so Z never freezes.
Y re-dials X every 2 s; once the RTT has stayed below `LOW_MS` for `RECOVER_S` the mode returns
to `CLOUD X`. Because X asks for a snapshot on every connection, the game state continues
instead of restarting.

---

## Verification & Self-Test

Run this on **both** Cloud X and Middle Y:

```powershell
.\venv\Scripts\python.exe selftest.py
```

(With the virtual environment activated, plain `python selftest.py` is equivalent.)

It plays a fixed 3000-tick input script, performs a JSON round-trip and restore on a differently-seeded instance, and prints:

```
host: <machine> | <OS build>
python <ver> | pygame <ver> | pillow <ver> | websockets <ver>
ticks 3000 score <n> deaths <n> hash <md5>
resync OK
render bytes: <X bytes> (X) <Y bytes> (Y)
```

The **hash must be identical on both machines** and `resync OK` must be printed — that is what guarantees Y can take over from X without a visible state jump. Compare the `host`/version lines too: a different Python version is the most likely reason for a hash mismatch.

For a quick X-side capacity check, start X alone, play for a minute, then look at
`log_x.csv`: `render_ms` is the per-frame encoding cost and `jpeg_bytes × 60` is roughly the
upstream bandwidth X needs in `CLOUD X` mode. On the reference machine the first frames cost
~25 ms and then settle at 7–10 ms for ~42 KB frames, i.e. about **20 Mbps** at 60 fps.

## Output & Logs

All three logs are written to the **current working directory** (run from the repository root so they appear beside the scripts) and are truncated on each start.

`log_x.csv` — written by Cloud X for every frame it renders:

| Column | Meaning |
|--------|---------|
| `unix_time` | wall-clock timestamp of the render |
| `tick` | game tick in the frame header |
| `seq` | input sequence number carried in the frame header |
| `render_ms` | time spent in `game.render()` (blit + scale + JPEG encode) |
| `jpeg_bytes` | encoded frame size, i.e. the bandwidth consumed by that frame |

`log_y.csv` — written by Middle Y every 0.2 s:

| Column | Meaning |
|--------|---------|
| `unix_time` | wall-clock timestamp of the sample |
| `mode` | active tier at that moment (`X` or `Y`) |
| `rtt_ms` | smoothed Y↔X RTT in milliseconds |
| `injected_delay_ms` | RTT currently injected by the dashboard slider |
| `e2e_ms_from_Z` | last end-to-end input→display latency reported by Z |
| `x_link` | `1` while the WebSocket to Cloud X is up, `0` while it is down |

`log_z.csv` — written by End Z for every displayed frame that can be matched to an input:

| Column | Meaning |
|--------|---------|
| `unix_time` | wall-clock timestamp of display |
| `source` | tier that produced the frame (`X` or `Y`) |
| `tick` | game tick carried in the frame header |
| `e2e_ms` | input→display latency in milliseconds |

Y flushes its file on every sample; Z flushes every 30 frames.

---

## Configuration

All tunables live in `common/config.py`:

| Constant | Env var | Default | Meaning |
|----------|---------|---------|---------|
| `X_HOST` | `FYP_X_HOST` | `0.0.0.0` | interface Cloud X binds (not a connect target) |
| `Y_HOST` | `FYP_Y_HOST` | `0.0.0.0` | interface Middle Y binds |
| `X_IP` | `FYP_X_IP` | `127.0.0.1` | address Middle Y dials (Cloud X) |
| `Y_IP` | `FYP_Y_IP` | `127.0.0.1` | address End Z and the dashboard dial (Middle Y) |
| `X_PORT` | `FYP_X_PORT` | `8001` | port Cloud X listens on for Y |
| `Y_PORT_Z` | `FYP_Y_PORT_Z` | `8000` | port Middle Y listens on for Z |
| `Y_PORT_DASH` | `FYP_Y_PORT_DASH` | `8002` | port Middle Y serves the dashboard on |
| `PING_INTERVAL`, `PING_TIMEOUT` | `FYP_PING_INTERVAL`, `FYP_PING_TIMEOUT` | `15`, `15` | WebSocket keepalive, in seconds |
| `RECONNECT_S` | — | `2.0` | wait before re-dialling a lost peer |
| `TICK_RATE` | — | `60` | simulation ticks per second (each tick = 4 original 240 fps frames) |
| `X_STREAM_EVERY` | — | `1` | X renders every tick → 60 fps |
| `Y_STREAM_EVERY` | — | `2` | Y renders every 2nd tick → 30 fps |
| `WIN_W`, `WIN_H` | — | `960`, `540` | window size on Z |
| `X_SIZE`, `X_QUALITY` | — | `(960, 540)`, `80` | Cloud X capture size and JPEG quality |
| `Y_SIZE`, `Y_QUALITY` | — | `(480, 270)`, `40` | Edge Y capture size and JPEG quality |
| `HIGH_MS` | — | `80` | RTT above which a sample counts as "bad" (X → Y) |
| `LOW_MS` | — | `50` | RTT below which recovery can begin (Y → X) |
| `BAD_COUNT` | — | `3` | consecutive bad samples before switching to Y |
| `RECOVER_S` | — | `3.0` | seconds below `LOW_MS` before switching back to X |

`HIGH_MS`/`LOW_MS` are calibrated for a healthy LAN (sub-millisecond RTT), where the mode only
changes when the dashboard slider injects delay. If you later host X on a real WAN link, measure
the baseline RTT first and set `HIGH_MS = baseline + 30`, `LOW_MS = baseline + 10`; otherwise Y
may sit in fallback permanently or flap.

---

## Troubleshooting (three-machine runs)

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `X link down (ConnectionRefusedError ...)` on Y | X not running, wrong `FYP_X_IP`, wrong port, or firewall | Start X; `Test-NetConnection <X_IP> -Port 8001` from Y; add the inbound rule |
| Z shows `reconnecting to Y ...` | Y not running or port 8000 blocked | Start Y; `Test-NetConnection <Y_IP> -Port 8000` from Z |
| Dashboard says `disconnected - retrying` | Wrong IP in `?ip=`, or port 8002 blocked | Re-open with `dashboard.html?ip=<Y_IP>`; check the Y firewall rule |
| `selftest.py` hashes differ | Different Python versions on X and Y (most likely), or a modified `common/game.py` | Install the same 3.13.x and the pinned `requirements.txt` on both, then re-run |
| Mode never switches when the slider moves | Slider changed on a dashboard attached to a different Y, or X link is down | Check the dashboard's `Cloud X link` field; edit `HIGH_MS`/`LOW_MS` only if the real RTT baseline is high |
| The startup banner shows a `10.x` / `100.x` address | A VPN owns the default route | Quit the VPN, then restart the tier |
| `OSError: [WinError 10048]` (port in use) | Another instance or another app holds the port | `Get-NetTCPConnection -LocalPort 8001 -State Listen`, stop that process |
| Frame rate drops, `render_ms` near 16 ms in `log_x.csv` | X's encode is the bottleneck | Raise `X_STREAM_EVERY` to 2 (30 fps) or lower `X_QUALITY` |

Keep the machines awake for the demo (`powercfg /change standby-timeout-ac 0`) and, if you will
merge `log_y.csv` with `log_z.csv` by `unix_time`, synchronise the clocks (`w32tm /resync`).
The `rtt_ms` and `e2e_ms` columns are measured inside one process and do not depend on clock sync.

## Known Limitations

- **TCP transport.** All traffic is WebSocket over TCP. The simulator models *constant* one-way
  delay only — there is no packet loss, reordering or jitter, and a stalled TCP segment stalls
  every later frame (head-of-line blocking). A production cloud-gaming stack would use UDP/WebRTC.
- **Measured RTT includes X's own processing.** Pongs are answered from the same loop that renders
  frames, so a busy X inflates `rtt_ms`. This is realistic "cloud lag", but it is not network-only.
- **Lock-step replay.** X advances only on inputs forwarded by Y, so in `CLOUD X` mode the frame Z
  displays corresponds to a state roughly one RTT old. Switching back from `EDGE Y` can therefore
  show a brief rewind.
- **Injection point.** The dashboard slider delays only the X↔Y leg, which is exactly the cloud leg
  the edge tier is meant to hide; the Z↔Y hop is untouched.
- **One game, one input.** Multiple Z clients can watch, but they share a single input state and
  there is one game instance per Y.
- **Quality knob only.** There is no bitrate cap or adaptive encoder; quality is fixed per tier by
  `X_QUALITY`/`Y_QUALITY` and `X_SIZE`/`Y_SIZE`.

---

## License

Academic research project — provided as-is for educational use.
