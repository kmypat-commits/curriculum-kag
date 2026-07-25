@echo off
cd /d "%~dp0backend"
title EPVO dataset download

echo ============================================================
echo EPVO public educational-program download
echo ============================================================
echo Keep this window open. You may minimize it.
echo If the connection fails, run download_epvo.bat again.
echo Existing detail files will be skipped automatically.
echo.

if not exist "venv\Scripts\python.exe" goto missing_python

"venv\Scripts\python.exe" -u "scripts\collect_epvo_dataset.py" --output "experiment-results\epvo-full" --details-only --details-limit 0 --delay 1.5

if errorlevel 1 goto interrupted
echo.
echo COMPLETE: all available EPVO cards were downloaded.
pause
exit /b 0

:missing_python
echo ERROR: backend\venv Python environment was not found.
echo Run start.bat first.
pause
exit /b 1

:interrupted
echo.
echo Download stopped. Saved data is safe.
echo Run this file again to continue.
pause
exit /b 1
