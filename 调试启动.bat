@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
title Tongchuan - debug console

if exist "runtime\python.exe" (set PY=runtime\python.exe) else (set PY=.venv\Scripts\python.exe)
if not exist "%PY%" (
  echo [x] Python runtime not found in this folder.
  pause
  exit /b 1
)

"%PY%" -m app.main %*
echo.
echo ---- exited with code %errorlevel% ----
echo If it failed, see output\app.log and output\error.log
pause
