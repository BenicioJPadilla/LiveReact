@echo off
REM LiveReact dev launcher (Windows). Activates the venv and runs demo mode.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo No virtual environment found. Create one with:
    echo     py -3.12 -m venv .venv
    echo     .venv\Scripts\python -m pip install -e ".[dev]"
    exit /b 1
)
".venv\Scripts\python.exe" -m livereact --demo %*
endlocal
