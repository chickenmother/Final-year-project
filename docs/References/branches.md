# Branching and releases

Status: 2026-11-23. Current working branch `feature/Cloud_X`; local/remote `main`
exists; no `dev` yet. This document is the source of truth for the branch/release
model. Read when creating or moving branches, or when packaging nodes.

## Short version

- Develop on `dev` plus short-lived `feature/wsX.Y-*` branches.
- `main` is stable and tagged.
- Split X/Y/Z only at release time: `release/x|y|z` from a `main` tag, or
  `dist/x|y|z` bundles.
- Do not develop on node release branches; merge fixes forward.

## Current state

- `feature/Cloud_X` is a long-lived working branch; it contains all three tiers
  (`x_server.py`, `y_gateway.py`, `z_client.py`), `common/`, `game/`, `ui/`,
  `web/`, `tools/`, `tests/`, `docs/`.
- `main` and `origin/main` exist; no `dev`.
- Lab X is at `cda0f52`; do not pull until the branch/deploy decision is applied.

## Why not three node development branches now

- Shared imports: X/Y use `common/` + `game.simulation`; Z uses `common/`,
  `game.settings` (plus `game/__init__`/`workload`) and `ui/`; Y also uses
  `common.testplan`/`report` and `web/`.
- Node branches would duplicate `common/`/`game/` and require three-way merges
  on every shared change.
- Cross-tier tests, the lab X to home Y to Z workflow, `tools/`, `tests/`,
  `docs/`, `AGENTS.md` and `sync.txt` do not belong to one node.
- "Only the files a node needs" is a package manifest, not source history.

## Branch model

| Branch | Purpose | Lifetime |
|---|---|---|
| `main` | stable, tagged FYP milestones | long-lived |
| `dev` | integration of feature branches | long-lived |
| `feature/wsX.Y-*` | one roadmap item | short-lived |
| `release/x|y|z` | deploy-only node snapshots from a `main` tag | release-only |

Tags: `v0.x-ws...` on `main`. Hotfix: `hotfix/*` from `main`, merged back to
`main` and `dev`.

## Feature branch names

Examples: `feature/ws2.2-test-panel`, `feature/ws3.1-router`,
`feature/ws3.2-offload`, `feature/ws1.3-rtt-repeat`.

## Node bundles

| Node | Include | Exclude |
|---|---|---|
| X | `x_server.py`, `common/`, `game/`, `run_x.cmd`, `requirements.txt`, `game_config.json`, `selftest.py`, `images/` (if used) | Y/Z entry points, `ui/`, `web/`, `tools/`, `tests/`, `docs/` |
| Y | `y_gateway.py`, `common/`, `game/`, `web/`, `run_y.cmd`, `requirements.txt`, `game_config.json`, `selftest.py`, `images/` | X/Z entry points, `ui/`, `tools/`, `tests/`, `docs/` |
| Z | `z_client.py`, `common/`, `game/__init__.py`, `game/settings.py`, `game/workload.py`, `ui/`, `game_config.json`, `run_z.cmd`, `requirements.txt` | X/Y entry points, `web/`, `tools/`, `tests/`, `docs/`, `images/` |

The exact subsets must be import-smoke-tested. The node bundles exclude
`tests/`, `tools/`, `docs/`, `AGENTS.md`, `sync.txt`, `venv/` and `logs/`.

## Migration

1. Commit/push the current work on `feature/Cloud_X`.
2. Create `dev` from `feature/Cloud_X`; push `dev`.
3. Create `feature/ws2.2-test-panel` from `dev`; do WS2.2 there.
4. When stable: merge `dev` into `main`; tag; create `release/x|y|z` from the
   tag (or generate `dist/`); do not develop on release branches.
5. Merge fixes forward from `main` to `dev`; keep `release/*` deploy-only.

## Validation

- Docs-only changes: link/path checks and `git diff --check`.
- Code changes: full unittest suite and `selftest.py` per the AGENTS rule.

## Related docs

- `README.md` (Branching and releases), `docs/References/roadmap.md`,
  `AGENTS.md`, `sync.txt`.