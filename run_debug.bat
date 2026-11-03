@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0app\main.py"
    if errorlevel 1 pause
    exit /b 0
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%~dp0app\main.py"
    if errorlevel 1 pause
    exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    python "%~dp0app\main.py"
    if errorlevel 1 pause
    exit /b 0
)

echo Python was not found.
echo Install Python 3.13+ and run: python -m pip install -r requirements.txt
pause
exit /b 1
