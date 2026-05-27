@echo off
REM register_raiv_file_association.bat
REM Register RAIV as a handler for supported image/archive extensions (current user).
REM Why this exists: make RAIV available for Open With and default app selection.
setlocal
cd /d "%~dp0"

set "RAIV_PROGID=RAIV.Image"
set "RAIV_EXE=%~dp0RAIV.exe"
if exist "%RAIV_EXE%" (
    set "RAIV_CMD=\"%RAIV_EXE%\" \"%%1\""
) else (
    set "RAIV_CMD=wscript.exe \"%~dp0run_raiv.vbs\" \"%%1\""
)
set "EXTENSIONS=.png .jpg .jpeg .webp .bmp .gif .zip .cbz .rar .cbr .7z .cb7"

echo Registering RAIV file association for current user...
echo.

reg add "HKCU\Software\Classes\%RAIV_PROGID%" /ve /t REG_SZ /d "RAIV Image Viewer" /f >nul
if errorlevel 1 goto :failed
reg add "HKCU\Software\Classes\%RAIV_PROGID%\shell\open\command" /ve /t REG_SZ /d "%RAIV_CMD%" /f >nul
if errorlevel 1 goto :failed

for %%E in (%EXTENSIONS%) do (
    reg add "HKCU\Software\Classes\%%E\OpenWithProgids" /v "%RAIV_PROGID%" /t REG_NONE /d "" /f >nul
    reg add "HKCU\Software\Classes\%%E" /ve /t REG_SZ /d "%RAIV_PROGID%" /f >nul
)

echo Done.
echo RAIV has been registered for: %EXTENSIONS%
echo.
echo NOTE:
echo - On modern Windows, the final default-app decision may still require one-time confirmation in Settings.
echo - Opening Default apps now...
start "" ms-settings:defaultapps
echo.
echo In Settings, choose default apps by file type and set RAIV for the extensions you want.
exit /b 0

:failed
echo Failed to write registry entries.
echo Try running this file again from a normal user account with registry write permission.
exit /b 1
