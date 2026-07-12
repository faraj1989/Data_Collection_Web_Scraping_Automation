@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "run_smartcare_analysis_task.py" %*
) else (
    echo Missing virtual environment: .venv\Scripts\python.exe
    echo Please create the virtual environment first.
    pause
    exit /b 1
)
