# Commands

Windows/PowerShell, Python 3.13.9.

```powershell
py -3.13 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\run_local.cmd
.\venv\Scripts\python.exe selftest.py
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe tools\test_cli.py --y ws://127.0.0.1:8002 --plan tools\plans\ws2_1_smoke.json
.\venv\Scripts\python.exe tools\test_cli.py --y ws://127.0.0.1:8002 --plan tools\plans\ws1_3_a1.json
.\venv\Scripts\python.exe tools\test_panel.py --y ws://127.0.0.1:8002 --plan tools\plans\ws2_1_smoke.json
.\run_panel.cmd
.\run_panel.cmd 192.168.0.182 tools\plans\ws3_1_all_cloud.json
```

- Ports: X 8001, Y 8000, Y dashboard/test 8002.
- Dashboard: `web/dashboard.html?ip=<Y_ADDRESS>`.
- Unattended Z: `$env:FYP_TEST = "1"` before `run_z.cmd` (or the panel's **Launch Z (test)**).
- Panel logic tests: `tests/test_panel_model.py`; Tk build/close: `tests/test_panel_smoke.py`.
- Runtime X preset (WS2.3): panel **Apply video to X**, or the Y dashboard message
  `{"cmd":"x_video","preset":"A1"}` (`A0`/`A1`/`A2`/`intra`).
- Task placement (WS3.1–WS3.3): panel **Apply placement**, or `{"cmd":"placement","pattern":"all_cloud"}`
  (`legacy`/`all_cloud`/`offload_ab`/`all_edge`). Bundled plans: `ws3_1_all_cloud.json`,
  `ws3_2_offload_ab.json`, `ws3_3_all_edge.json` in `tools/plans/`
  (`.\venv\Scripts\python.exe tools\test_cli.py --plan tools\plans\ws3_3_all_edge.json`).
- Comparison (WS4.2): `.\venv\Scripts\python.exe tools\compare_reports.py --workload medium`
  (add `--out logs\reports\comparison.md --csv logs\reports\comparison.csv`; `--ids` for explicit
  reports).
- Matched WAN runs (same workload, ~60 s each): `ws3_1_all_cloud_medium.json`,
  `ws3_2_offload_ab.json`, `ws3_3_all_edge.json`, then the comparison above.
  All Edge cannot use the A1 X preset (Y encodes), so it runs `current` by design.
- Free placement (WS3.5): set `"placement": "custom"` plus a `placement_tasks` table, or edit the
  panel's *Task placement* rows. Bundled chains:
  `.\venv\Scripts\python.exe tools\test_cli.py --plan tools\plans\ws3_5_pipeline_on_y.json`
  (`pipeline_on_y`, `split_ab`, `pixels`, `pixels_30s`, `pixels_raw`, `all_on_y`).
  Raw pixels instead of JPEG over a D→E split: `$env:FYP_PIXELS_RAW = "1"` on the rendering tier
  (2.8 MB per 1280x720 frame; expect a frame-rate drop on a real link).
  Inspect one report's chain fields:
  `.\venv\Scripts\python.exe tools\report_peek.py logs\reports\<id>.json`.
- Regression smoke for the three presets (10 s each): `ws3_5_smoke_all_cloud.json`,
  `ws3_5_smoke_offload_ab.json`, `ws3_5_smoke_all_edge.json`.
- Plan-schema gate (loads and validates every bundled plan):
  `.\venv\Scripts\python.exe tools\check_plans.py`.
- Isolated-port stack for a second session (does not touch 8000/8002):
  `$env:FYP_X_PORT="8011"` for X; `$env:FYP_X_PORT="8011"; $env:FYP_Y_PORT_Z="8010";
  $env:FYP_Y_PORT_DASH="8012"` for Y; `$env:FYP_Y_URI="ws://127.0.0.1:8010"; $env:FYP_TEST="1"`
  for Z; then point the CLI at `--y ws://127.0.0.1:8012`.
