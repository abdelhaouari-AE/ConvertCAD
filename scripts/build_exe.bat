@echo off
REM ======================================================================
REM  ConvertCAD - build the PORTABLE Windows application
REM
REM    scripts\build_exe.bat           dist\ConvertCAD\ConvertCAD.exe
REM                                    (folder - starts fast, recommended)
REM    scripts\build_exe.bat onefile   dist\ConvertCAD.exe
REM                                    (single file - slower to start)
REM
REM  Result: the folder (or exe) + a ready-to-share zip in dist\.
REM  Nothing is installed on the target computer; no admin rights needed.
REM  For the INSTALLER (setup.exe), run scripts\build_installer.bat instead
REM  (it calls this script first).
REM
REM  Included automatically:
REM    - GNU LibreDWG (DWG output)       vendor\libredwg\win64 (in the repo)
REM    - RapidOCR + the built-in OCR     Python packages (English, French
REM      model                           and the other Latin languages)
REM  Other OCR languages and the maximum accuracy models are NOT bundled:
REM  users download them from the program (Settings > Scanned pages).
REM  Offline build: put them in vendor\ocr_models first
REM  (python scripts\get_ocr_models.py --all --dest vendor\ocr_models).
REM  Optional code signing: see scripts\sign_windows.bat
REM ======================================================================
setlocal
cd /d "%~dp0\.."

if exist .venv\Scripts\python.exe (set "PY=.venv\Scripts\python.exe") else (set "PY=python")

echo [1/5] Installing build tools ...
REM exact versions of requirements-lock.txt (see CLAUDE.md, "Dependencies")
%PY% -m pip install -r requirements-dev.txt -c requirements-lock.txt --quiet
if errorlevel 1 goto :fail
%PY% scripts\check_lock.py
if errorlevel 1 goto :fail

echo [2/5] Running the tests ...
%PY% -m pytest -q
if errorlevel 1 goto :fail

echo [3/5] Building (2 to 5 minutes) ...
if not exist "vendor\libredwg\win64\dxf2dwg.exe" (
    echo     WARNING: vendor\libredwg\win64\dxf2dwg.exe is missing - DWG output will be unavailable.
)
%PY% scripts\make_icon.py
if errorlevel 1 goto :fail
if /i "%~1"=="onefile" (set "CONVERTCAD_ONEFILE=1") else (set "CONVERTCAD_ONEFILE=0")
REM fixed hash seed: two builds of the same code give identical files
set "PYTHONHASHSEED=0"
%PY% -m PyInstaller --noconfirm --clean ConvertCAD.spec
if errorlevel 1 goto :fail
set "PYTHONHASHSEED="

echo [4/5] Code signing ...
if "%CONVERTCAD_ONEFILE%"=="1" (
    call scripts\sign_windows.bat "dist\ConvertCAD.exe"
    if errorlevel 1 goto :fail
) else (
    call scripts\sign_windows.bat "dist\ConvertCAD\ConvertCAD.exe" "dist\ConvertCAD\ConvertCAD-cli.exe" "dist\ConvertCAD\_internal\libredwg\dxf2dwg.exe" "dist\ConvertCAD\_internal\libredwg\dwg2dxf.exe"
    if errorlevel 1 goto :fail
)

echo [5/5] Packing the zip ...
for /f "delims=" %%v in ('%PY% -c "import convertcad; print(convertcad.APP_VERSION)"') do set "VER=%%v"
if "%CONVERTCAD_ONEFILE%"=="1" (
    powershell -NoProfile -Command "Compress-Archive -Force -Path 'dist\ConvertCAD.exe','README.md','LICENSE','THIRD_PARTY_NOTICES.md' -DestinationPath 'dist\ConvertCAD-%VER%-win64-onefile.zip'"
    if errorlevel 1 goto :fail
    echo.
    echo SUCCESS: dist\ConvertCAD.exe  and  dist\ConvertCAD-%VER%-win64-onefile.zip
) else (
    copy /y README.md dist\ConvertCAD\ >nul
    copy /y LICENSE dist\ConvertCAD\ >nul
    copy /y THIRD_PARTY_NOTICES.md dist\ConvertCAD\ >nul
    copy /y CHANGELOG.md dist\ConvertCAD\ >nul
    copy /y PRIVACY.md dist\ConvertCAD\ >nul
    copy /y CODE_SIGNING.md dist\ConvertCAD\ >nul
    REM list of files with their checksums (small updates): last, folder final
    %PY% scripts\make_manifest.py dist\ConvertCAD
    if errorlevel 1 goto :fail
    powershell -NoProfile -Command "Compress-Archive -Force -Path 'dist\ConvertCAD' -DestinationPath 'dist\ConvertCAD-%VER%-win64-portable.zip'"
    if errorlevel 1 goto :fail
    echo.
    echo SUCCESS: dist\ConvertCAD\ConvertCAD.exe  and  dist\ConvertCAD-%VER%-win64-portable.zip
)
echo.
echo Portable use: unzip anywhere (USB stick included). Put an empty file
echo named ConvertCAD.portable next to ConvertCAD.exe to keep the settings
echo and the downloaded OCR models in that folder instead of the user profile.
if not "%CONVERTCAD_NOPAUSE%"=="1" pause
exit /b 0

:fail
echo.
echo BUILD FAILED - read the messages above.
if not "%CONVERTCAD_NOPAUSE%"=="1" pause
exit /b 1
