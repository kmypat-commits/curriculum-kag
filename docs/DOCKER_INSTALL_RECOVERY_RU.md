# Восстановление Docker Desktop без потери данных

Этот сценарий нужен, если `docker.exe` существует, но `Docker Desktop.exe`
отсутствует, а `docker desktop start` отвечает, что Desktop не запущен.

## Перед установкой

Не нажимайте **Reset to factory defaults** и не удаляйте VHDX.
Проверьте сохранённый образ:

```powershell
$vhdx = 'D:\Docker\DockerDesktopWSL\disk\docker_data.vhdx'
Get-Item -LiteralPath $vhdx | Select-Object FullName,Length,LastWriteTime
```

Ожидаемый persistent data root проекта: `D:\Docker\DockerDesktopWSL`.
Временные runtime-сокеты под `%LOCALAPPDATA%\Docker\run` не являются базой
данных и могут быть пересозданы.

## Восстановление

1. Установите или выполните Repair Docker Desktop штатным установщиком.
2. Запустите Docker Desktop и в настройках **Resources → Advanced** укажите
   существующий disk image location, содержащий `docker_data.vhdx`.
3. Дождитесь состояния **Engine running**. Не создавайте новый factory reset
   data store поверх существующего образа.
4. Выполните read-only проверки:

```powershell
$docker = 'C:\Users\User\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker version
& $docker ps
Test-NetConnection 127.0.0.1 -Port 5433
```

5. Из каталога проекта выполните one-command smoke:

```powershell
Set-Location 'D:\curriculum-kag\curriculum-kag'
& .\scripts\repair-docker-runtime.ps1 -NoStart
& .\start.ps1 -NoBrowser -Database postgres
& .\scripts\monitor-health.ps1 -BackendUrl 'http://127.0.0.1:8000/health' -FrontendUrl 'http://127.0.0.1:3001/' -CheckDocker
```

Успешный результат должен содержать `Healthy: backend, frontend, PostgreSQL`.
Если PostgreSQL недоступен, launcher в режиме `postgres` должен завершиться с
ошибкой, а не молча переключиться на SQLite.

## После восстановления

Проверьте, что образ остался на D:

```powershell
Get-Item -LiteralPath 'D:\Docker\DockerDesktopWSL\disk\docker_data.vhdx' |
    Select-Object FullName,Length,LastWriteTime
```

Затем повторите backup/restore smoke и только после этого запускайте staging
acceptance. Runtime repair проекта запускается от обычного интерактивного
пользователя, удаляет только временные сокеты и никогда не изменяет VHDX.
