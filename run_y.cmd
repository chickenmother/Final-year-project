@echo off
setlocal
cd /d "%~dp0"

rem First argument = LAN address of Cloud X (static or DHCP-reserved).
set "FYP_X_IP=%~1"
if "%FYP_X_IP%"=="" set "FYP_X_IP=192.168.0.181"

if not exist "venv\Scripts\python.exe" (
    echo venv not found. Run: py -3.13 -m venv venv
    echo                 then: venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

echo Middle Y: dialling Cloud X at %FYP_X_IP%, serving Z on 8000 and the dashboard on 8002
echo If Z or the dashboard cannot connect, allow inbound TCP 8000 and 8002 ^(Private profile^).
echo.
venv\Scripts\python.exe -u y_gateway.py
