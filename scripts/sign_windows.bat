@echo off
REM ======================================================================
REM  sign_windows.bat FILE [FILE ...]  - Authenticode code signing
REM
REM  Signs the given .exe files when a code-signing certificate is set up,
REM  and does NOTHING otherwise (unsigned builds work; Windows SmartScreen
REM  then warns "unknown publisher" the first time users run them).
REM
REM  Certificate, one of:
REM    set CONVERTCAD_SIGN_PFX=C:\keys\convertcad.pfx      (certificate file)
REM    set CONVERTCAD_SIGN_PASSWORD=...                    (its password)
REM  or
REM    set CONVERTCAD_SIGN_THUMBPRINT=0123...ABCD          (certificate in the
REM                                                         Windows store or on
REM                                                         a USB token)
REM  Optional:
REM    set CONVERTCAD_SIGN_TIMESTAMP=http://timestamp.digicert.com  (default)
REM
REM  signtool.exe comes with the Windows SDK ("Windows SDK Signing Tools").
REM  See docs\PACKAGING.md, section "Code signing".
REM ======================================================================
setlocal
if "%~1"=="" exit /b 0
if not defined CONVERTCAD_SIGN_PFX if not defined CONVERTCAD_SIGN_THUMBPRINT (
    echo     code signing: no certificate configured - files left unsigned.
    exit /b 0
)

REM ---- find signtool.exe: PATH first, then the newest Windows SDK
set "SIGNTOOL="
for %%x in (signtool.exe) do set "SIGNTOOL=%%~$PATH:x"
if not defined SIGNTOOL (
    for /f "delims=" %%d in ('dir /b /ad /o-n "%ProgramFiles(x86)%\Windows Kits\10\bin\10.*" 2^>nul') do (
        if not defined SIGNTOOL if exist "%ProgramFiles(x86)%\Windows Kits\10\bin\%%d\x64\signtool.exe" set "SIGNTOOL=%ProgramFiles(x86)%\Windows Kits\10\bin\%%d\x64\signtool.exe"
    )
)
if not defined SIGNTOOL (
    echo ERROR: signtool.exe not found - install the Windows SDK signing tools.
    exit /b 1
)
set "TS=%CONVERTCAD_SIGN_TIMESTAMP%"
if not defined TS set "TS=http://timestamp.digicert.com"

echo     signing %*
if defined CONVERTCAD_SIGN_PFX goto :pfx
"%SIGNTOOL%" sign /fd sha256 /td sha256 /tr "%TS%" /d "ConvertCAD" /sha1 %CONVERTCAD_SIGN_THUMBPRINT% %* || exit /b 1
exit /b 0

:pfx
"%SIGNTOOL%" sign /fd sha256 /td sha256 /tr "%TS%" /d "ConvertCAD" /f "%CONVERTCAD_SIGN_PFX%" /p "%CONVERTCAD_SIGN_PASSWORD%" %* || exit /b 1
exit /b 0
