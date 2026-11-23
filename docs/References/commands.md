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
```

- Ports: X 8001, Y 8000, Y dashboard/test 8002.
- Dashboard: `web/dashboard.html?ip=<Y_ADDRESS>`.
- Unattended Z: `$env:FYP_TEST = "1"` before `run_z.cmd` (or the panel's **Launch Z (test)**).
- Panel logic tests: `tests/test_panel_model.py`; Tk build/close: `tests/test_panel_smoke.py`.
