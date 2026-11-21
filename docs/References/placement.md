# Placement of files and folders

## Purpose

1. Keep the directory tidy.
2. Make it easy to read.
3. Make it easy to organize files and add future features.

## Rules

1. Use the appropriate folder: tests in `/tests`, game code in `/game`, and so on.
2. If a file does not fit any existing folder, discuss it with me first and create a new folder at the repository root. Add subfolders there if needed.
3. Keep the docs structure below.

## Folders

| Path | Purpose |
|---|---|
| `/common` | shared by all tiers (config, net, video, testplan, report, legacy game oracle) |
| `/docs` | documentation |
| `/docs/archive` | finished plans/files no longer current |
| `/docs/guides` | how-to guides (future; currently `.gitkeep`) |
| `/docs/notes` | research notes, citations, latency notes |
| `/docs/plans` | implementation plans |
| `/docs/References` | references for `AGENTS.md` |
| `/game` | runtime game core |
| `/images` | game assets |
| `/logs` | runtime logs, reports and raw archives (git-ignored) |
| `/tests` | unit tests |
| `/tools` | test driver, autoplay, plans |
| `/ui` | Z menus and overlays |
| `/web` | browser dashboard |

## Root files

These stay at the repository root:

`README.md`, `requirements.txt`, `.gitignore`, `AGENTS.md`, `sync.txt`,
`game_config.json`, `selftest.py`, `run_local.cmd`, `run_x.cmd`, `run_y.cmd`,
`run_z.cmd`, `x_server.py`, `y_gateway.py`, `z_client.py`.

`docs/test-panel.md` stays at the docs root as the test-panel guide; future guides go in `docs/guides/`.
