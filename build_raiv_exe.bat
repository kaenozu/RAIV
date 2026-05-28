@echo off
REM build_raiv_exe.bat
REM Build RAIV as a normal Windows executable using PyInstaller (one-folder).
REM Why this exists: create a Python-free desktop app package for end users.
setlocal
cd /d "%~dp0"

set "PY_EXE="
set "PY_ARGS="
where py >nul 2>nul
if %errorlevel% equ 0 (
    set "PY_EXE=py"
    set "PY_ARGS=-3"
)
if not defined PY_EXE (
    where python >nul 2>nul
    if %errorlevel% equ 0 set "PY_EXE=python"
)
if not defined PY_EXE (
    if exist "%~dp0.venv\Scripts\python.exe" set "PY_EXE=%~dp0.venv\Scripts\python.exe"
)
if not defined PY_EXE (
    for /d %%D in ("%LocalAppData%\Programs\Python\Python*") do (
        if not defined PY_EXE if exist "%%~fD\python.exe" set "PY_EXE=%%~fD\python.exe"
    )
)

if not defined PY_EXE (
    echo Python was not found.
    echo Install Python 3.11+ or ensure python.exe is available on PATH.
    echo If Python is already installed, restart the terminal and run this script again.
    exit /b 1
)

echo Using Python command: %PY_EXE% %PY_ARGS%
echo Installing build dependencies...
"%PY_EXE%" %PY_ARGS% -m pip install --upgrade pip
if %errorlevel% neq 0 exit /b %errorlevel%
"%PY_EXE%" %PY_ARGS% -m pip install -r requirements.txt pyinstaller
if %errorlevel% neq 0 exit /b %errorlevel%

echo Building RAIV.exe...
"%PY_EXE%" %PY_ARGS% -m PyInstaller --noconfirm --clean --windowed --name RAIV --icon assets\app_icon.ico --add-data "assets;assets" --add-data "tools;tools" --add-data "README.md;." --add-data "LICENSE;." --collect-all PySide6 raiv.py
if %errorlevel% neq 0 exit /b %errorlevel%

if not exist "dist\RAIV" (
    echo Build output was not found: dist\RAIV
    exit /b 1
)

copy /Y "register_raiv_file_association.ps1" "dist\RAIV\register_raiv_file_association.ps1" >nul
if exist "dist\RAIV\RAIV.exe" (
    echo.
    echo Build succeeded.
    echo Output folder: dist\RAIV
    echo Executable: dist\RAIV\RAIV.exe
    echo.
    echo To register file association from the built app folder:
    echo   powershell -ExecutionPolicy Bypass -File dist\RAIV\register_raiv_file_association.ps1
    exit /b 0
)

echo Build finished but RAIV.exe was not found.
exit /b 1
