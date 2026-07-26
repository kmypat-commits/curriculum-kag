# PostgreSQL primary cutover — 2026-07-26

## Итог

Локальный запуск переведён на PostgreSQL primary mode:

```powershell
.\start.ps1 -Database postgres
```

Для совместимости `postgres-shadow` пока оставлен как alias на ту же проверенную локальную базу:

```text
postgresql+psycopg2://curriculum_user:***@localhost:5433/curriculum_kag_shadow
```

SQLite остаётся rollback-точкой:

```powershell
.\start.ps1 -Database sqlite
```

## Restore-point

Создан лёгкий restore-point без дублирования 12GB SQLite и модели:

```text
backups/restore-point-2026-07-26_light-before-pg-primary.zip
```

Проверка архива:

```text
testzip = None
files = 190
large_state_included = false
sqlite = external_existing
```

## Readiness

`backend/scripts/prepare_postgres_cutover.py`:

```text
ready_for_cutover = true
postgres_count_compare_ok = true
backend_health_ok = true
frontend_health_ok = true
```

## Smoke после запуска `-Database postgres`

```text
backend health = 200
frontend health = 200
projects = 5
project 17 variants = 3
project 17 international quality = [100.0, 100.0, 100.0]
repository courses = 20789
graph nodes = 46
graph edges = 70
```

Время ответов:

```text
projects: 0.041 s
variants: 0.139 s
repository stats: 0.008 s
graph: 0.094 s
```

## Следующий шаг

Проверить свежую генерацию новой программы с нуля на PostgreSQL primary mode.
