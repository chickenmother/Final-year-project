@echo off
setlocal
cd /d "%~dp0"

rem First argument = LAN address of Middle Y.
set "FYP_Y_IP=%~1"
if "%FYP_Y_IP%"=="" set "FYP_Y_IP=192.168.0.182"

if not exist "venv\Scripts\python.exe" (
    echo venv not found. Run: py -3.13 -m venv venv
    echo                 then: venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

echo End Z: connecting to Middle Y at %FYP_Y_IP%:8000
echo.
venv\Scripts\python.exe -u z_client.py
