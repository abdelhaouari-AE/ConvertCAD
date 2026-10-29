@echo off
REM ======================================================================
REM  ConvertCAD - run directly from the source code (no .exe needed)
REM  Uses .venv\ when it exists (scripts\setup_venv.bat), else the system
REM  Python. Useful while developing, or when an antivirus blocks
REM  unsigned programs. The console window shows any error message.
REM ======================================================================
setlocal
cd /d "%~dp0\.."
if exist .venv\Scripts\python.exe (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
    python -m pip install -r requirements.txt --quiet
)
%PY% main.py %*
if errorlevel 1 pause
