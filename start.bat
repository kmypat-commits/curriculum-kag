@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "DOCKER_DESKTOP_BIN=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin"
if exist "%DOCKER_DESKTOP_BIN%\docker.exe" set "PATH=%DOCKER_DESKTOP_BIN%;%PATH%"
rem Docker Desktop and its AF_UNIX runtime sockets belong to this user profile.
rem Do not elevate the launcher: an elevated token can recreate `run` with
rem ownership different from the Desktop process and trigger Error 1920.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Database postgres -RestartBackend -RestartFrontend
if errorlevel 1 (
    echo.
    echo Launch failed. See the message above.
    pause
)
