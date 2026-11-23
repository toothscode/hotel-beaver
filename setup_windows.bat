@echo off
REM Hotel Rate Finder - ONE-TIME setup on a new Windows PC. Double-click it.
REM Safe to run again (it just re-checks everything).
cd /d "%~dp0"
echo.
echo ===== Hotel Rate Finder setup =====
echo.

python --version >nul 2>&1
if errorlevel 1 (
  echo [X] Python is not installed.
  echo     Install Python 3.12 from https://www.python.org/downloads/
  echo     IMPORTANT: on the first installer screen tick "Add python.exe to PATH".
  echo     Then double-click setup_windows.bat again.
  pause
  exit /b 1
)
python --version

echo.
echo [1/5] Creating private Python environment (.venv) ...
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto :fail
set PY=.venv\Scripts\python.exe

echo [2/5] Installing packages (takes a few minutes the first time) ...
"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install -r requirements.txt --quiet
if errorlevel 1 goto :fail

echo [3/5] Installing headless browser for Leela ...
"%PY%" -m playwright install chromium
if errorlevel 1 goto :fail

echo [4/5] Running offline tests ...
"%PY%" -m pytest tests -q
if errorlevel 1 goto :fail

echo [5/5] Checking access to every hotel website from THIS network (about 2-3 minutes) ...
"%PY%" tools\check_access.py
if errorlevel 1 (
  echo.
  echo [!] Some hotel could not be reached from this network - see above.
  echo     Do NOT start big runs until this passes. Send this screen to Pratyush.
  pause
  exit /b 1
)

echo.
echo ===== Setup complete =====
echo From now on just double-click start_dashboard.bat
pause
exit /b 0

:fail
echo.
echo [X] Setup failed at the step above. Send a screenshot of this window to Pratyush.
pause
exit /b 1
