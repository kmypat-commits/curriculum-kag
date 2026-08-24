# Staging-релиз Curriculum-KAG

Документ описывает контролируемый staging, а не безусловный production-релиз.
Большие модели, PostgreSQL backup и EPVO-датасет не входят в Git-репозиторий и
передаются отдельными файлами с checksum.

## Перед запуском

1. Установить Docker Desktop и запустить Linux engine.
2. Скопировать `.env.production.example` в `.env.production` и заменить
   `POSTGRES_PASSWORD`, `SECRET_KEY`, домен и ключ LLM. Не публиковать заполненный
   файл.
3. Положить модель в `backend/models/epvo-sbert-finetuned-40k` или указать
   отдельный внутренний путь в `MODEL_DIR`.
4. Подготовить PostgreSQL backup и его manifest; не удалять исходный backup до
   успешного restore-проверочного прогона.

## Развёртывание

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml up -d postgres
docker compose --env-file .env.production -f docker-compose.production.yml run --rm backend alembic upgrade head
$env:DATABASE_URL = "postgresql+psycopg2://<user>:<password>@localhost:5433/<db>"
python backend/scripts/check_alembic_state.py
docker compose --env-file .env.production -f docker-compose.production.yml up -d backend frontend
```

После запуска выполнить read-only smoke для health, login, graph, coverage,
EPVO и всех трёх языков. Если PostgreSQL недоступен, релиз останавливается;
SQLite не является заменой production-режима.

## Проверки перед Git tag

```powershell
python backend/run_tests.py
python backend/scripts/ci_static_gate.py
python backend/scripts/check_dependency_profiles.py
python backend/scripts/check_release_hygiene.py
./scripts/verify-public-release.ps1
./scripts/build-staging-manifest.ps1
```

Тег создаётся только при чистом `git status`, успешном backup/restore,
`alembic` head, endpoint contracts и browser smoke. До этого версия считается
`staging-candidate`, а не production.

Для защиты от случайного тега используйте `powershell -File .\scripts\create-staging-tag.ps1 -Tag staging-YYYY.MM.DD[-suffix]`. Скрипт сам проверяет чистый worktree, manifest, последний restore-manifest, PostgreSQL на `5433` и UI smoke; при незапущенном PostgreSQL он завершает работу без создания тега.

## Откат

Остановить backend/frontend, сохранить логи и текущий manifest, восстановить
последний проверенный PostgreSQL backup в отдельную БД, затем вернуть предыдущий
Git tag. Пользовательские данные не удаляются автоматически.
