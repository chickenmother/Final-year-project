# Game v2 — Task-Placement MVP Plan

## Status

Milestone 1 (game core) is implemented in `game/`:

- player/bot/obstacle/bullet entities
- HP, damage, bot shooting, waves, explosion particles
- spatial-grid hit registration
- light / medium / heavy workload profiles
- snapshot/restore and deterministic digest
- unit tests in `tests/test_game_core.py`

Milestone 2 (menu + start/game-over protocol) is partially implemented:

- local `ui/menu.py` on Z with VS Bot, light/medium/heavy selection, exit
- disabled Leaderboard/Multiplayer placeholders
- `start` message resets X/Y to the chosen workload and seed
- X emits `game_over`; Y forwards it to Z; Z returns to the menu
- leaderboard remains pending

X and Y now import the v2 core directly. The legacy `common/game.py`
remains available for `selftest.py` and older comparisons.

## 1. Goal

Extend the current 3-tier simulator from whole-pipeline failover to
**task-level placement**:

```
Z (end node) -> Y (edge router) -> X (cloud tasks)
                         |-> Y local task copies
```

A task can be pinned or movable. The first experiment compares:

1. **All Cloud** — A/B/C/D/E on X.
2. **Offload A/B** — A/B on Y; C/D/E on X.
3. **All Edge** — everything on Y (upper bound / weaker node).
4. **Pinned task** — leaderboard L always on X.

The existing full-renderer fallback (`CLOUD X` / `EDGE Y`) stays as a
legacy comparison mode.

## 2. Scope

### MVP (must finish)

- Local menu on Z: title, VS Bot, Leaderboard, Exit, Dev panel.
- Gameplay: player HP, bots, bot shooting, fixed obstacles with HP,
  bullets, damage, explosions, waves, score.
- Leaderboard task on X only (SQLite).
- Task router on Y with a placement table.
- Dashboard/menu controls: All Cloud, Offload A/B, All Edge.
- Workload profiles: light, medium, heavy.
- Logging: per-task latency, placement, mode, RTT, e2e.
- Deterministic selftest for light and heavy profiles.

### Stretch (only after MVP)

- Multiplayer netcode.
- Advanced pathfinding/flow fields.
- Procedural maps.
- Asset streaming.
- Auto placement policy (professor Stage 3).

### Non-goals for the first implementation

- Docker is not required for the first working version. The services are
  Python processes with the same contract; containerization comes later.
- Real code migration. Stage 2 uses pre-placed copies and a routing
  switch, matching the professor's prototype.
- Cloud leaderboard caching on Y/Z. L is X-only by design.

## 3. Task model

Task count is not fixed. Start with these semantic tasks, then split
only if profiling shows a hotspot.

| Task | Responsibility | State | Default placement |
|------|----------------|-------|-------------------|
| A | World simulation: movement, spawning, physics, HP, score | Stateful | X (movable) |
| B | AI / pathfinding / bot decisions | Needs A state | X (movable candidate) |
| C | Hit registration: bullets vs bots/player/obstacles | Needs entity state | X (movable) |
| D | Rendering: world, HP bars, particles | Stateful visual | X (movable) |
| E | Video encoding: JPEG / H.264 | Stateless per frame | X (movable) |
| L | Leaderboard / results store | Persistent SQLite | X (pinned) |
| U | UI / menu / leaderboard display | Local | Z (not offloaded) |

Dependency graph:

```
Input -> A simulation -> B AI -> C hit registration -> A (HP/score)
                         -> D render -> E encode -> Z
Game over -> L submit/top -> U display
```

`L` is the prime example of a pinned, stateful task: it must stay on X
and must not be selected by any placement policy.

## 4. Proposed file layout

```
common/
  config.py            existing; add workload/placement env vars
  game.py              compatibility facade; re-export Game
  video.py             existing H.264 encode/decode
  tasks.py             TaskRequest/TaskResponse/Placement types
  protocol.py          JSON message types shared by X/Y/Z

game/
  __init__.py
  entities.py          Player, Bot, Bullet, Obstacle, Explosion
  simulation.py        simulation step, waves, score, deterministic RNG
  ai.py                bot state machine, targeting, optional pathfinding
  hitreg.py            collision/broadphase, damage/HP
  render.py            world/HP/particle rendering
  effects.py           particle pool and explosion bursts
  workload.py          WorkloadConfig and light/medium/heavy profiles

tasks/
  __init__.py
  leaderboard.py       SQLite leaderboard service (pinned X)
  router.py            placement table, routing, local/remote dispatch
  client.py            task client used by X/Y/Z

ui/
  __init__.py
  menu.py              Pygame menu state machine on Z
  widgets.py           buttons/labels/panel helpers
  leaderboard_view.py  leaderboard screen

x_server.py            X game loop + task host + leaderboard
y_gateway.py           Y router + local task copies + dashboard backend
z_client.py            Z menu, input, display, leaderboard view
dashboard.html         placement/workload controls, task latency view
selftest.py            add light/heavy determinism tests
```

`common/game.py` remains importable so `selftest.py` and existing
fallback code keep working during the refactor. It re-exports `Game`
from `game/simulation.py`.

## 5. Protocol additions

All control messages are JSON over the existing WebSocket links. Binary
frames keep the current JPEG/H.264 header.

```
Z -> Y -> X
  {"t":"start","mode":"vs_bot","workload":"heavy","placement":"all_x"}
  {"t":"quit"}
  {"t":"leaderboard","action":"top","limit":10}
  {"t":"leaderboard","action":"submit","result":{...}}

Y -> X
  {"t":"task","id":"A","tick":123,"payload":{...}}
  {"t":"placement","tasks":{"A":"Y","B":"Y","C":"X","D":"X","E":"X"}}

X -> Y -> Z
  {"t":"task_result","id":"A","tick":123,"result":{...},"compute_ms":4.2}
  {"t":"game_over","score":1234,"survival_ms":45000}
  {"t":"leaderboard_result","rows":[...]}
```

Placement rules:

- `L` is pinned to X; a placement message that tries to move it is
  rejected and logged.
- `U` is local to Z and never appears in the router table.
- Unknown task IDs are rejected.

## 6. Leaderboard task (X only)

Use Python's built-in `sqlite3`; no new dependency.

Schema:

```sql
CREATE TABLE IF NOT EXISTS matches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  mode TEXT NOT NULL,
  score INTEGER NOT NULL,
  survival_ms INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
```

Operations:

- `submit(result)` -> insert and return the new rank.
- `top(limit)` -> ordered by score desc, survival_ms desc.
- `health()` -> optional.

X owns the database file (`leaderboard.db`). Y only forwards requests.
Z only displays results. If X is unreachable, Z shows
"leaderboard unavailable" rather than using a local cache.

## 7. Gameplay design

### Entities

- **Player**: position, HP, fire cooldown, score.
- **Bot**: position, HP, target, fire cooldown, simple state machine
  (seek, avoid, shoot).
- **Obstacle**: fixed position, HP, size; destroyed at 0 HP.
- **Bullet**: owner, position, velocity, damage.
- **Explosion**: particle burst; visual only unless damage radius is used.

### Rules

- Player and bots collide with obstacles: reduce HP, push out.
- Bullets hit bots, player, and obstacles; reduce HP.
- At 0 HP: remove entity, spawn explosion, add score.
- Bots shoot at the player when in range and line of sight (optional).
- Waves increase bot/obstacle counts until game over.
- Player death -> game over -> submit result to L.

### WorkloadConfig

```python
@dataclass
class WorkloadConfig:
    bots: int = 0
    obstacles: int = 8
    bullets_per_second: int = 0
    particles_per_explosion: int = 0
    pathfinding_agents: int = 0
    raycast_checks: int = 0
    resolution: tuple = (1600, 900)
    tick_rate: int = 60
```

Profiles:

| Profile | Bots | Obstacles | Bullets | Particles |
|---------|------|-----------|---------|-----------|
| light | 0 | 8 | low | 0 |
| medium | 5 | 100 | 20/s | 50 |
| heavy | 50 | 1000 | 200/s | 300 |

The light profile preserves the current game as the control baseline.

### Determinism

- All gameplay randomness uses a seeded RNG.
- AI decisions and wave spawning use that RNG.
- Particles are visual and excluded from the snapshot/hash unless they
  affect damage.
- `selftest.py` must pass for both light and heavy profiles.

### State snapshot

Include: tick, player, bots, bullets, obstacles, HP, score, wave, RNG.
Exclude: particles, UI state, leaderboard.

Heavy-mode snapshots can be large; use compact lists and later delta
snapshots if needed.

## 8. Menu and UI (local on Z)

State machine:

```
TITLE -> MENU -> MODE_SELECT -> PLAYING -> GAME_OVER -> LEADERBOARD
                  |-> LEADERBOARD
                  |-> DEV
                  |-> EXIT
```

Buttons:

- VS Bot
- Multiplayer (disabled)
- Leaderboard
- Exit
- Dev panel: workload, placement, RTT, mode

Menu is rendered locally on Z. Starting a match sends a control message
to Y, which forwards it to X. The menu never waits on the network to
render; it only waits for a leaderboard result when that screen opens.

## 9. Task router and placement

Placement table on Y:

```python
placement = {
    "A": "X", "B": "X", "C": "X", "D": "X", "E": "X",
    "L": "X",   # pinned
}
```

Rules:

- `L` cannot be moved; reject and log any attempt.
- Local tasks are called directly on Y.
- Remote tasks are sent to X and awaited with a timeout.
- If X is down, movable tasks can fall back to local copies only if a
  copy exists and the task is marked fallback-capable; L never falls back.
- Log task ID, placement, compute time, network time, timeout/drop.

Task transport for the first version: JSON over the existing WebSocket
control channel. Local task calls are direct Python function calls to
avoid unnecessary serialization overhead; remote calls use JSON.

## 10. Dashboard and menu controls

Dashboard buttons/messages:

```json
{"t":"placement","tasks":{"A":"Y","B":"Y","C":"X","D":"X","E":"X"}}
{"t":"workload","profile":"heavy"}
```

Show:

- active placement per task
- active workload profile
- `rtt_xy`, `rtt_zy`, `e2e`
- mode
- per-task compute/network time
- leaderboard pin status (L = X, pinned)

Keep the legacy `CLOUD X` / `EDGE Y` fallback controls separate from
task placement. Do not change resolution/codec when comparing
placements, or the comparison is confounded.

## 11. Logging and experiments

Per run:

```
results/<run_id>/
  run.json
  frames.csv
  samples.csv
  events.csv
  leaderboard.csv
  log_x.csv
  log_y.csv
  log_z.csv
```

Minimum columns:

- frames: run_id, phase, source, codec, keyframe, tick, seq, bytes,
  encode_ms, decode_ms, queue_ms, e2e_ms, mode
- samples: run_id, phase, ts, mode, placement, rtt_xy, rtt_zy, e2e,
  workload, queue_x, queue_z
- events: placement changes, mode switches, task timeouts, leaderboard
  submit/top
- leaderboard: timestamp, operation, rows, latency_ms

Conditions to compare:

1. All Cloud
2. Offload A/B
3. All Edge
4. light vs heavy workload
5. Ethernet vs Wi-Fi/DERP vs injected delay

Metrics: p50/p95/p99 response time, task compute, network time, timeout
rate, leaderboard latency (menu-time only), score/survival.

## 12. Implementation milestones

### Milestone 1 — Game core
- `game/entities.py`, `simulation.py`, `hitreg.py`, `effects.py`
- `WorkloadConfig` and profile loading
- Keep `common/game.py` facade and `selftest.py` passing

### Milestone 2 — Menu and leaderboard
- `ui/menu.py` on Z
- `tasks/leaderboard.py` on X (SQLite, pinned)
- Start/quit/leaderboard control messages
- Local menu works without X; leaderboard shows unavailable if X is down

### Milestone 3 — All-Cloud task baseline
- `tasks/router.py` + placement table on Y
- All tasks on X; Y forwards requests
- Measure Z request->response

### Milestone 4 — Offload A/B
- Local A/B copies on Y
- Placement switch in dashboard/menu
- Same workload and quality as All-Cloud
- Measure and compare

### Milestone 5 — Data and analysis
- run metadata and unified CSVs
- analysis/plots
- light vs heavy, cloud vs offload

### Milestone 6 — Stretch
- Auto placement policy (professor Stage 3)
- Multiplayer
- Dockerization
- Advanced pathfinding

## 13. Testing plan

- `selftest.py` light and heavy profiles: X/Y hashes match.
- Unit tests for HP/damage, obstacle destruction, bot shooting,
  particle pool, leaderboard insert/top.
- Router tests: L pinned, unknown task rejected, X timeout behavior.
- Menu state transition tests (headless where possible).
- Integration: Z start -> X game -> game over -> L submit -> top.
- Placement comparison: All Cloud vs Offload A/B with same workload.

## 14. Risks

| Risk | Mitigation |
|------|------------|
| Scope too large | Implement milestones in order; multiplayer last |
| Heavy game cannot run 60 Hz | Profile; lower tick or use smaller heavy profile |
| Pygame rendering dominates | Keep D/E as explicit tasks; measure separately |
| State snapshots too large | Compact state; particles excluded; delta snapshots later |
| Leaderboard unavailable when X is down | Expected; show clear UI message |
| Docker unavailable | Process-based services first; containerize later |
| Task dependencies erase benefit | This is a research result; measure it explicitly |

## 15. Open decisions

1. Task split: A/B/C/D/E/L/U as above, or merge A+B if AI is tightly
   coupled to simulation.
2. Task transport: JSON over WebSocket first; gRPC/UDP later if needed.
3. Multiplayer: implement only if Milestones 1–5 are complete.
4. Docker: after the process-based router is stable.
5. Leaderboard name source: menu text input or OS username; keep it
   simple for the MVP.


