# Режимы локального запуска Curriculum-KAG

## Обычный запуск: PostgreSQL

```powershell
.\start.ps1
```

По умолчанию запускается PostgreSQL на `localhost:5433`. Если Docker или база
недоступны, запуск завершается понятной ошибкой: SQLite **не** выбирается
молча. Это защищает от работы со старой локальной копией данных.

После переноса Docker Desktop/WSL-диска launcher ждёт готовности daemon до 180
секунд, проверяя его раз в 5 секунд, а PostgreSQL — до 300 секунд. При особо
долгом восстановлении можно увеличить значения без правки кода:
`$env:DOCKER_DESKTOP_STARTUP_TIMEOUT_SECONDS=600`,
`$env:DOCKER_COMPOSE_STARTUP_TIMEOUT_SECONDS=600`,
`$env:POSTGRES_STARTUP_TIMEOUT_SECONDS=600`. Значения принимаются от 5 до
1800 секунд; некорректное значение останавливает запуск понятной ошибкой.

Для локального запуска используйте `start.bat` (или только
`docker compose -f docker-compose.postgres-only.yml up -d`). Не объединяйте
`docker-compose.yml` с `docker-compose.postgres-only.yml`: базовый файл является
production/local-конфигурацией и намеренно требует `POSTGRES_USER`,
`POSTGRES_PASSWORD` и `POSTGRES_DB` из `.env`; это не ошибка переноса VHDX.

## Принудительно SQLite

```powershell
.\start.ps1 -Database sqlite
```

Используется файл:

```text
backend/curriculum_kag.db
```

Это быстрый rollback-режим, если PostgreSQL нужно временно отключить.

## Диагностический auto-режим

```powershell
.\start.ps1 -Database auto
```

Этот режим сохраняется только для диагностики старых установок. Для обычной
работы и демонстраций используйте PostgreSQL по умолчанию.

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

## Основной PostgreSQL

```powershell
.\start.ps1 -Database postgres
```

Это основной локальный режим после миграции. Повторный запуск безопасен: launcher
проверяет уже работающий backend и не создаёт второй процесс. Если запрошен
PostgreSQL, а backend работает с SQLite, запуск остановится с понятной ошибкой
вместо ложного сообщения об успешном старте.

В production `ASYNC_BUILDS=true` запускает генерацию отдельным короткоживущим
worker-процессом: API сразу возвращает `202 queued`, а интерфейс получает
прогресс через `/build-status`. Для локальной диагностики можно оставить
`ASYNC_BUILDS=false` и выполнять тот же pipeline синхронно.

Быстрая проверка после запуска:

```powershell
.\smoke-test.ps1 -ExpectedDatabase postgresql
```

Или двойным щелчком:

```text
smoke-test.bat
```

Проверка подтверждает доступность backend, frontend-прокси, реальное соединение
backend с БД и используемый диалект `postgresql`. Эндпоинт `/health` выполняет
`SELECT 1`, поэтому зелёный статус теперь означает не только работающий HTTP,
но и доступную базу данных.

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
