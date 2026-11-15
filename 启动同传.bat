@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
title Tongchuan

if exist "runtime\pythonw.exe" (
  start "" "runtime\pythonw.exe" -m app.main %*
  exit /b 0
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m app.main %*
  exit /b 0
)
echo [x] Python runtime not found in this folder.
echo     Copy the whole folder intact (do not copy only part of it).
pause
exit /b 1
