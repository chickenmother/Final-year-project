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
