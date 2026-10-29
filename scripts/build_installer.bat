@echo off
REM ======================================================================
REM  ConvertCAD - build the Windows INSTALLER (setup.exe)
REM
REM    scripts\build_installer.bat           uses dist\ConvertCAD\ if it
REM                                          exists, else builds it first
REM    scripts\build_installer.bat rebuild   always rebuilds the program
REM
REM  Result: dist\ConvertCAD-<version>-win64-setup.exe
REM
REM  Needs Inno Setup 6.3 or later (free):
REM      winget install JRSoftware.InnoSetup
REM  or  https://jrsoftware.org/isdl.php
REM
REM  The installer contains exactly the portable folder: DWG converter,
REM  OCR with its built-in model (other OCR languages are downloaded from
REM  the program). Users install nothing else and need no administrator
REM  rights. Optional code signing: see scripts\sign_windows.bat
REM ======================================================================
setlocal
cd /d "%~dp0\.."
set "OWN_NOPAUSE=%CONVERTCAD_NOPAUSE%"
if exist .venv\Scripts\python.exe (set "PY=.venv\Scripts\python.exe") else (set "PY=python")

REM ---- 1. the program (portable folder)
set "NEED_BUILD="
if /i "%~1"=="rebuild" set "NEED_BUILD=1"
if not exist "dist\ConvertCAD\ConvertCAD.exe" set "NEED_BUILD=1"
if defined NEED_BUILD (
    echo == Building the program first ...
    set "CONVERTCAD_NOPAUSE=1"
    call scripts\build_exe.bat
    if errorlevel 1 goto :fail
)

REM ---- 2. the Inno Setup compiler
set "ISCC="
for %%x in (ISCC.exe) do set "ISCC=%%~$PATH:x"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    echo ERROR: Inno Setup was not found. Install it with
    echo            winget install JRSoftware.InnoSetup
    echo        or from https://jrsoftware.org/isdl.php, then run this again.
    goto :fail
)

REM ---- 3. compile
for /f "delims=" %%v in ('%PY% -c "import convertcad; print(convertcad.APP_VERSION)"') do set "VER=%%v"
echo == Compiling the installer for ConvertCAD %VER% ...
"%ISCC%" /Q "/DAppVersion=%VER%" installer\ConvertCAD.iss
if errorlevel 1 goto :fail

REM ---- 4. optional code signing of the setup program
call scripts\sign_windows.bat "dist\ConvertCAD-%VER%-win64-setup.exe"
if errorlevel 1 goto :fail

echo.
echo SUCCESS: dist\ConvertCAD-%VER%-win64-setup.exe
if not "%OWN_NOPAUSE%"=="1" pause
exit /b 0

:fail
echo.
echo INSTALLER BUILD FAILED - read the messages above.
if not "%OWN_NOPAUSE%"=="1" pause
exit /b 1
