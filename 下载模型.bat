@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Downloading faster-whisper-large-v3-turbo from ModelScope ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\download_model.ps1"
echo.
pause
