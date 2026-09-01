@echo off
chcp 65001 >nul
cd /d "%~dp0"
net session >nul 2>&1
if not errorlevel 1 goto :run
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b 0

:run
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -NoBrowser -Database postgres
if errorlevel 1 (
    echo.
    echo Launch failed. See the message above.
    pause
)
