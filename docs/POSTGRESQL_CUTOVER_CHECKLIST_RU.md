# PostgreSQL cutover checklist

Цель: перейти с локального SQLite/auto режима на PostgreSQL как основной рабочий режим без потери rollback-возможности.

## Текущий рабочий режим

PostgreSQL является основным рабочим режимом:

```powershell
.\start.ps1 -Database postgres
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

## Проверяемая резервная копия PostgreSQL

Создание custom-format дампа, manifest с SHA-256 и контрольными количествами строк:

```powershell
.\backup-postgres.ps1
```

Проверка выполняется настоящим восстановлением в отдельную временную БД. Основная БД не изменяется:

```powershell
.\verify-postgres-restore.ps1 -Manifest .\backups\postgres\<имя>.manifest.json
```

После успешной сверки manifest получает `restore_verified=true`, а временная БД удаляется.
Каталог `backups/` не включается в Git и должен храниться на резервном диске.

## Единая приёмочная проверка

После запуска приложения:

```powershell
.\acceptance-test.ps1 -RequireVerifiedBackup
```

Проверяются backend-тесты и кодировка исходников, подключение PostgreSQL,
контрольные программы всех уровней и варианты A/B/C, полнота RU/KK/EN,
отсутствие повреждённых описаний и production-сборка frontend.
