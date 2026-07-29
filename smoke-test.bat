@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0smoke-test.ps1" -ExpectedDatabase postgresql
exit /b %errorlevel%
