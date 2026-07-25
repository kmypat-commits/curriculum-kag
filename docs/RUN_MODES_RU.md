# Режимы локального запуска Curriculum-KAG

## Обычный запуск

```powershell
.\start.ps1
```

Режим `auto`: скрипт берёт `DATABASE_URL` из окружения или `.env`. Если PostgreSQL недоступен, автоматически использует локальную SQLite-БД.

## Принудительно SQLite

```powershell
.\start.ps1 -Database sqlite
```

Используется файл:

```text
backend/curriculum_kag.db
```

Это быстрый rollback-режим, если PostgreSQL нужно временно отключить.

## Shadow PostgreSQL

```powershell
.\start.ps1 -Database postgres-shadow
```

Используется локальный PostgreSQL/pgvector контейнер:

```text
host: localhost
port: 5433
database: curriculum_kag_shadow
user: curriculum_user
```

Если контейнер недоступен, скрипт остановится с понятной ошибкой и предложит запустить Docker/PostgreSQL или использовать `-Database sqlite`.

## Полезные проверки

Сверка SQLite и PostgreSQL:

```powershell
$env:PYTHONPATH='D:\curriculum-kag\curriculum-kag\backend\venv\Lib\site-packages'
C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe backend\scripts\compare_sqlite_postgres_counts.py --sqlite backend\curriculum_kag.db --postgres postgresql+psycopg2://curriculum_user:curriculum_pass@localhost:5433/curriculum_kag_shadow
```

Мониторинг PostgreSQL activity:

```powershell
$env:PYTHONPATH='D:\curriculum-kag\curriculum-kag\backend\venv\Lib\site-packages'
C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe backend\scripts\monitor_postgres_migration.py --postgres postgresql+psycopg2://curriculum_user:curriculum_pass@localhost:5433/curriculum_kag_shadow
```
