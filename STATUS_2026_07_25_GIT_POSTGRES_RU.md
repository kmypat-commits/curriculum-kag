# Статус: Git-версии и PostgreSQL shadow

Дата: 2026-07-25

## Сделано

- Инициализирован локальный Git-репозиторий проекта.
- Создан первый локальный baseline-коммит.
- Добавлена страница приложения «Версии проекта».
- Добавлен backend API `/git` для просмотра:
  - текущей ветки;
  - состояния рабочей копии;
  - изменённых файлов;
  - последних 20 коммитов;
  - diff выбранного коммита;
  - сравнения коммита с текущей версией;
  - создания новой ветки от выбранного коммита.
- Diff в UI ограничен по размеру, чтобы большой вывод Git не подвешивал браузер.
- Docker Desktop проверен, shadow PostgreSQL/pgvector запущен на порту `5433`.
- Запущена фоновая миграция SQLite → PostgreSQL shadow.
- Добавлен лёгкий монитор миграции:
  `backend/scripts/monitor_postgres_migration.py`.

## Проверено

- `docker compose -f docker-compose.postgres-only.yml config --quiet` — успешно.
- PostgreSQL контейнер `curriculum-kag-postgres-shadow` — healthy.
- `py_compile` для Git API и миграционных скриптов — успешно.
- Frontend production build — успешно.
- Генерация проблемного проекта `Киберследователь` больше не падает с `list.remove(x): x not in list`.
- После ремонта доменных квот план для проекта 15 формируется с `hard=0`.

## Текущий процесс

- Миграция SQLite → PostgreSQL shadow выполняется в фоне.
- Лог миграции:
  `.runtime/postgres-migration.combined.log`.
- Прогресс можно смотреть командой:

```powershell
$env:PYTHONPATH='D:\curriculum-kag\curriculum-kag\backend\venv\Lib\site-packages'
C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe backend\scripts\monitor_postgres_migration.py --postgres postgresql+psycopg2://curriculum_user:curriculum_pass@localhost:5433/curriculum_kag_shadow
```

## Следующие шаги

1. Дождаться завершения миграции.
2. Сверить количество строк SQLite и PostgreSQL.
3. Запустить backend на shadow PostgreSQL.
4. Проверить основные API: health, projects, variants, LO coverage, EPVO compare, генерация плана.
5. После успешной проверки решить, когда переключать PostgreSQL как основную БД.

## Риск

- `.env` содержит локальные настройки и не должен попадать в Git.
- Shadow PostgreSQL пока не считается основной БД до завершения сверки counts и API-smoke.
