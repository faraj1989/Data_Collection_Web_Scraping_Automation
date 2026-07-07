@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "project_settings_gui.py"
    exit /b
)

if exist "dashboard_env\Scripts\pythonw.exe" (
    start "" "dashboard_env\Scripts\pythonw.exe" "project_settings_gui.py"
    exit /b
)

py -3 "project_settings_gui.py"
