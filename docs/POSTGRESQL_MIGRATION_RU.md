# План перехода SQLite → PostgreSQL/pgvector

Переезд нужен не “для красоты”, а чтобы большая база ЕПВО, embeddings и экспертные связи работали быстрее и стабильнее. Логика данных остаётся слоистой:

`raw EPVO → normalized EPVO → approved course repository → projects/LO → plans → feedback/audit`.

## Текущее состояние

Контроль на 25.07.2026:

- `backend/curriculum_kag.db`: около 11.45 GB;
- `courses`: 20 782;
- `course_localizations`: 62 346;
- `raw_epvo_disciplines`: 408 638;
- `raw_epvo_learning_outcomes`: 124 521;
- `raw_epvo_expert_checks`: 935 151;
- `epvo_disciplines_normalized`: 191 292;
- `epvo_discipline_lo_links`: 932 483;
- `embeddings`: 207 983;
- `plans`: 15.

Самые тяжёлые слои — raw EPVO, expert checks, discipline–LO links и embeddings. Их нельзя загружать в active repository “кашей”; raw и normalized остаются отдельными слоями.

## Что уже готово

- SQLAlchemy-конфигурация поддерживает SQLite и PostgreSQL через `DATABASE_URL`.
- Добавлен отдельный compose-файл: `docker-compose.postgres-only.yml`.
- Есть мигратор: `backend/scripts/migrate_sqlite_to_postgres.py`.
- Есть быстрый preflight SQLite: `backend/scripts/audit_sqlite_postgres_readiness.py`.
- Есть post-migration сравнение counts: `backend/scripts/compare_sqlite_postgres_counts.py`.
- Есть API-аудит контрольных программ, независимый от движка БД: `backend/scripts/audit_control_programs_api.py`.
- Создан быстрый backup:
  - `archive/backups_2026-08-01/baseline-2026-07-25_fast/curriculum_kag.db`;
  - `archive/backups_2026-08-01/baseline-2026-07-25_fast/manifest.json`;
  - размер backup DB: 12 296 245 248 bytes.

## Важный текущий статус

Docker Desktop установлен в пользовательский путь:

`C:\Users\User\AppData\Local\Programs\DockerDesktop`

В обычной PowerShell-сессии `docker` может быть не виден в `PATH`. Перед Docker-командами можно временно добавить CLI:

```powershell
$env:Path='C:\Users\User\AppData\Local\Programs\DockerDesktop\resources\bin;' + $env:Path
```

Shadow PostgreSQL/pgvector поднят и проверен:

- контейнер: `curriculum-kag-postgres-shadow`;
- порт: `5433`;
- состояние: healthy;
- расширение `vector`: доступно.

## Перед миграцией

Быстрый контроль SQLite:

```powershell
& 'C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' backend\scripts\audit_sqlite_postgres_readiness.py
```

Контроль сохранённых планов:

```powershell
& 'C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' backend\scripts\audit_plan_quality_sqlite.py --latest-per-version --limit 30
```

Старые планы с `feasible=False` не считать эталоном качества — их надо просто перегенерировать новой версией алгоритма.

## Shadow PostgreSQL

Запуск отдельного PostgreSQL/pgvector:

```powershell
docker compose -f docker-compose.postgres-only.yml up -d
```

Он поднимает только БД:

- host port: `5433`;
- database: `curriculum_kag_shadow`;
- user: `curriculum_user`;
- password: `curriculum_pass`.

Рабочий SQLite при этом не переключается.

## Перенос данных

```powershell
python backend\scripts\migrate_sqlite_to_postgres.py `
  --source sqlite:///D:/curriculum-kag/curriculum-kag/backend/curriculum_kag.db `
  --target postgresql+psycopg2://curriculum_user:curriculum_pass@localhost:5433/curriculum_kag_shadow
```

Мигратор:

- создаёт `vector` extension при доступности pgvector;
- создаёт схему из SQLAlchemy models;
- переносит таблицы батчами;
- проверяет, что target пустой перед копированием;
- сверяет количество строк;
- обновляет PostgreSQL sequences.

## Проверка после миграции

Сравнить ключевые таблицы:

```powershell
python backend\scripts\compare_sqlite_postgres_counts.py `
  --postgres postgresql+psycopg2://curriculum_user:curriculum_pass@localhost:5433/curriculum_kag_shadow `
  --output backend/experiment-results/postgres-shadow-counts.json
```

Затем поднять backend отдельно с shadow `DATABASE_URL` и прогнать API-аудит:

```powershell
python backend\scripts\audit_control_programs_api.py `
  --projects <id-бакалавр> <id-магистр> <id-доктор> `
  --base-url http://127.0.0.1:8000 `
  --output backend/experiment-results/postgres-shadow-control-audit.json
```

Сравниваем:

- проекты и версии;
- A/B/C планы;
- кредиты;
- LO coverage;
- пререквизиты;
- domain/admission guard;
- международный чек-лист;
- скорость страниц.

## Когда можно переключать основную систему

Только когда одновременно выполнено:

- counts SQLite/Postgres совпали по ключевым таблицам;
- нет FK-сирот;
- контрольные планы проходят без 500;
- качество планов не хуже SQLite;
- страницы открываются быстрее или хотя бы не медленнее;
- rollback проверен.

## Rollback

Если PostgreSQL ведёт себя иначе:

1. остановить запись в PostgreSQL-стенд;
2. вернуть старый `DATABASE_URL` на SQLite;
3. проверить backup SQLite;
4. оставить PostgreSQL как экспериментальный стенд до диагностики.
