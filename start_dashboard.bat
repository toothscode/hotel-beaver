@echo off
REM Hotel Rate Finder - double-click to open the dashboard in your browser.
cd /d "%~dp0"
python -m streamlit run dashboard\app.py --server.port 8501
pause
