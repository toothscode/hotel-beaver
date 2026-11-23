@echo off
REM Hotel Rate Finder - double-click to open the dashboard in your browser.
REM Keep this window open while using the dashboard; close it to stop.
cd /d "%~dp0"
REM Use the private environment made by setup_windows.bat if present, else system Python.
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
echo Starting Hotel Rate Finder... your browser will open in a few seconds.
start "" cmd /c "timeout /t 5 /nobreak >nul & start http://localhost:8501"
"%PY%" -m streamlit run dashboard\app.py --server.port 8501 --server.headless true
pause
