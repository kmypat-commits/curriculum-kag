# Восстановление Docker Desktop runtime

## Симптом

Docker Desktop завершается с ошибкой `Error 1920` для `sailor-ingest.sock`,
`dockerInference` или `docker-secrets-engine/engine.sock`. Это повреждённые
временные Windows runtime entries, а не повреждение PostgreSQL data disk.

## Границы данных

`D:\Docker\DockerDesktopWSL\disk\docker_data.vhdx` — data disk Docker. Его
нельзя удалять, перемещать или переименовывать при восстановлении runtime.

Удалению/пересозданию подлежат только ephemeral-каталоги:

- `C:\Users\User\AppData\Local\Docker\run`
- `C:\Users\User\AppData\Local\docker-secrets-engine`

## Процедура

1. Закрыть Docker Desktop через `Quit`, не нажимать `Reset to factory defaults`.
2. Запустить `start.bat`. Он поднимает весь стек одной командой и не
   очищает нормальные работающие socket-файлы.
3. Если остаётся Error 1920, выполнить точечный runtime repair из обычного
   PowerShell от имени того же пользователя, под которым запущен Docker
   Desktop:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\repair-docker-runtime.ps1 -NoStart
   ```

4. После успешного repair снова выполнить `start.bat`.
5. Проверить `docker version`, PostgreSQL `localhost:5433` и `/health`.

Repair не требует UAC: runtime namespace принадлежит интерактивному профилю
пользователя. Он сначала завершает Desktop/WSL, затем атомарно заменяет только
две перечисленные ephemeral-папки. Repair не должен останавливаться на
неопределённый срок и не изменяет VHDX, Docker volumes или database data root.
Если Windows удерживает папку даже после полного `Quit`, перезагрузите Windows
и повторите процедуру; не используйте factory reset.
