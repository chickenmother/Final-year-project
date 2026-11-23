# Commands

Windows/PowerShell, Python 3.13.9.

```powershell
py -3.13 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\run_local.cmd
.\venv\Scripts\python.exe selftest.py
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe tools\test_cli.py --y ws://127.0.0.1:8002 --plan tools\plans\phase1_smoke.json
```

- Ports: X 8001, Y 8000, Y dashboard/test 8002.
- Dashboard: `web/dashboard.html?ip=<Y_ADDRESS>`.
- Unattended Z: `$env:FYP_TEST = "1"` before `run_z.cmd`.
