@echo off
REM run_raiv.bat
REM RAIV を起動するバッチファイル。コマンドウィンドウを表示する。
REM なぜ存在するか: ユーザーが簡単にアプリを起動できるようにするため。
REM 関連ファイル: raiv.py, run_raiv.vbs, install_support.bat
setlocal
cd /d "%~dp0"

where pyw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pyw "%~dp0raiv.py"
    exit /b 0
)

where pythonw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pythonw "%~dp0raiv.py"
    exit /b 0
)

py "%~dp0raiv.py"
if %errorlevel% equ 0 exit /b 0
python "%~dp0raiv.py"
