@echo off
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "Libyana Automation Watchdog" /B "%~dp0.venv\Scripts\pythonw.exe" service_watchdog.py
) else (
    start "Libyana Automation Watchdog" /B pythonw service_watchdog.py
)
exit
