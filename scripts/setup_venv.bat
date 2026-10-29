@echo off
REM ======================================================================
REM  ConvertCAD - create the development environment (run once)
REM
REM  Creates .venv\ in the project folder and installs everything needed
REM  to run, test and build ConvertCAD. Needs Python 3.10 or newer
REM  (python.org installer, tick "Add python.exe to PATH").
REM ======================================================================
setlocal
cd /d "%~dp0\.."

where py >nul 2>nul && (set "BASE=py -3") || (set "BASE=python")

if not exist .venv\Scripts\python.exe (
    echo Creating the virtual environment .venv ...
    %BASE% -m venv .venv || goto :fail
)
echo Installing the dependencies (a few minutes the first time) ...
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet || goto :fail
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt || goto :fail

echo.
echo Done. Next steps:
echo   scripts\run_from_source.bat   start the application
echo   .venv\Scripts\python -m pytest   run the tests
echo   scripts\build_exe.bat         build the portable ConvertCAD.exe
echo In VS Code: "Python: Select Interpreter" and choose .venv.
pause
exit /b 0

:fail
echo.
echo SETUP FAILED - read the messages above.
pause
exit /b 1
