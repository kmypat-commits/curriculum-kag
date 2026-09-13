# Аудит Curriculum-KAG: gap register

Дата: 2026-09-03
Режим: read-only аудит текущего репозитория; в этом проходе функциональность не менялась.

## Итог

Система уже имеет признаки production-grade разработки: объектная авторизация, RBAC, cookie/CSRF-контур, PostgreSQL как основной режим, Alembic, сохранение статусов долгих сборок, инварианты учебного плана, локализация RU/KK/EN, тесты API и acceptance-когорта. Локальный Docker/PostgreSQL runtime подтверждён; оставшиеся пробелы относятся к миграционному cutover, независимой экспертной оценке и deployment-level доказательствам.

Оценка технического health score для UI-кода: **15/20, Good с остаточными задачами по широкому viewport/a11y проходу и декомпозиции крупных страниц**. Оценка подтверждена code scan, production build и локальным authenticated smoke.

| Область | Балл | Вывод |
|---|---:|---|
| Accessibility | 3/4 | Есть axe/auth smoke и локализация, но нужен живой keyboard/mobile проход на всех крупных экранах |
| Performance | 3/4 | Есть bounded polling, gzip и telemetry; остаются крупные страницы и layout-transition |
| Theming/i18n | 2/4 | RU/KK/EN покрыты gate-ами, но detector находит локальные hard-coded визуальные паттерны |
| Responsive | 2/4 | Тесты не дают достаточного доказательства всех узких viewport/длинных переводов |
| Implementation integrity | 3/4 | Система предметно согласована; несколько повторяемых UI-паттернов выглядят как временные заплатки |

## Критические пробелы и задачи

### P0 — блокирует подтверждение внедрения

#### AUD-DOCKER-001 — Docker Desktop runtime подтверждён; нужна регрессия после перезагрузки

- **Место:** `start.ps1:214-230, 245-306`, `scripts/repair-docker-runtime.ps1:8-20`.
- **Факт:** ошибки были вызваны повреждёнными reparse/runtime-ссылками в C: (`sailor-ingest.sock`, `dockerInference`, `docker-secrets-engine/engine.sock`), а не возвратом VHDX с D:. Runtime-каталоги ротированы в резервные `.stale-*`, Docker Desktop `29.7.2`, PostgreSQL healthy на `127.0.0.1:5433`, backend/frontend health и штатный launcher подтверждены 2026-09-04.
- **Риск:** остаётся только регрессионная проверка после полного выхода/перезагрузки; данные проекта и VHDX не затронуты.
- **Задачи:**
  1. Повторить `start.bat` после следующей перезагрузки Windows.
  2. При stale runtime запускать `scripts/repair-docker-runtime.ps1`; скрипт ротирует только ephemeral namespaces.
  3. Периодически проверять `docker version`, порт 5433, `/health` и генерацию.

#### AUD-DATA-001 — SQLite → PostgreSQL не закрыт как cutover

- **Место:** `.runtime/sqlite-orphan-review-archive-20260903.json`, `docs/POSTGRESQL_MIGRATION_RU.md`.
- **Факт:** в legacy SQLite обнаружено 205222 orphan FK (основная масса — embeddings и match_scores). Manifest fail-closed и restore verification есть, но это ещё не доказательство полной миграции данных.
- **Риск:** часть старых связей будет намеренно отброшена или архивирована; без подписанного решения владельца данных нельзя утверждать эквивалентность SQLite и PostgreSQL.
- **Задачи:** согласовать discard/archive policy по каждой таблице, сравнить counts/checksums по разрешённым сущностям, выполнить staging cutover и rollback drill, затем подписать acceptance.

### P1 — исправить до staging/release candidate

#### AUD-OPS-001 — локальный compose требует явной конфигурации

- **Место:** `docker-compose.yml:7-10, 28-41`.
- **Факт:** production compose требует password и secret из `.env`; local compose использует явно помеченные development-only defaults и `APP_ENV=local`. `--reload` остаётся только в локальном compose.
- **Риск:** оператору всё ещё нужно не перепутать local compose с production compose.
- **Задачи:** сохранить разделение compose-файлов в runbook и проверять `APP_ENV`/секреты перед staging-запуском; production compose уже требует секреты.

#### AUD-SEC-001 — fallback demo password в служебных аудитах

- **Место:** `backend/scripts/audit_control_programs_api.py:29-32`, `backend/scripts/run_plan_build_api.py:35-40`, `start.ps1`; аналогичные smoke scripts.
- **Факт:** fallback `admin123` удалён из служебных API/smoke-скриптов и launcher; credentials теперь обязательны через environment и не печатаются при старте.
- **Риск:** оператор может случайно проверить staging/production demo-учёткой; секрет попадает в командный сценарий и снижает доверие к security review.
- **Задачи:** проверить аналогичные legacy seed-сценарии и ограничить `ALLOW_DEMO_SEED=true` только local/test; два найденных legacy seed теперь требуют этот флаг и `CURRICULUM_LOCAL_PASSWORD`.

#### AUD-SEC-002 — долгоживущий JWT для CLI требует операционного контроля

- **Место:** `backend/app/config.py:14-18, 57-60`, `backend/app/api/auth.py:83-90`.
- **Факт:** CLI token использует отдельный TTL 60 минут (production ограничен 1–240 минутами); JWT маркируется `token_use`, канал проверяется, `/auth/token/revoke` инвалидирует все старые CLI-токены пользователя через persisted `cli_token_version`, а выдача/отзыв пишутся в audit events без token material.
- **Риск:** токен, выданный после последнего revoke, действителен до истечения TTL; logout браузера CLI-токены не отзывает.
- **Задачи:** добавить аудит выдачи/отзыва и документировать хранение токена/service-account policy.

#### AUD-QA-001 — acceptance качества содержит stale/incomplete 50-case evidence и не содержит независимого экспертного agreement

- **Место:** `.runtime/quality-cohort-final-50.json`, `.runtime/quality-cohort-breadth-post-domain-fix-20260903.json` и quality scripts.
- **Факт:** отдельный breadth evidence зафиксирован как 30/30. `.runtime/quality-cohort-final-50.json` имеет `status=running`, `completed=14`, `requested=50`, текущий case №15 с timestamp 2026-09-02; живого Python-процесса сейчас не видно, поэтому 50-case acceptance не считаю завершённым. Отдельный runtime artifact `quality-cohort-runtime-20260903.json` содержит 1/5 passed, но его 4 failures относятся к старой версии `schedule_fingerprint` до фикса mixed real/bridge sorting; текущий regression-тест этот случай проходит. Требование двух независимых экспертов и agreement score также не закрыто evidence-файлом.
- **Задачи:** закрыть stale progress-файл отдельным resume/новым run после восстановления Docker; progress-файл теперь сохраняет `runner_pid` и `recovered_from_stale`, чтобы отличать живой долгий run от умершего процесса. Acceptance runner исправлен на явный `--cohort breadth`; далее сформировать 30–50 уникальных программ по уровням, ослепить два набора reviewer IDs, оценить credits/ГОСО/prerequisites/семестры/relevance/bridge, посчитать agreement и сохранить протокол.

#### AUD-OBS-001 — telemetry есть, alerting/retention deployment-level не доказаны

- **Место:** `backend/app/api/planner_build.py:80-116`, `scripts/monitor-staging-observability.ps1`.
- **Факт:** duration/query count/cache fields и aggregate summary реализованы; монитор bounded. Но нет доказательства, что staging реально запускает alert при p95 budget breach, stale lease и backup age breach.
- **Задачи:** подключить scheduler/CI job, проверить exit codes и уведомление на synthetic breach, запустить retention purge, задокументировать TTL и ownership дашборда.

#### AUD-REF-001 — крупные backend/frontend модули остаются зонами риска

- **Факт:** `backend/app/planner/scheduler.py` ~66.7 KB, `backend/app/planner/variant_strategy.py` ~52.2 KB, `backend/app/api/epvo.py` ~51.6 KB, `frontend/src/translations.js` ~123 KB, `PlanBuilder.jsx` ~56.9 KB.
- **Риск:** изменения трудно ревьюить, выше вероятность скрытых условий и регрессий локализации/качества.
- **Задачи:** выделить bounded modules: domain rules, persistence, orchestration, transport; для каждого оставить contract tests и dependency graph. Не делать механическое дробление ради размера.

### P2 — следующая hardening-итерация

#### AUD-UI-001 — detector находит повторяемые AI-like визуальные паттерны (закрыто для текущего дерева)

- **Место:** `frontend/src/components/CompactSection.jsx:13`, `PlanBuildProgress.jsx:16,31`, `frontend/src/index.css:89`, `CourseSyllabus.jsx:129`, `EpvoComparison.jsx:206,236`, `LOCoverageDashboard.jsx:306,391,408,419,633`, `PlanBuilder.jsx:701,714,739`, `PrerequisiteGraph.jsx:205`, `ProjectDetails.jsx:162`.
- **Факт:** detector ранее давал 16 предупреждений. Повторная проверка текущего дерева `frontend/src` от 2026-09-04 возвращает `[]`; `transition: width` и повторяемые толстые `border-left/right`-акценты удалены. Для motion сохранён `prefers-reduced-motion`.
- **Риск:** остаётся отдельная acceptance-проверка графа на больших данных; это функционально-производительный риск и не является текущим detector-дефектом.
- **Задачи:** закрыты в рамках текущего UI-прохода; повторить visual smoke после следующего крупного изменения визуальных компонентов.

#### AUD-I18N-001 — локализацию нужно доказать не только ключами

- **Факт:** i18n gate проходит, но длинные KK/RU строки и fallback-paths не подтверждены на узких viewport.
- **Задачи:** runtime scan всех маршрутов в RU/KK/EN, поиск отображаемых source-language строк, screenshot/keyboard pass при 320/768/1440 px, проверка plural/number/date formatting.

#### AUD-GRAPH-001 — граф требует отдельного acceptance на больших данных

- **Задачи:** проверить 0/1/1000+ узлов, циклы, отсутствующие prerequisites, bridge-only nodes, zoom/keyboard/focus, экспорт и понятное объяснение ошибок; замерить render time и memory.

## Что уже выглядит надёжно

- Access audit: 90 routes, 46 object-scoped, 0 найденных незащищённых object routes.
- RBAC/ownership, safe errors, secure cookie + CSRF контур и production validation присутствуют.
- Backend test inventory: **173 tests**, полный regression в этом проходе завершился успешно (`[100%]`); access/profile layer 24/24, compose-security и CLI-revoke tests, а также static quality gate проходят.
- CI дополнен secret-hygiene gate: tracked files проверяются на private-key/API-token signatures; `.env` остаётся ignored и не попадает в release.
- Миграция `cli_token_version` оставляет server default `0`, чтобы не использовать несовместимый с SQLite `ALTER COLUMN` в rollback/development-пути.
- Обе новые миграции rate-limit/token-version теперь не удаляют объекты, которые могли быть созданы baseline metadata bootstrap при downgrade.
- Чистая SQLite migration chain вынесена в `backend/scripts/check_sqlite_migrations.py` и подключена к CI.
- Frontend gates: **8/8 Vitest**, i18n inline-language `0`, graph style gate passed, production Vite build passed.
- GOSO ruleset versioned, профили Bachelor/Master/Doctorate и инварианты плана покрыты тестами; добавлены явные проверки international master 60/90/120 и запрет master-volume shortcuts для doctorate. Wizard теперь показывает оба doctorate track и выбирает объём через тот же backend profile endpoint; endpoint профилей получил typed response model и отражается в OpenAPI.
- 30/30 breadth — сильное автоматическое основание для дальнейшего экспертного acceptance; stale 50-case artifact неполон (14/50), а 5-case runtime artifact требует повторного запуска после фикса mixed real/bridge fingerprint.
- Restore drill PostgreSQL повторно подтверждён на рабочем Docker host 2026-09-04: backup 2026-09-03, SHA-256 verified, critical table counts совпали, mismatches=0; временная restore-БД удалена. SQLite migration chain также повторно прошла до Alembic head. Read-only compare canonical SQLite (`backend/curriculum_kag.db`, 12.3 GB) против текущего shadow зафиксировал 205222 legacy FK violations: EPVO source counts совпадают, app tables отличаются по снимку, а `bridge_modules` (115 нарушений) и `match_feedback` (2 уникальные строки/4 FK-ссылки) требуют owner decision. Полный data cutover всё ещё требует согласованной orphan discard/archive policy и rollback acceptance.

## Краткое описание системы

Curriculum-KAG — web-система для проектирования учебных планов. Frontend на React/Vite предоставляет wizard, repository/EPVO, plan builder, prerequisite graph, LO coverage и research/observability экраны на RU/KK/EN. Backend на FastAPI принимает запросы, выполняет RBAC/ownership checks, извлекает дисциплины из PostgreSQL/EPVO evidence repository, ранжирует кандидатов и строит варианты плана с учётом кредитов, ГОСО, prerequisites, семестров и bridge modules. Долгие сборки имеют durable status/lease/heartbeat/cancel/retry/idempotency; telemetry пишет компактные технические показатели. PostgreSQL — основной режим; SQLite оставлен как явный rollback/development режим. Docker Compose поднимает PostgreSQL и backend/frontend, production-вариант добавляет pinned images, non-root/limits через compose policy и Caddy TLS edge.

## Уровень для одного разработчика

По объёму это высокий уровень: фактически full-stack продукт с domain engine, миграцией данных, ML/EPVO контуром, RBAC, i18n, observability, QA и release hygiene. Для одного разработчика это сильный результат уровня senior+/staff по широте ответственности. До enterprise-ready не хватает не «ещё фич», а эксплуатационных доказательств: стабильный Docker host, подписанный data cutover, независимая экспертная оценка, реальные alerts/retention и повторяемый staging acceptance.

## Приоритетный порядок работ

1. **AUD-DOCKER-001** — проверить исправленный видимый elevation/UAC путь и доказать one-command startup.
2. **AUD-DATA-001** — закрыть policy orphan data и staging rollback.
3. **AUD-SEC-001/002** — проверить legacy demo seed и определить CLI token lifecycle; API audit fallbacks уже убраны.
4. **AUD-QA-001** — возобновить/перезапустить stale 50-case cohort и провести независимый экспертный agreement.
5. **AUD-OBS-001** — активировать и проверить alerts/retention.
6. **AUD-REF-001** — рефакторинг крупных модулей через bounded contexts и contract tests.
7. **AUD-I18N-001/AUD-GRAPH-001** — финальный UI/i18n/graph pass; AUD-UI-001 закрыт detector-проверкой 2026-09-04.

## Статус семи целей

1. Docker/PostgreSQL one-command — **локальное runtime acceptance пройдено 2026-09-04**; остаётся только регрессия после перезагрузки и staging/production-host evidence.
2. Генерация разных уровней — **автотесты и cohort пройдены**, real Docker rerun нужен.
3. UI/граф/RU-KK-EN/дубли/объяснения — **frontend gates и authenticated cookie/CSRF+a11y smoke пройдены**, остаётся широкий graph/i18n viewport pass.
4. SQLite→PostgreSQL/backup — **restore подтверждён**, полный migration cutover не закрыт из-за orphan policy.
5. Качество планов — **автоматические инварианты и 30/30 есть**, 5-case runtime artifact устарел относительно текущего fingerprint fix, расширенный 50-case прогон stale на 14/50, независимый экспертный agreement отсутствует.
6. Senior-refactoring — **частично**, крупные модули ещё требуют выделения bounded contexts.
7. Telemetry — **реализована**, deployment alerting/retention evidence ещё не закрыты.

## Addendum 2026-09-04

- Docker Desktop daemon `29.7.2` подтверждён; `curriculum-kag-postgres-shadow` работает
  и healthy на `127.0.0.1:5433`.
- Штатный запуск `start.ps1 -NoBrowser -Database postgres` завершился успешно;
  backend health=`healthy`, database=`postgresql`, database_status=`connected`,
  frontend отвечает `200`.
- Реальный authenticated cookie/CSRF Playwright smoke после добавления штатной
  test-only учётки и перезапуска frontend прошёл `1/1`; найденная в smoke проблема
  контраста `.status-active` исправлена в `frontend/src/index.css`.
- Frontend production build и UI smoke после фикса прошли. Полный migration cutover,
  50-case acceptance, экспертный agreement, deployment alerting/retention и крупный
  refactoring по-прежнему требуют отдельного evidence.

### Addendum 2026-09-04 — текущий acceptance blocker

- Full acceptance повторно прошёл backend tests, release hygiene, PostgreSQL smoke,
  Alembic и authenticated core API: build-status/variants/evaluation/graph вернули
  HTTP 200. Localization audit после консервативного repair также complete: 0
  replacement markers, RU/KK/EN `26699/26699/26699`; 20 записей восстановлены из
  чистого EPVO source, 58 необратимых записей оставлены `needs_review`.
- Свежие bachelor и master A/B/C прошли с `hard_violations=0`, `quality_passed=true`,
  ГОСО и credit integrity без ошибок. Doctorate A/B/C честно остановлены validator-ом:
  все имеют 180 кредитов, ГОСО compliant и hard violations `0`, но отсутствует
  обязательный competency block `experimental_validation`.
- Причина подтверждена данными: scoped EPVO-кандидат «Теория экспериментальной
  валидации в ИИ и системах» существует, но имеет 4 кредита, тогда как в текущей
  doctoral раскладке нет допустимого 4-кредитного заменяемого блока. Маскировать это
  снижением quality gate нельзя; требуется нормативный credit-balanced repair
  (либо подтверждённый владельцем 4-кредитный doctoral module), после чего acceptance
  нужно повторить.
- Изолированный PostgreSQL restore drill завершён с кодом `0`: временная БД
  `curriculum_kag_shadow_restore_0154a56334` восстановлена, наличие Alembic version
  подтверждено, затем временная БД и dump автоматически удалены.
- В `EmbeddingService.encode_batch()` добавлен повторно используемый кэш SBERT-векторов;
  это устраняет повторный CPU-расчёт одинаковых дисциплин между LO. Regression-тест
  на повторное использование кэша проходит `3/3`; качество ранжирования и состав
  кандидатов не изменялись.

### Addendum 2026-09-04 — исправления после повторной проверки

- Doctorate repair закрыт без ослабления quality gate: если единственный scoped
  competency-модуль имеет другую кредитность, planner выполняет проверяемый
  парный обмен с сохранением суммы кредитов, LO-покрытия, пререквизитов и
  обязательных компетенций. Свежий doctorate A/B/C: `passed=true`.
- Variant B для узких doctoral-профилей получает отдельную допустимую траекторию
  по семестрам; это предотвращает ложное совпадение A/B без изменения кредитов
  или состава нормативных дисциплин.
- Повторный полный acceptance подтвердил bachelor, master, doctorate и
  ICT+medicine A/B/C: все свежие gates `passed=true`. Cohort breadth из 30
  программ запущен с frozen manifest и resume-state; на момент последней
  проверки завершено `4/30`, ошибок `0`, процесс runner жив.
- Для SEC-01 усилена не только статическая инвентаризация: `kag` graph/system
  state получил явное permission boundary, а promotion bridge теперь сначала
  разрешает объект через его `project_version_id`. Access HTTP regression после
  этого изменения проходит `31/31`; route inventory: `90` routes, `46`
  object-scoped, `0` unprotected.
