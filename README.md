# 3-Tier Vertical Cloud Gaming Latency Simulator

**Mitigating the main drawback of cloud gaming — latency — with edge computing**

| | |
|---|---|
| **Author** | Andrew Sung |
| **Supervisor** | Noriko Matsumoto |
| **Institution** | Kyushu Sangyou Unisersity Department of Information Science|
| **Programme** | Final Year Project |
| **Academic Year** | [2025/2026] |
| **Status** | Working prototype — tested with Python 3.10.5 on Windows |

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
├── venv/                        # local virtual environment (git-ignored)
├── x_server.py                  # Cloud X — game engine + high-quality renderer
├── y_gateway.py                 # Middle Y — proxy, fallback renderer, RTT monitor, dashboard
├── z_client.py                  # End Z — input sampling + frame display
├── selftest.py                  # determinism / resync check (run on X and Y)
├── dashboard.html               # live mode, RTT, lag and latency-injection dashboard
├── log_y.csv                    # generated by Y at runtime (git-ignored)
├── log_z.csv                    # generated by Z at runtime (git-ignored)
├── common/                      # shared by X and Y
│   ├── __init__.py
│   ├── config.py                # IPs, ports, tick rate, quality and switch thresholds
│   ├── game.py                  # deterministic game logic + JPEG renderer
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

- **Python 3.10+** — developed and tested on **Python 3.10.5**.
- **Python packages** (versions used during testing):
  - `pygame 2.6.1` — display, input, surface scaling and JPEG decoding on Z
  - `pillow 12.3.0` — JPEG encoding on X and Y
  - `websockets 16.1.1` — the async client/server transport used by all three tiers
- **The four image assets** in `images/` — `background.png`, `bullet.png`, `player.jpg`, `rock.png`. Required on **X and Y**; Z does not load them.
- **Three processes** (or three machines on the same LAN) with these ports free:

  | Port | Bound by | Purpose |
  |------|----------|---------|
  | `8001` | Cloud X | accepts the WebSocket connection from Middle Y |
  | `8000` | Middle Y | accepts the WebSocket connection from End Z |
  | `8002` | Middle Y | dashboard feed (plain WebSocket) |

- **Windows is recommended but not required.** `common/win.py` calls `timeBeginPeriod(1)` so 60 Hz ticks are not quantised to the default 15.6 ms timer; on other platforms the call is swallowed and the OS timer is used as-is.
- **A browser** on any machine for `dashboard.html`.

> There is currently no `requirements.txt` in the repository; the packages are installed directly in the Quick Start section.

---

## Quick Start — Simulator

### 1. Create and activate a virtual environment

From the repository root (`FYP/`):

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install pygame pillow websockets
```

On macOS/Linux the activation command is `source venv/bin/activate`; everything else is identical.

### 2. Configure the IP addresses

Edit `common/config.py` and set the machine that runs each tier:

```python
X_IP = "127.0.0.1"   # desktop  (Cloud X)
Y_IP = "127.0.0.1"   # laptop A (Middle Edge Gateway Y)
```

Use `ipconfig` (Windows) or `ip addr` (Linux) to find each machine's LAN address. For a single-machine demo leave both as `127.0.0.1`. Ports are defined on the following lines (`X_PORT`, `Y_PORT_Z`, `Y_PORT_DASH`) and normally do not need changing.

### 3. Provide the image assets

Copy `background.png`, `bullet.png`, `player.jpg` and `rock.png` into `images/` on **Cloud X** and **Middle Y**. These four files are loaded at startup; there is no placeholder file in the repository.

### 4. Start the tiers — in this order

Open three terminals, activate the virtual environment in each, and **run from the repository root** so the `common` package imports correctly and the CSV logs land beside the scripts:

```powershell
python x_server.py      # terminal 1 — Cloud X   -> "X ready on port 8001"
```

```powershell
python y_gateway.py     # terminal 2 — Middle Y  -> "connected to X" / "Y ready: waiting for Z and dashboard"
```

```powershell
python z_client.py      # terminal 3 — End Z     -> opens the 960x540 game window
```

On separate machines, run the corresponding process on each host after setting `X_IP`/`Y_IP` consistently everywhere. X must be running before Y, because Y connects to X once at startup; Z can join at any time.

### 5. Open the dashboard

Open `dashboard.html` in a browser (double-clicking the file is enough) and enter **Y's IP address** when prompted — for example `127.0.0.1` in a local demo, or the laptop's LAN IP such as `192.168.1.11`. The page connects to `ws://<that IP>:8002`.

---

## What the Dashboard Shows

- **Active node** — `CLOUD X` (green) or `EDGE Y` (orange), updated every 0.2 s.
- **RTT X↔Y** — the smoothed round-trip time Y measures with its ping/pong loop.
- **X lag** — how many ticks ahead Y's local simulation is compared with the newest frame received from X.
- **input→display (Z)** — end-to-end latency reported by End Z: how long it took between sending an input and displaying a frame produced from it.
- **Injected X↔Y latency (RTT)** — a 0–400 ms slider.

## Latency Injection

The slider simulates a slower WAN link without touching the network stack. When you move it, the browser sends `{"delay_ms": value}` to Y, which sets both `DelayLine` instances to `value / 2000` seconds — half the RTT per direction:

- **uplink** — every message Y sends to X (inputs, pings) is held for that delay;
- **downlink** — every message X sends to Y (pongs, snapshots, frames) is held for that delay.

The `DelayLine` queues are ordered and non-blocking, so delay is applied per message without reordering. Increase the slider past roughly **80 ms** and, after three consecutive samples, Y switches to `EDGE Y`; bring it back under **50 ms** and the mode returns to `CLOUD X` after 3 s. The dashboard's RTT value and the overlay on Z (`CLOUD X (high quality)` → `EDGE Y (fallback)`) confirm the migration.

---

## Verification & Self-Test

Run this on **both** Cloud X and Middle Y:

```powershell
python selftest.py
```

It plays a fixed 3000-tick input script, performs a JSON round-trip and restore on a differently-seeded instance, and prints:

```
ticks 3000 score <n> deaths <n> hash <md5>
resync OK
render bytes: <X bytes> (X) <Y bytes> (Y)
```

The **hash must be identical on both machines** and `resync OK` must be printed — that is what guarantees Y can take over from X without a visible state jump.

## Output & Logs

Both logs are written to the **current working directory** (run from the repository root so they appear beside the scripts) and are truncated on each start.

`log_y.csv` — written by Middle Y every 0.2 s:

| Column | Meaning |
|--------|---------|
| `unix_time` | wall-clock timestamp of the sample |
| `mode` | active tier at that moment (`X` or `Y`) |
| `rtt_ms` | smoothed Y↔X RTT in milliseconds |
| `injected_delay_ms` | RTT currently injected by the dashboard slider |
| `e2e_ms_from_Z` | last end-to-end input→display latency reported by Z |

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

| Constant | Default | Meaning |
|----------|---------|---------|
| `X_IP` | `127.0.0.1` | address of the Cloud X machine |
| `Y_IP` | `127.0.0.1` | address of the Middle Y machine |
| `X_PORT` | `8001` | port Cloud X listens on for Y |
| `Y_PORT_Z` | `8000` | port Middle Y listens on for Z |
| `Y_PORT_DASH` | `8002` | port Middle Y serves the dashboard on |
| `TICK_RATE` | `60` | simulation ticks per second (each tick = 4 original 240 fps frames) |
| `X_STREAM_EVERY` | `1` | X renders every tick → 60 fps |
| `Y_STREAM_EVERY` | `2` | Y renders every 2nd tick → 30 fps |
| `WIN_W`, `WIN_H` | `960`, `540` | window size on Z |
| `X_SIZE`, `X_QUALITY` | `(960, 540)`, `80` | Cloud X capture size and JPEG quality |
| `Y_SIZE`, `Y_QUALITY` | `(480, 270)`, `40` | Edge Y capture size and JPEG quality |
| `HIGH_MS` | `80` | RTT above which a sample counts as "bad" (X → Y) |
| `LOW_MS` | `50` | RTT below which recovery can begin (Y → X) |
| `BAD_COUNT` | `3` | consecutive bad samples before switching to Y |
| `RECOVER_S` | `3.0` | seconds below `LOW_MS` before switching back to X |

---

## License

Academic research project — provided as-is for educational use.
