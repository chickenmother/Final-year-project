@echo off
setlocal
cd /d "%~dp0"

rem WS2.2 test control panel (Tk). It talks only to Middle Y's dashboard port.
rem   run_panel.cmd                 -> Y at 127.0.0.1 (same PC)
rem   run_panel.cmd 192.168.0.182   -> Y on another machine
rem   run_panel.cmd 192.168.0.182 tools\plans\ws3_1_all_cloud.json
rem Keep the panel on a machine with a desktop session; End Z is separate.
rem Clear any headless SDL setting inherited from a test shell (harmless for Tk,
rem but keeps a follow-up run_local.cmd clean).
set "SDL_VIDEODRIVER="

set "Y_ADDR=%~1"
if "%Y_ADDR%"=="" set "Y_ADDR=127.0.0.1"
set "PANEL_PLAN="
set "PANEL_PLAN_ARG="
if not "%~2"=="" (
    set "PANEL_PLAN=%~2"
    set "PANEL_PLAN_ARG=--plan "%~2""
)

if not exist "venv\Scripts\python.exe" (
    echo venv not found. Run:
    echo   py -3.13 -m venv venv
    echo   venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

echo FYP test control panel: Middle Y at %Y_ADDR%:8002
echo Start Middle Y first (run_y.cmd) and End Z with FYP_TEST=1 for a test run.
echo.
venv\Scripts\python.exe tools\test_panel.py --y ws://%Y_ADDR%:8002 %PANEL_PLAN_ARG%
if errorlevel 1 pause
