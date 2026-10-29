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
REM    - RapidOCR + PP-OCR models        Python packages
REM    - larger OCR models + Arabic      downloaded once into vendor\ocr_models
REM                                      (skip: set CONVERTCAD_NO_MODELS=1)
REM    - Tesseract OCR                   vendor\tesseract\ or an installed copy
REM  Optional code signing: see scripts\sign_windows.bat
REM ======================================================================
setlocal
cd /d "%~dp0\.."

if exist .venv\Scripts\python.exe (set "PY=.venv\Scripts\python.exe") else (set "PY=python")

echo [1/6] Installing build tools ...
%PY% -m pip install -r requirements-dev.txt --quiet
if errorlevel 1 goto :fail

echo [2/6] Running the tests ...
%PY% -m pytest -q
if errorlevel 1 goto :fail

echo [3/6] OCR models for "Maximum" and Arabic ...
if "%CONVERTCAD_NO_MODELS%"=="1" (
    echo     skipped ^(CONVERTCAD_NO_MODELS=1^)
) else (
    %PY% scripts\get_ocr_models.py
    if errorlevel 1 echo     WARNING: models not downloaded - "Maximum" will use the standard models.
)
if not exist "vendor\libredwg\win64\dxf2dwg.exe" (
    echo     WARNING: vendor\libredwg\win64\dxf2dwg.exe is missing - DWG output will be unavailable.
)

echo [4/6] Building (2 to 5 minutes) ...
%PY% scripts\make_icon.py
if errorlevel 1 goto :fail
if /i "%~1"=="onefile" (set "CONVERTCAD_ONEFILE=1") else (set "CONVERTCAD_ONEFILE=0")
%PY% -m PyInstaller --noconfirm --clean ConvertCAD.spec
if errorlevel 1 goto :fail

echo [5/6] Tesseract OCR and code signing ...
REM ---- Bundle Tesseract OCR (optional) so users have nothing to install.
REM      Source: vendor\tesseract\ if present, else the installed copy.
set "TESS="
if exist "vendor\tesseract\tesseract.exe" set "TESS=vendor\tesseract"
if not defined TESS if exist "%ProgramFiles%\Tesseract-OCR\tesseract.exe" set "TESS=%ProgramFiles%\Tesseract-OCR"
if not defined TESS goto :no_tess
if "%CONVERTCAD_ONEFILE%"=="1" goto :no_tess
echo     bundling Tesseract from "%TESS%"
robocopy "%TESS%" "dist\ConvertCAD\tesseract" /E /NFL /NDL /NJH /NJS /NP >nul
> "dist\ConvertCAD\tesseract\README-ConvertCAD.txt" echo Tesseract OCR - Apache License 2.0 - https://github.com/tesseract-ocr/tesseract
goto :tess_done
:no_tess
echo     Tesseract not bundled: "Fast - Tesseract" OCR will be unavailable
echo     (the other OCR engines are included).
:tess_done
if "%CONVERTCAD_ONEFILE%"=="1" (
    call scripts\sign_windows.bat "dist\ConvertCAD.exe"
    if errorlevel 1 goto :fail
) else (
    call scripts\sign_windows.bat "dist\ConvertCAD\ConvertCAD.exe" "dist\ConvertCAD\ConvertCAD-cli.exe" "dist\ConvertCAD\_internal\libredwg\dxf2dwg.exe" "dist\ConvertCAD\_internal\libredwg\dwg2dxf.exe"
    if errorlevel 1 goto :fail
)

echo [6/6] Packing the zip ...
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
    powershell -NoProfile -Command "Compress-Archive -Force -Path 'dist\ConvertCAD' -DestinationPath 'dist\ConvertCAD-%VER%-win64-portable.zip'"
    if errorlevel 1 goto :fail
    echo.
    echo SUCCESS: dist\ConvertCAD\ConvertCAD.exe  and  dist\ConvertCAD-%VER%-win64-portable.zip
)
echo.
echo Portable use: unzip anywhere (USB stick included). Put an empty file
echo named ConvertCAD.portable next to ConvertCAD.exe to keep the settings
echo in that folder instead of the user profile.
if not "%CONVERTCAD_NOPAUSE%"=="1" pause
exit /b 0

:fail
echo.
echo BUILD FAILED - read the messages above.
if not "%CONVERTCAD_NOPAUSE%"=="1" pause
exit /b 1
