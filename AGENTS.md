# AGENTS instructions

## 1. Final-year-project

This repository is my final-year project (fourth-year undergraduate).
The project studies the network latency of cloud services, applied to cloud gaming.

## 2. Brief Architecture

### Node placement

X -> Y -> Z

- X: Cloud
- Y: Edge
- Z: Client

Input goes Z -> Y -> X; video returns X -> Y -> Z. The README Architecture section has the full baseline, task model A–E/L/U and the planned placement patterns.

### Machines

Placement is not fixed; I test different combinations. Current assignment:

| Machine | Current role | Notes |
|---|---|---|
| Home desktop (chicken-mother) | Y (sometimes Z) | confirm current assignment |
| Lab desktop (matslabsungky) | X | pinned to `4f189b9`; do not pull |
| Laptop1 (andoryuuuspc) | Y or Z | |
| Laptop2 (pc23-148d) | Z | |

Only one Y and one Z should run at a time; stale duplicates share ports and state.

### Current status

- Phase 1 test runner/CLI shipped; Phase 2 Tk panel next; task-level placement/router/L planned.
- Branch: `feature/Cloud_X`.
- Lab X is pinned to `4f189b9`; no pull on X.
- The home PC may have duplicate Y/Z processes; kill all but one pair before a run.

## 3. File/Folder placement

If you need to create new files or folders, follow `docs/References/placement.md`.
Use the existing folders first; for anything that does not fit, discuss it with me and create a new folder at the repository root.

## 4. Research

Before answering questions or implementing anything, do the research.
Follow `docs/References/research.md`; keep sources and citations in `docs/notes/`.

## 5. Implementation

- Create a plan first if none exists; follow `docs/References/plans.md` and put it in `docs/plans/`.
- After implementation, append an entry to `sync.txt` following `docs/References/sync.md`.
- Run the tests/selftest and update `README.md` if user-facing paths or commands changed.

## 6. Commands

```powershell
py -3.13 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\run_local.cmd
.\venv\Scripts\python.exe selftest.py
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe tools\test_cli.py --y ws://127.0.0.1:8002 --plan tools\plans\phase1_smoke.json
```

- Python 3.13.9 on Windows/PowerShell.
- Ports: X 8001, Y 8000, Y dashboard/test 8002.
- Browser dashboard: `web/dashboard.html?ip=<Y_ADDRESS>`.
- Unattended Z: `$env:FYP_TEST = "1"` before `run_z.cmd`.

## 7. Push and Pull Request

Do not `git push`, open a pull request, or `git pull` on the pinned lab X until I explicitly ask.
Ask before making a local commit.
