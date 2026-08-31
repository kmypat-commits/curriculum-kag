@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0repair-docker-runtime.ps1"
if errorlevel 1 (
  echo.
  echo Docker runtime repair failed. Run this file as Administrator and confirm UAC.
  pause
)
