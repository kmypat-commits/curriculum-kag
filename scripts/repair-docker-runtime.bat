@echo off
setlocal
set "DOCKER_DESKTOP_BIN=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin"
if exist "%DOCKER_DESKTOP_BIN%\docker.exe" set "PATH=%DOCKER_DESKTOP_BIN%;%PATH%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0repair-docker-runtime.ps1"
set "REPAIR_EXIT=%errorlevel%"
if errorlevel 1 (
  echo.
  echo Docker runtime repair failed. Quit Docker Desktop, then run this file from the same user profile.
  pause
)
endlocal & exit /b %REPAIR_EXIT%
