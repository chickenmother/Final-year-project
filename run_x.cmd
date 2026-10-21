@echo off
setlocal
cd /d "%~dp0"

set "FYP_X_HOST=%~1"
if "%FYP_X_HOST%"=="" set "FYP_X_HOST=0.0.0.0"

if not exist "venv\Scripts\python.exe" (
    echo venv not found. Run: py -3.13 -m venv venv
    echo                 then: venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

echo Cloud X: listening on %FYP_X_HOST%:8001
echo If Middle Y cannot connect, allow inbound TCP 8001 ^(Private profile^) in Windows Firewall.
echo.
venv\Scripts\python.exe -u x_server.py
