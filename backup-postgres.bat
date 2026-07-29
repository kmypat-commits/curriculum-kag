@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup-postgres.ps1"
exit /b %errorlevel%
