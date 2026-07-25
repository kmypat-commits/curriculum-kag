@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
title EPVO - состояние загрузки

powershell.exe -NoProfile -Command "$all=12237; $p='experiment-results\epvo-full\raw\details'; $n=if(Test-Path $p){(Get-ChildItem $p -Filter '*.json').Count}else{0}; $pct=[math]::Round($n*100/$all,2); Write-Host ''; Write-Host ('Загружено карточек: {0} из {1} ({2}%%)' -f $n,$all,$pct); Write-Host ('Осталось: {0}' -f ($all-$n)); Write-Host ''"
pause
