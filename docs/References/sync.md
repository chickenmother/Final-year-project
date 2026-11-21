# Sync

## Purpose

1. I develop on different machines; I need to know what changed where.
2. Agents on different machines need the current situation.

## Rules

1. Include:
   - time and date
   - machine/tier that made the change
   - title
   - changes made
2. Format: use the current `sync.txt` as an example, but this file is the standard.
3. Append entries; keep the latest at the bottom before `END OF SYNC`.
4. Mention the pinned lab X / no-pull and the push status when relevant.

## Example

[2026-11-21 11:25 +09:00 | from chicken-mother (running Y and Z) — architecture direction: task-level placement]
  README Architecture now separates:
    - Baseline whole-pipeline (implemented): X A-E + render/stream, Y proxy/
      fallback, Z input/display.
    - Task model A-E (simulation / AI / hit registration / render / encode),
      L leaderboard pinned to X, U UI local to Z. F-K and M-T are reserved for
      future task splits; the semantic task count is not fixed.
    - Placement patterns (planned): All Cloud, Offload A/B, All Edge, Pinned L;
      the legacy whole-pipeline remains the comparison mode.
    - Pattern axes: placement pattern vs legacy mode vs video preset vs
      workload / input / delay timeline.
    - Implementation status: A-E + U partial; L, router, placement table and
      local A/B copies planned; Phase 2 Tk panel; Phase 3 X runtime video.

  docs/test-panel.md now marks `mode` as legacy and `placement` as planned.
  No code changes. Lab X remains pinned to 4f189b9; do NOT pull on X.
