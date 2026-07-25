# PostgreSQL cutover checklist

Цель: перейти с локального SQLite/auto режима на PostgreSQL как основной рабочий режим без потери rollback-возможности.

## Текущий безопасный режим

Сейчас рекомендованный запуск:

```powershell
.\start.ps1 -Database postgres-shadow
```

SQLite остаётся резервной точкой:

```powershell
.\start.ps1 -Database sqlite
```

## Проверка готовности

Read-only проверка:

```powershell
C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe backend\scripts\prepare_postgres_cutover.py --output .runtime\postgres-cutover-readiness.json
```

Скрипт проверяет:

- наличие SQLite rollback-файла и его размер;
- наличие и успешность `.runtime/sqlite-postgres-counts-valid.json`;
- backend health;
- frontend health.

Скрипт ничего не меняет: не редактирует `.env`, не останавливает сервисы и не пишет в БД.

Глубокая проверка SQLite на 12 GB может идти долго. Её включать только отдельно:

```powershell
C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe backend\scripts\prepare_postgres_cutover.py --deep-sqlite-check
```

## Cutover

Если `ready_for_cutover=true`, рабочая команда:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\stop.ps1
.\start.ps1 -Database postgres-shadow
```

После проверки UI можно сделать PostgreSQL режимом по умолчанию через `.env` или отдельный `-Database postgres`.

## Rollback

Если после перехода что-то пошло не так:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\stop.ps1
.\start.ps1 -Database sqlite
```

## Что ещё нужно до окончательного production

1. Создать свежий restore-point перед окончательным переключением.
2. Проверить 3–5 программ разных уровней: бакалавриат, магистратура, докторантура.
3. Зафиксировать, где хранится PostgreSQL backup.
4. После cutover не удалять SQLite backup до завершения ручной проверки.
