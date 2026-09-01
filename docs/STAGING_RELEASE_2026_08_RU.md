# Staging-релиз Curriculum-KAG

Документ описывает контролируемый staging, а не безусловный production-релиз.
Большие модели, PostgreSQL backup и EPVO-датасет не входят в Git-репозиторий и
передаются отдельными файлами с checksum.

## Текущий staging-candidate (02.09.2026)

Создан локальный release-candidate tag `staging-2026.09.02-rc` на commit
`02944d4d63b59b0cbdb1e13098db89c18956bc68`. Перед созданием тега пройдены
PostgreSQL health/restore gates, UI smoke и ручная авторизованная проверка
графа проекта 13 с вариантами A/B и переключением на KK; ошибок интерфейса не
обнаружено.

Следующий внешний шаг — по отдельному разрешению владельца выполнить `git push`
ветки и тега в GitHub. До push модели, базы и backup остаются отдельными
артефактами и в обычный Git не добавляются.

Исторический baseline (25.08.2026):

Последний проверенный restore-manifest подтверждает совпадение SHA-256 и всех
контрольных таблиц PostgreSQL (20 проектов, 54 плана, 26 696 курсов,
935 151 экспертная проверка и 932 483 связи дисциплина–РО). Текущий контейнер
`curriculum-kag-postgres-shadow` здоров и доступен на `localhost:5433`; Alembic
указывает head `20260825_planner_read_indexes`. Read-only authenticated API
smoke графа проекта 13 вернул 51 узел и 84 ребра, а UI smoke проверил 10
маршрутов и маркеры RU/KK/EN. Git tag намеренно не создаётся до ручной проверки
графа и переключения языков в авторизованном браузере. Эта проверка выполнена
для текущего кандидата 02.09.2026.

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

Для защиты от случайного тега используйте `powershell -File .\scripts\create-staging-tag.ps1 -Tag staging-YYYY.MM.DD[-suffix] -BrowserSmokeVerified` после ручной проверки графа и RU/KK/EN в авторизованном браузере. Скрипт сам проверяет чистый worktree, manifest, последний restore-manifest, PostgreSQL на `5433` и UI smoke; без флага браузера или при незапущенном PostgreSQL он завершает работу без создания тега.

Для воспроизводимой API-проверки защищённого графа можно передать локальные
учётные данные только через переменные окружения:

```powershell
$env:CURRICULUM_KAG_SMOKE_EMAIL = "..."
$env:CURRICULUM_KAG_SMOKE_PASSWORD = "..."
.\scripts\authenticated-api-smoke.ps1 -ProjectVersionId 13
```

Этот smoke не сохраняет пароль и не заменяет ручную проверку отображения
графа и переключения RU/KK/EN в браузере.

## Откат

Остановить backend/frontend, сохранить логи и текущий manifest, восстановить
последний проверенный PostgreSQL backup в отдельную БД, затем вернуть предыдущий
Git tag. Пользовательские данные не удаляются автоматически.
