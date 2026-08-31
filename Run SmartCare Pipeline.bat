@echo off
setlocal

cd /d "%~dp0"

echo ============================================================
echo  SmartCare CEM Pipeline
echo  Step 1/2: Download latest export from the SmartCare portal
echo  Step 2/2: Analyze it and update the historical archive
echo ============================================================
echo.

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Could not find venv Python at "%PYTHON_EXE%".
    echo Make sure the .venv folder exists in this project.
    pause
    exit /b 1
)

"%PYTHON_EXE%" "%~dp0reports\run_smartcare_analysis_task.py"

echo.
echo ============================================================
echo  Pipeline finished (exit code %ERRORLEVEL%)
echo ============================================================
pause
