@echo off
REM register_raiv_file_association.bat
REM Register RAIV as a handler for supported image/archive extensions (current user).
REM Why this exists: make RAIV available for Open With and default app selection.
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register_raiv_file_association.ps1"
exit /b %errorlevel%
