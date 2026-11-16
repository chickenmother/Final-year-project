@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo venv not found. Run:
    echo   py -3.13 -m venv venv
    echo   venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

echo Starting Cloud X, Middle Y and End Z on localhost...
set FYP_HIGH_MS=120
set FYP_LOW_MS=70
set FYP_BAD_COUNT=5
start "FYP Cloud X" cmd /k "%~dp0run_x.cmd"
timeout /t 4 /nobreak >nul
start "FYP Middle Y" cmd /k "%~dp0run_y.cmd 127.0.0.1"
timeout /t 3 /nobreak >nul
start "FYP End Z" cmd /k "%~dp0run_z.cmd 127.0.0.1"

echo.
echo Three windows opened. Close each window to stop that tier.
echo End Z opens the local menu; choose MEDIUM for a smoother local test.
