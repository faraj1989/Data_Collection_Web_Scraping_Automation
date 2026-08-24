@echo off
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "Libyana Automation Control Panel" /B "%~dp0.venv\Scripts\pythonw.exe" control_panel.py
) else (
    start "Libyana Automation Control Panel" /B pythonw control_panel.py
)
exit
