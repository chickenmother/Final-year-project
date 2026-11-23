# AGENTS instructions

This repository is my final-year project: a 3-tier cloud-gaming latency simulator
(Cloud X → Edge Y → Client Z). The README has the architecture and task model.

These are the universal rules. Task-specific detail lives in `docs/References/`
and is read only when the current task needs it.

## Universal rules

1. **Research** — before answering/implementing, follow `docs/References/research.md` (read when researching).
2. **Plan** — create a plan before implementation; `docs/References/plans.md`; put it in `docs/plans/`.
3. **Placement** — follow `docs/References/placement.md` only when creating/moving files.
4. **Tests after code changes** — run the full unittest suite (`.\venv\Scripts\python.exe -m unittest discover -s tests -v`) and `selftest.py` after every code change; add or update tests when behaviour changes; docs-only changes need the relevant validation instead; do not report the work as done until the suite passes.
5. **After implementation** — append an entry to `sync.txt` per `docs/References/sync.md`; update `README.md` if user-facing paths/commands changed.
6. **Push/pull** — do not `git push`, open a PR, or `git pull` on the pinned lab X until I explicitly ask; ask before a local commit.
7. **Cleanup** — after testing/implementation/debugging, kill every test process and terminal; no stale listeners on 8000/8001/8002; verify with `Get-NetTCPConnection -LocalPort 8000,8001,8002 -State Listen` and `Get-CimInstance Win32_Process -Filter "Name='python.exe'"`; only explicitly requested long-running tiers stay up.
8. **Rule authoring** — universal rules stay here; task-specific rules go to `docs/References/<topic>.md` with a one-line pointer and a “read when…” note; do not inline task-specific detail or read unused references (saves context/token window).

## References (read only when needed)

- Context/topology/machines/current status — `docs/References/context.md`
- Commands/environment — `docs/References/commands.md`
- File/folder placement — `docs/References/placement.md`
- Research/citations — `docs/References/research.md`
- Plan format — `docs/References/plans.md`
- Sync format — `docs/References/sync.md`
- Roadmap/schedule/workstreams — `docs/References/roadmap.md` (read when you need status/next step)
- Branching/release model — `docs/References/branches.md` (read when changing branches or packaging nodes)
