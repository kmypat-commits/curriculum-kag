# Аудит Curriculum-KAG перед внедрением

Дата: 2 сентября 2026 года
Снимок: рабочее дерево после baseline `1f9b18720d3944411a508d345deed0d8629c508e`; release tag не считается подтверждённым до фиксации текущих изменений.
Режим аудита: чтение кода, конфигурации, тестов, runtime-отчётов и журналов. Ниже сохранён исходный baseline аудита; после него в рабочем дереве уже внесены исправления, отмеченные в текущем статусе.

## Текущий статус после baseline-аудита

Закрыты или частично закрыты следующие пункты: ownership-dependencies для planner/export/KAG, RBAC dependencies для глобальных mutations, production validation и security headers, request-id и базовые rate/request limits, SQLite DDL-only startup, build lease/heartbeat/stale recovery/cancel/idempotency, explicit programme profiles, versioned ГОСО ruleset, invariant ledger/property tests, stability/breadth cohort tooling, migration hash/FK acceptance tooling, typed build contract, expert rubric и keyboard/ARIA-семантика карточек графа. Дополнительно подключены ранее не зарегистрированные planner course-flags routes; исправлены ложные inventory-защиты plan-level mutation `toggle-active`, syllabus bridge, syllabus drafts и plan evidence-bundle — теперь используются реальные FastAPI ownership dependencies, подтверждённые HTTP owner/other/admin тестом. Production validation теперь дополнительно проверяет соответствие `DOMAIN` списку `ALLOWED_HOSTS` и корректность явных http(s) CORS origins. UI verifier теперь показывает пользователю сообщение unsupported standard, regulatory profile и редакцию ruleset. KZ профильная магистратура на 120 кредитов теперь отклоняется как не соответствующая действующему ruleset. Нормативная матрица теперь содержит явный `regulatory_profile`, неизвестные профили блокируются и verifier также никогда не считает их compliant, а план получает checksum ruleset. Frontend сейчас проходит 7/7 Vitest и production build.

Остаются незакрытыми: runtime-подтверждение отдельного worker для генерации, полноценная 30–50 unique-input acceptance, фактический SQLite→PostgreSQL cutover (legacy FK-orphan policy ещё не применена), authenticated browser/a11y CI, полный zero-inline i18n (сейчас gate только запрещает рост legacy `localText`), крупный frontend/backend refactor, hash-locked Python/SBOM/digests и операционные dashboards/alerts. Docker/PostgreSQL runtime smoke пройден: engine `29.7.2`, shadow PostgreSQL healthy на `localhost:5433`, migrations применились, `/health` и frontend вернули 200, one-command launcher завершился успешно. Read-only проверка Docker Desktop подтвердила `CustomWslDistroDir = D:\Docker\DockerDesktopWSL`; launcher отделяет этот persistent root от временных сокетов в `Local\Docker\run`. Свежий backup восстановлен в изолированную PostgreSQL БД на миграции `20260902_build_control`: 26 projects, 26 versions, 54 plans, 26698 courses, 408638 EPVO disciplines, 935151 expert checks, unvalidated FK constraints — 0; временная БД удалена после проверки. Свежие standalone acceptance master, doctorate и exact ict-medicine прошли; последовательный cohort ещё требует hardening. В CI добавлен воспроизводимый Chromium UI smoke; это не заменяет authenticated PostgreSQL acceptance. Поэтому baseline-рекомендация NO-GO для внешнего multi-user production сохраняется.

Локальная проверка текущего дерева: backend — **131 тест пройден**, frontend — **7 тестов пройдено**, production build — **успешен**, i18n-gate — **197 legacy-вызовов, без роста относительно baseline**. Browser login теперь не возвращает JWT в JSON: cookie-flow отделён от явного CLI `/auth/token`; это покрыто поведенческим тестом и runtime-smoke после restart (`204`/0 bytes, `/auth/me` `200`, `/health` `healthy`). Реальный async worker также проверен на PostgreSQL: `queued → running → complete`, 114 секунд, heartbeat/lease обновлялись, `quality_after=true`, `hard_after=0`, idempotency key сохранён. Дополнительный kill-worker smoke остановил worker PID во время build: через 30 секунд status стал `timed_out`, `stale=true`, с возможностью retry; после этого обнаруженный дефект независимого heartbeat исправлен и покрыт тестом, а terminal status теперь очищает устаревшие lease-маркеры. Breadth acceptance обработал **30/30 уникальных входов**: исходно `29/30 passed`, без инфраструктурных ошибок; единственный `ict-agro` case 5 повторно сгенерирован после evidence-backed profile-specific prerequisite policy и прошёл A/B/C (`240 credits`, `0 hard`, quality/ГОСО true, prerequisite edges `5/9/7`). Поэтому revalidated breadth равен **30/30**, при этом исторический исходный failure сохранён в frozen отчёте и не скрыт. Standalone level/profile acceptance: master `passed=true`, doctorate `passed=true`, ict-medicine `passed=true`, ict-agro даёт 240 кредитов, 0 hard violations и корректную нагрузку `27/28` в последних семестрах. Это подтверждает регрессии на unit/contract-уровне, runtime worker и breadth revalidation, но не заменяет параллельные jobs/cancel smoke, authenticated browser acceptance и экспертную content validity. В frontend остаются предупреждения Vite о deprecated `esbuild` options; это не падение, но отдельная задача обслуживания toolchain.

Новая проверка SQLite backend-копии `backend/curriculum_kag.db` (11,45 GB) подтвердила размеры основных таблиц, но обнаружила **205 222 FK-нарушения**; первые относятся к orphan-записям `bridge_modules → project_versions`. До формирования discard/repair manifest эту копию нельзя считать чистым источником миграции.

Сформирован read-only manifest `.runtime/sqlite-fk-discard-manifest.json` с SHA-256 `d664734686c06be8d6648328219db8a00485dceac58b04be2419bb7275704b5d`: `embeddings` — 197 343, `match_scores` — 7 760, `bridge_modules` — 115, `match_feedback` — 4. Физическая `integrity_check` завершилась `ok`; это не отменяет логические FK-нарушения.

Политика manifest: `embeddings` и `match_scores` — только discard с последующей регенерацией; `match_feedback` — review перед discard; `bridge_modules` — repair/review перед cutover. Автоматического удаления строк не выполнялось.

API inventory текущего приложения содержит 84 routes, из них 45 object-scoped; **45/45 имеют access marker, 0 unmarked**. Planner/KAG/export object routes имеют access dependency; project и EPVO object routes используют FastAPI-wrapper `require_project_object_access`. Global repository reads отделены от mutations permission matrix, а EPVO priority mutation теперь требует `planner:write`. Effective RBAC payload в `/auth/me` совпадает с role policy; это дополнительно покрыто тестом. Последний backend regression: **128 тестов пройдено**.

Quality cohort теперь делает DB preflight и при недоступном PostgreSQL сразу пишет `status=blocked`; прежний прогон `50/50` с `0/50` переклассифицирован как инфраструктурный failure. Первый реальный stability-прогон обработал `5/5`, прошёл `1/5`; после исправлений отдельные bachelor ict-medicine и ict-agro A-кейсы прошли: 240 кредитов, 0 hard violations, quality passed, ГОСО compliant. Master/doctorate пока quality-fail по недостаточному LO-покрытию.

CI test runner `backend/run_tests.py` также проверен после исправления async-build contract test: **121/121 passed**; новый verifier-тест дополнительно проходит в pytest. Это закрывает расхождение между локальным pytest и фактическим plain-assert runner workflow, но runner требует отдельного обновления, чтобы включить весь pytest-набор.

CI дополнен API route inventory gate. При этом обнаружена и исправлена чистая runner-проблема: `repository` импортирует `pandas` при старте приложения, поэтому пакет добавлен в `requirements-minimal.txt`; dependency profile gate после изменения проходит.

## 1. Итог без прикрас

Важно: разделы ниже содержат baseline-находки и исходные доказательства. Их задачи не означают, что все пункты всё ещё открыты. Актуальное состояние определяется таблицей выше и этой сверкой:

| Находка | Сейчас | Остаток |
|---|---|---|
| AUD-001 ownership/IDOR | Исправлено для инвентаризированных object-scoped routes; 45/45 отмечены access-механизмом | Нужен runtime smoke против PostgreSQL и полный HTTP-каталог edge cases |
| AUD-001B RBAC | Основные global mutations защищены permission dependencies; owner/other/admin покрыты тестами | Нужна production-проверка реального cookie/CSRF/RBAC потока |
| AUD-002 production defaults | Валидация `DOMAIN`, `ALLOWED_HOSTS`, CORS, secure cookie и SECRET_KEY добавлена | Нужен запуск compose с реальным доменом/HTTPS |
| AUD-003 async builds | Lease, heartbeat, stale recovery, cancel, idempotency и worker-контракт реализованы | Не доказаны kill-worker, параллельные jobs и runtime latency |
| AUD-005/006 ГОСО | Профили и versioned ruleset/checksum добавлены; неизвестные профили блокируются | Нужна проверка полного UI/API набора и устранение оставшихся дублированных нормативных формул |
| AUD-007 SQLite → PostgreSQL | Backup restore на shadow PostgreSQL подтверждён; FK discard manifest подготовлен | Полный cutover из legacy SQLite ещё не выполнен: 205222 логических FK-нарушения требуют утверждённой policy |

### 1.1. Что нельзя выдавать за доказанное

Пока Docker daemon не поднимается, нельзя утверждать успешную генерацию новых программ, качество cohort 30–50, миграцию/restore или browser acceptance. Unit-тесты и скрипты доказывают контракт и готовность проверки, но не факт runtime-успеха.

Curriculum-KAG нельзя честно назвать «тонкой AI-обёрткой» или игрушечным проектом. В системе есть большая предметная модель, PostgreSQL/pgvector, сохранённые источники доказательств, детерминированный планировщик, независимый verifier, транзакционная замена вариантов, ГОСО, пререквизиты, объяснимость, аудит действий, резервное копирование и повторяемые эксперименты. Для одного разработчика это высокий уровень: по объёму и предметной сложности работа соответствует сильному senior/lead R&D-прототипу.

Но это ещё не институционально зрелый продукт. Основной риск не в том, что «ничего не работает», а в разнице зрелости слоёв:

- предметное и исследовательское ядро — сильное;
- локальная эксплуатация и воспроизводимость — выше среднего;
- многопользовательская изоляция, production-конфигурация, фоновые задачи и UI-контракты — заметно слабее;
- автоматические тесты хорошо защищают известные алгоритмические регрессии, но слабо ищут новые классы ошибок на HTTP-, security- и browser-уровне.

Ориентировочная зрелость, а не формальная сертификационная оценка:

| Область | Оценка | Комментарий |
|---|---:|---|
| Предметная глубина и алгоритмы | 8/10 | Сильный constrained planner, evidence и verifier; остаётся риск накопления эвристик и расхождения нормативных правил. |
| Исследовательская воспроизводимость | 7/10 | Есть frozen-отчёты, Model/Dataset Card и manifests; acceptance шире по числу прогонов, чем по разнообразию программ. |
| Backend/API | 6/10 | Хорошее разбиение роутеров, но крупные orchestration-файлы, слабая типизация части API и критичный ownership-gap. |
| Frontend/UX | 6/10 | Рабочий сложный интерфейс и объяснения, но высокая связанность, неполная доступность и локализация в нескольких слоях. |
| Данные и миграции | 6/10 | Подготовлены PostgreSQL acceptance/restore и manifest-политика; runtime restore не подтверждён, legacy SQLite содержит большой слой осиротевших вычисляемых данных. |
| Security для локальной установки | 7/10 | Cookie, CSRF, безопасные ошибки, admin Git и базовые headers уже есть. |
| Security для многопользовательского внедрения | 6/10 | Основные ownership/RBAC и production defaults закрыты контрактами; runtime cookie/CSRF/HTTP smoke ещё не доказан. |
| Эксплуатация и масштабирование | 6/10 | Есть async worker lease/cancel/recovery и telemetry contracts; Docker runtime, kill-worker и нагрузочный smoke ещё не доказаны. |

Вердикт: **сильный solo R&D/pilot продукт, но не готов к внешнему многопользовательскому внедрению без закрытия P0 и основных P1**.

## 2. Как система работает

1. Пользователь создаёт проект: уровень образования, юрисдикция, направление/группа ЕПВО, одна или две области, кредиты, семестры, цель и результаты обучения.
2. Backend синхронизирует релевантные дисциплины из нормализованного CEER/ЕПВО-слоя и рассчитывает связи дисциплина–РО с использованием лексических, SBERT и экспертных сигналов.
3. Планировщик отбирает допустимые дисциплины, добавляет защищённые ГОСО-компоненты, строит варианты A/B/C с разными soft-приоритетами, восстанавливает пререквизиты и распределяет дисциплины по семестрам.
4. Repair-этапы исправляют кредитный остаток, нагрузку, доменные квоты, покрытие РО и педагогическую уместность. Bridge-модуль создаётся как ограниченный fallback.
5. Независимый verifier повторно считает кредиты, нагрузки, дубли, уровень, доменные квоты, РО, пререквизиты и ГОСО. Новые варианты коммитятся только после прохождения hard-инвариантов.
6. React-интерфейс показывает планы, источники покрытия, причины выбора, сравнение с ЕПВО, граф траектории, замены bridge и экспертную обратную связь.
7. PostgreSQL хранит проектные данные, CEER, результаты сопоставления, статусы генерации и audit events. Модель и крупная база распространяются отдельно от GitHub-кода.

## 3. Что уже сделано хорошо

- Текущий локальный gate проходит: **127/127 backend**, **7/7 frontend Vitest**, frontend production build.
- PostgreSQL health и локальный frontend runtime в текущем окружении не подтверждены: Docker daemon отсутствует, `localhost:5433` недоступен.
- Завершённый cohort 30/30 относится к историческому runtime-снимку; новый acceptance 30–50 unique inputs ещё не выполнен.
- A/B/C строятся отдельно и проверяются на одинаковые fingerprints до коммита.
- План строится транзакционно: старые варианты удаляются только после успешного построения и проверки новых.
- Есть безопасный deterministic fallback при недоступности внешней LLM.
- Browser auth переведён на HttpOnly cookie, добавлен double-submit CSRF; ошибки генерации не раскрывают внутреннее исключение клиенту.
- CRUD проектов действительно фильтрует владельца либо администратора.
- Git-маршруты требуют роль `admin`, имена веток ограничены, shell-интерполяция не используется.
- Есть Alembic, PostgreSQL endpoint-contract job, dump/restore check, SHA-256 manifests и staging tag.
- Критичные исходные CEER-таблицы SQLite → PostgreSQL совпадают по количеству строк.
- Код честно отделяет software checklist от аккредитации, а не выдаёт автоматическую метрику за экспертное решение.

## 4. Критичные находки — P0 до внешнего внедрения

### AUD-001. Planner API не проверяет владельца проекта (IDOR)

CRUD проектов имеет `_require_project_access`, но большинство `/planner/*` проверяет только наличие авторизованного пользователя. Например, build получает `ProjectVersion` по переданному ID и не связывает его с `current_user`; activation получает `Plan` по ID и меняет активный вариант. Аналогично доступны graph, coverage, replacement, syllabus bundle и build status.

Риск: любой вошедший пользователь, угадав или перебрав ID, потенциально может читать граф/метрики чужой программы, запускать дорогой пересчёт, менять bridge и активный план. Это критично для институциональных и неопубликованных программ.

Почему прежний audit это пропустил: `test_project_ownership_contract.py` читает исходный текст только `projects.py` и проверяет наличие строк; реального второго пользователя и planner endpoints в тесте нет.

Задача:

1. Создать единый `require_project_access`, `require_version_access`, `require_plan_access` в service-слое.
2. Применить dependency/helper ко всем planner, KAG feedback, export и syllabus маршрутам.
3. Для чужого объекта отвечать одинаковым 404, не раскрывая его существование.
4. Добавить интеграционные тесты: owner, second user, admin для каждого семейства read/write endpoints.
5. Проверить не только HTTP-код, но и отсутствие изменения БД после запрещённого запроса.

Критерий приёмки: второй пользователь не может прочитать, пересчитать, заменить, экспортировать или активировать чужой проект даже при знании всех ID.

Доказательства: `backend/app/api/projects.py:24-31`, `backend/app/api/planner_build.py:267-303`, `backend/app/api/planner_build.py:587-617`, `backend/app/api/planner_build.py:699-718`, `backend/app/api/planner_graph.py:19-36`, `backend/tests/test_project_ownership_contract.py:4-12`.

### AUD-001B. Модель RBAC существует в БД, но фактически не защищает системные операции

В системе объявлены роли `admin`, `methodist`, `analyst`, `guest`, permissions и `check_permission`, однако API почти не использует permission dependency. Admin-проверка реально есть только у Git-маршрутов. Любой авторизованный пользователь сейчас может импортировать, создавать, менять и удалять дисциплины общего репозитория; запускать полный reindex и graph rebuild; продвигать bridge в постоянный каталог; запускать LSTM/GNN smoke subprocess. Это одновременно privilege escalation, риск порчи общего evidence layer и простой DoS через тяжёлые операции.

Существующие decorator helpers `require_permission`/`require_role` также нельзя просто массово навесить без переработки: они не сохраняют FastAPI signature через `functools.wraps` и достают пользователя из `kwargs`, поэтому надёжнее сделать dependency factories.

Задача:

1. Зафиксировать матрицу `role × resource × action`, включая project, planner, repository, graph, model experiments, export и administration.
2. Реализовать FastAPI dependency factories `require_permission(...)`, а не непрозрачные async decorators.
3. Оставить чтение общего каталога доступным по политике, но все глобальные mutations — только разрешённым ролям.
4. Ограничить model smoke/reindex отдельной admin/ops permission и concurrency lock.
5. Добавить HTTP tests для `guest`, `analyst`, `methodist`, `admin`; проверять и отказ, и отсутствие побочных изменений.
6. В production bootstrap запретить известные demo credentials и потребовать смену первоначального администратора.

Критерий приёмки: каждая изменяющая операция имеет явное permission; guest/analyst не изменяют глобальные данные и не запускают вычислительные процессы; матрица проверяется параметризованными тестами.

Доказательства: `backend/app/models/user.py:35-53`, `backend/app/services/rbac.py:7-70`, `backend/app/api/repository.py:109-113`, `backend/app/api/repository.py:448-502`, `backend/app/api/kag.py:216-220`, `backend/app/api/kag.py:238-285`, `backend/app/api/epvo.py:434-445`, `backend/app/api/git_versions.py:49-53`.

### AUD-002. Production-compose блокирует реальный домен и оставляет auth-cookie без Secure

Приложение по умолчанию принимает только `localhost`, `127.0.0.1`, `testserver`. `docker-compose.production.yml` передаёт `DOMAIN` только Caddy, но не передаёт backend-параметры `ALLOWED_HOSTS` и `AUTH_COOKIE_SECURE`. Проверено фактически на текущем backend: `Host: localhost` → 200, `Host: example.org` → 400.

Риск: опубликованный DOMAIN не сможет обращаться к API либо оператор отключит TrustedHost вручную; cookie останется без Secure несмотря на HTTPS.

Задача:

1. Передавать `ALLOWED_HOSTS` и `AUTH_COOKIE_SECURE=true` в production-compose.
2. Добавить их в `.env.production.example` с корректным форматом Pydantic list.
3. Валидировать на старте: production DOMAIN задан, Secure cookie включена, SECRET_KEY не example.
4. Добавить контейнерный smoke с реальным Host header и проверкой `Set-Cookie`.

Критерий приёмки: запрос через тестовый HTTPS-domain проходит TrustedHost; `access_token` и CSRF cookie имеют `Secure`; localhost-профиль по-прежнему работает по HTTP.

Доказательства: `backend/app/config.py:14-16`, `backend/app/config.py:81-85`, `backend/app/main.py:114`, `docker-compose.production.yml:24-40`, `.env.production.example:1-24`.

### AUD-003. Runtime-подтверждение фонового job/lease ещё не выполнено

При `ASYNC_BUILDS=true` HTTP `/build` выполняет claim и запускает отдельный короткоживущий worker-процесс; API возвращает `202 queued`. В status-модели есть worker ID, lease, heartbeat, attempts, idempotency key, cancel и stale recovery. При `ASYNC_BUILDS=false` сохраняется синхронный режим для локального rollback/debug.

Остающийся риск: в текущем окружении не выполнен runtime-тест с PostgreSQL, kill worker посередине build и параллельными jobs. Без него нельзя доказать, что заявленная recovery-семантика работает в реальном Docker deployment.

Задача:

1. Выполнить Docker/PostgreSQL runtime acceptance отдельного worker.
2. Убить worker посередине build и подтвердить stale recovery/retry.
3. Проверить health во время двух генераций и пользовательские/global concurrency limits.

Критерий приёмки: kill worker посередине build → job автоматически становится retryable/failed, новый запуск не блокируется; health p95 остаётся в заданном бюджете.

Доказательства: `backend/app/api/planner_build.py:267-403`, `backend/app/api/planner_state.py:56-89`, `backend/app/api/planner_state.py:92-107`, `backend/app/models/plan_build_status.py:12-24`, `docker-compose.production.yml:53`.

## 5. Высокий приоритет — P1

### AUD-004. Broad cohort подготовлен, но runtime acceptance заблокирован инфраструктурой

`audit_quality_cohort.py` разделяет stability-профили и breadth inputs, сохраняет frozen manifest и проверяет уникальность. Broad cohort на 50 inputs был подготовлен, но PostgreSQL preflight корректно переводит запуск в `blocked`, если `localhost:5433` недоступен. Это не подтверждение качества генерации: сначала требуется рабочая target DB.

После восстановления PostgreSQL нужно выполнить полный cohort и сохранить coverage matrix; текущие локальные unit/contract тесты этого не заменяют.

Задача:

1. Переименовать текущую метрику в repeated-stability cohort.
2. Создать frozen manifest из 30–50 **разных** scope/целей/РО/длительностей/языков/юрисдикций.
3. Включить разные группы ЕПВО, 60/90/120 master, doctorate tracks, KZ/international, standard/interdisciplinary/joint и негативные случаи.
4. Считать distinct input fingerprints и schedule fingerprints; падать, если breadth ниже порога.
5. Сохранить per-case seed, вход, версию модели/БД, длительность, verifier result и причину исключения.

Критерий приёмки: не менее 30 уникальных input fingerprints, заранее зафиксированная матрица покрытия и отдельные показатели reliability, domain quality и latency.

Доказательства: `backend/scripts/audit_quality_cohort.py:39-45`, `backend/scripts/audit_quality_cohort.py:59-80`, `backend/scripts/audit_cross_level_generation.py:98-166`, `.runtime/quality-cohort-final-30-after-quota-fix.json`, `.runtime/quality-cohort-final-50.json`.

### AUD-005. Валидация объёма противоречит реализованным ГОСО-профилям магистратуры

`goso.py` явно содержит профильную магистратуру 60 и 90 кредитов, включая 1,5 года. Но backend приводит `duration_years` к `int`, требует `semesters == years * 2` и `credits == years * 60`; 1,5 года/3 семестра/90 кредитов становятся недостижимы. UI предлагает professional track, но при переключении сохраняет master defaults 2 года/120 кредитов и ввод продолжительности только целыми годами.

Задача:

1. Сделать допустимые programme-volume profiles явной таблицей по level/track/jurisdiction.
2. Для profile master разрешить 60/2 и 90/3; для scientific-pedagogical — 120/4.
3. Автоматически менять duration/credits при выборе track; запретить несовместимые комбинации.
4. Добавить positive/negative API и UI tests для каждого профиля.
5. Аналогично проверить достижимость doctorate profile, который код поддерживает, а wizard явно не выбирает.

Критерий приёмки: каждая ветка `_definitions_for_constraints` достижима из UI и API ровно с нормативно допустимым объёмом.

Доказательства: `backend/app/api/projects.py:53-73`, `backend/app/planner/goso.py:84-94`, `backend/app/planner/goso.py:199-219`, `frontend/src/pages/ProjectWizard.jsx:83-96`, `frontend/src/pages/ProjectWizard.jsx:328-332`, `frontend/src/pages/ProjectWizard.jsx:416-431`.

### AUD-006. Нормативный JSON не является полностью исполняемым source of truth

Введён компактный versioned ruleset с rule IDs, ссылкой на приказ и runtime checksum; неизвестный `regulatory_profile` больше не считается поддержанным. При этом нормативные числа и названия в основном planner-коде всё ещё частично продублированы в Python-константах. Это оставшийся риск drift: документ можно обновить, а отдельную формулу — забыть.

Задача:

1. Перенести оставшиеся нормативные числа и определения в ruleset либо добавить drift-test на каждую исполняемую константу.
2. Добавить contract test: все исполняемые ГОСО-компоненты имеют нормативное основание либо явно помечены как institutional planner allocation.
3. Описать процедуру обновления при новой редакции приказа.

Критерий приёмки: по любой автоматической ошибке ГОСО UI показывает rule ID, редакцию и источник; drift между JSON и кодом невозможен в CI.

Доказательства: `backend/app/planner/goso.py:1`, `backend/app/planner/goso.py:47-112`, `backend/data/goso/goso-2026-requirements.json`, `docs/PLAN_QUALITY_GOSO_RU.md:20-24`.

Официальная проверка на дату аудита: [ИПС «Әділет», приказ № 2, регистрационный № 28916](https://adilet.zan.kz/rus/docs/V2200028916) помечает документ как обновлённый и показывает изменение от 04.05.2026 № 225. То есть дата локального extract выглядит актуальной; пробел состоит в отсутствии автоматической проверки новой редакции и traceability исполняемых правил.

## 12. Дополнительная сверка 3 сентября 2026 года

Проверка выполнена на работающем локальном runtime после входа администратора через cookie-flow. Это отдельное доказательство поведения интерфейса и не заменяет production smoke.

### Подтверждено

- `/` открылся, login прошёл, `/projects/489` показал карточку программы и понятное состояние «сначала сформируйте варианты учебного плана», когда плана нет.
- `/projects/16/graph` загрузил активный вариант A: 8 семестров, кредитные итоги по семестрам, 240-кредитный контур, связи repository/plan-inferred, текстовую версию графа и explain-карточки семестров.
- Переключение RU → EN и reload сохранили выбранный язык: после reload заголовки, действия, дисциплины и граф остались на English. Аналогично ранее подтверждался RU/KK flow.
- Явной ошибки JavaScript в console после smoke не обнаружено.

### AUD-020. Cytoscape принимает неподдерживаемые shadow-свойства

**Severity: Medium (UX/визуальная достоверность).** Browser console зафиксировал предупреждения `The style property shadow-blur/shadow-color/shadow-opacity/shadow-offset-x/shadow-offset-y is invalid` в собранном Cytoscape-графе. Значит, часть ожидаемого визуального оформления узлов/связей игнорируется библиотекой. Риск — граф выглядит иначе, чем предусмотрено дизайном, а состояние «выделено/важно/bridge» может быть менее различимо.

**Задачи:** заменить CSS-подобные shadow-свойства на поддерживаемую Cytoscape-модель (или убрать их), закрепить визуальный smoke для обычного узла, выбранного узла, bridge и ошибки; проверить keyboard focus и контраст после изменения.

**Критерий приёмки:** console без Cytoscape style warnings; все семантические состояния различимы без тени, только цветом они не кодируются; screenshot/DOM smoke проходит для RU/KK/EN.

**Доказательство:** runtime browser log от 2026-09-03, asset `frontend/dist/assets/cytoscape.esm-Byh4RplT.js`; UI source — `frontend/src/pages/PrerequisiteGraph.jsx`.

**Статус после исправления:** закрыто в текущем дереве. `frontend/scripts/check-graph-style.mjs`, frontend 7/7 и production build проходят; после публикации свежего `frontend/dist` в `.runtime/dist` graph smoke подтвердил готовый граф и текстовую версию, Cytoscape warnings = 0, JavaScript errors = 0.

Дополнительно добавлен `frontend/e2e/authenticated.spec.js`: сценарий с mock API проверяет неаутентифицированное состояние, cookie-login, восстановление `/auth/me`, переход на dashboard и отображение данных. В сценарий включен `@axe-core/playwright` с блокировкой critical/serious нарушений. Локально authenticated test завершился `1 passed`, а полный набор Playwright — `5 passed` (включая health и protected routes). Это закрывает UI auth-flow и базовый dashboard axe-gate; real-backend ownership/403, graph axe и расширенная accessibility-матрица остаются в AUD-021.

В рамках I18N-01 verification-панели переведены с 14 inline tri-language вызовов на ключи общего каталога RU/KK/EN. Legacy count уменьшен с `197` до `183`; gate проходит с предупреждением о незавершённой миграции. Unit `7/7` и production build после изменения проходят, свежий bundle опубликован в `.runtime/dist`.

В рамках API-01 typed-контракт добавлен для `build-status` и `build-cancel`: Pydantic-модели проверяют state/stage/progress, временные поля, worker/attempt и cancel-маркер, сохраняя forward-compatible telemetry extras. Planner/async contract tests после изменения: `42 passed`, auth/safe-error tests: `4 passed`.

I18N-01 продолжен в `PlanSemesterGrid`: 9 повторяющихся подписей и источников переведены на общий каталог (`cycle`, `component`, `source`, типы источников, `course_code`). Последовательность legacy inline count: **197 → 183 → 182 → 173**. Unit `7/7`, i18n gate и production build проходят; новый bundle обновлён в `.runtime/dist`.

После расширения `backend/tests/run_postgres_endpoint_contracts.py` реальный PostgreSQL-контур подтвердил `6` базовых endpoint contracts и ещё `8` owner/other/admin checks: владелец получает проект и build-status, другой пользователь получает 404 и пустой список своих проектов, admin получает доступ; запрещённые проверки не выполняют mutation. Запуск завершился успешно на выделенной БД `curriculum_kag_endpoint_test`.

### AUD-021. Полный browser-аудит пока не является CI-gate

Сейчас есть Playwright-конфигурация и локальный smoke, но в репозитории не обнаружен завершённый authenticated сценарий с фиксацией cookie-login, маршрутов graph/plan/coverage, проверкой 401/403 и accessibility-assertions. Не следует выдавать текущие 7/7 Vitest и production build за проверку браузерного продукта.

**Задачи:** добавить отдельный authenticated Playwright project с изолированным test user/seed; проверять login, logout, прямой deep-link, graph empty/ready, plan build status, 401 session expiry, 403 ownership, язык RU/KK/EN и отсутствие console errors; подключить axe или эквивалентный accessibility gate и сохранять trace только при падении.

**Критерий приёмки:** CI проходит на чистой базе/fixture без ручного входа; минимум один позитивный и один негативный ownership-сценарий; console error count = 0, кроме явно allowlisted third-party warnings.

### AUD-022. Нужно отделить «система работает» от «содержание программы релевантно»

Граф на `IT медицина` технически строится, но показывает широкий междисциплинарный набор: программирование, экология, право, биостатистика и медицина. Для interdisciplinary-программы это может быть допустимо, однако UI сейчас не формулирует рядом с каждой дисциплиной строгую причину релевантности, evidence score и статус «реальный курс / bridge / plan-inferred». Внедрение может быть раскритиковано не за сбой, а за необъяснимый выбор содержания.

**Задачи:** для каждой дисциплины показывать домен, LO/evidence, источник связи и причину допуска; явно разделить общие, профессиональные, bridge и ГОСО-компоненты; для каждой специальной отрасли задать negative examples и экспертную выборочную проверку.

**Критерий приёмки:** эксперт по двум blind-сэмплам может восстановить причину выбора курса без чтения исходного кода; нерелевантная дисциплина либо отбрасывается verifier-ом, либо имеет явное предупреждение и требует подтверждения.

## 13. Консолидированный план задач аудита

### P0 — до показа внешнему заказчику

1. Исправить AUD-020 и включить browser console gate.
2. Завершить authenticated Playwright/a11y CI из AUD-021.
3. Прогнать ownership/RBAC HTTP matrix в PostgreSQL для owner/other/admin по всем write-семействам и проверить отсутствие изменений в БД после отказа.
4. Завершить чистый SQLite → PostgreSQL migration acceptance с утверждённым discard manifest; отдельно выполнить backup → isolated restore → application smoke.

### P1 — до pilot-внедрения

1. Закрыть zero-inline i18n, включая placeholders, статусы, ошибки, graph labels и empty states.
2. Убрать нормативный drift: каждое число/профиль/исключение должно иметь ruleset rule ID или явную institutional allocation пометку.
3. Завершить экспертную rubric-проверку релевантности и bridge-модулей на blind-сэмпле; хранить inter-rater agreement.
4. Стабилизировать крупные orchestration-файлы: scheduler/variant strategy/planner build и соответствующие frontend page controllers.
5. Ввести p95 telemetry dashboard/alerts для login, graph, coverage и build; добавить concurrent jobs/cancel/retry acceptance.

### P2 — hardening после pilot

1. Перевести rate-limit и job lease из in-memory механизма в общий production storage при нескольких backend workers.
2. Добавить lockfile/SBOM/image digest/non-root verification и ежемесячный dependency review.
3. Добавить retention policy для audit/telemetry и проверку восстановления backup по расписанию.
4. Подготовить staging tag, manifest/checksum и раздельную поставку кода, модели и базы только после прохождения P0.

### Итоговая оценка

По текущему снимку это сильный solo senior/lead R&D-продукт: предметное ядро, planner/verifier, PostgreSQL/pgvector, evidence/provenance, ГОСО, граф и recovery-механика существенно выше обычного CRUD или «vibe-coded» демо. До уровня надёжного внедрения не хватает не нового большого алгоритма, а доказательств вокруг него: authenticated browser CI, чистого migration acceptance, экспертной релевантности и production hardening. Ориентировочная зрелость остаётся **6–7/10 для pilot** и **не выше 5/10 для внешнего multi-user production до закрытия P0**.

### AUD-006B. Матрица нормативной области требует расширения для специальных отраслей

Теперь программа должна иметь явный `regulatory_profile`; общий KZ-профиль идентифицирован как `KZ_GOSO_2026`, а неизвестный профиль не проходит `supports_profile`. Но для `ict-medicine` и других специальных отраслей пока нет отдельного реализованного healthcare ruleset и sign-off. Поэтому такая программа не должна считаться юридически подтверждённой только по факту наличия KZ-профиля.

Задача:

1. Зафиксировать матрицу `general KZ / healthcare / military-special / other` и состояние реализации каждой ветки.
2. Для нереализованного ruleset блокировать автоматическое заявление `goso_compliant` и показывать «требуется внешняя нормативная проверка».
3. Отделить interdisciplinary IT+medicine от основной медицинской образовательной программы.
4. Провести sign-off правил профильным методистом/юристом и сохранить протокол рядом с версией ruleset.

Критерий приёмки: система никогда не показывает общий `ГОСО соответствует` для regulatory profile, чьи правила она не реализует; каждый план содержит конкретный standard ID/version.

Источник для проверки scope: [официальные требования лицензирования на «Әділет»](https://adilet.zan.kz/rus/docs/V2200030832) отдельно упоминают приказ № 2 и нормативные акты для образования в области здравоохранения.

### AUD-007. SQLite → PostgreSQL доказан для исходного CEER, но не как полный чистый перенос

Позитив: девять критичных raw/normalized CEER tables совпали точно. Негатив: общий live compare имеет `passed=false`, потому что PostgreSQL уже содержит новые проекты и планы. Legacy SQLite содержит 197 343 orphan embeddings и 3 880 orphan match scores; migration считает их невалидными и пропускает. Это разумная очистка вычисляемого слоя, но её нельзя называть полным bit-for-bit переносом без отдельного утверждённого discard manifest.

Задача:

1. Заморозить копию SQLite и пустую целевую PostgreSQL.
2. Выполнить миграцию в одноразовую target DB.
3. Сравнить все таблицы: row count, PK set, FK check, выбранные canonical hashes.
4. Сформировать discard manifest по каждой пропущенной строке/классу с причиной и regenerate policy.
5. После загрузки пересоздать embeddings/match scores и доказать их соответствие текущей модели.
6. Отдельно сравнивать live-state divergence, не смешивая её с migration acceptance.

Критерий приёмки: frozen migration report `passed=true`; все расхождения либо нулевые, либо перечислены и подписаны как производные/перегенерируемые данные.

Доказательства: `.runtime/sqlite-postgres-source-current.json`, `.runtime/sqlite-postgres-current.json`, `backend/scripts/compare_sqlite_postgres_counts.py:16-36`, `backend/scripts/compare_sqlite_postgres_counts.py:47-83`, `backend/scripts/migrate_sqlite_to_postgres.py:64-114`.

### AUD-008. Planner — последовательность repair-эвристик с риском «последний repair сломал предыдущий»

Большая часть известного дефекта `ict-medicine 55/68` возникла именно после позднего trim/repair. Сейчас финальный verifier ловит такие случаи — это хорошо. Но `scheduler.py` (1283 строки) и `variant_strategy.py` (1133 строки) всё ещё координируют много некоммутативных стадий; `variant_strategy` временно объявляет no-op callback, который позднее перепривязывается. Это выглядит как переходный seam и затрудняет доказательство порядка.

Задача:

1. Формализовать invariant ledger: какие инварианты читает/меняет/обязан восстановить каждый stage.
2. После каждого мутационного stage запускать дешёвые локальные postconditions.
3. Ввести bounded fixed-point/convergence вместо неявной надежды на порядок repair.
4. Добавить property-based tests для кредитов, квот, уникальности, пререквизитов и bridge caps на случайно сгенерированных допустимых входах.
5. Убрать late binding/no-op callback и передавать зависимости явно.
6. Ограничить orchestration-функции; вынести policy и state transitions в типизированные stage results.

Критерий приёмки: перестановка независимых stages либо эквивалентна, либо запрещена явной dependency graph; случайные тесты не находят нарушение инвариантов.

Доказательства: `backend/app/planner/scheduler.py:157`, `backend/app/planner/variant_strategy.py:139`, `backend/app/planner/variant_strategy.py:195-212`, `backend/app/planner/variant_strategy.py:719`.

### AUD-009. CI не запускает frontend tests/E2E и не проверяет accessibility

Frontend job делает только `npm ci` и `npm run build`. Два unit-файла/5 тестов в CI не запускаются. Playwright состоит из четырёх smoke-тестов: blank screen, health и редирект неавторизованного пользователя; authenticated plan/graph/locale/bridge workflows не проверяются. Нет lint/typecheck/coverage/a11y gate.

Задача:

1. Добавить `npm test` в CI.
2. Поднять app + PostgreSQL fixture и запускать Playwright без зависимости от project ID 13.
3. Добавить owner/admin/second-user browser cases.
4. Проверять RU/KK/EN основные страницы, граф A/B/C, build error/retry, bridge replacement.
5. Добавить axe/WCAG smoke и keyboard navigation.
6. Ввести ESLint и минимальный coverage budget для изменяемых модулей.

Критерий приёмки: PR не проходит при поломке unit, authenticated E2E, locale или accessibility contract.

Доказательства: `.github/workflows/quality.yml:38-52`, `frontend/e2e/smoke.spec.js:3-27`, `frontend/package.json:38-42`.

### AUD-010. Граф и initial plan screen слишком медленные

Фактические логи показывают параллельные `graph`, `semester-competencies`, `variants` по 8,8–13,4 секунды. Это уже не косметическая задержка: пользователь видит длинный initial load, а одновременные тяжёлые запросы конкурируют за один worker и БД.

Задача:

1. Профилировать SQL count и Python CPU отдельно для трёх endpoints.
2. Устранить повторные ORM загрузки и N+1; добавить недостающие индексы по фактическим plans.
3. Кэшировать immutable graph/coverage по `plan_id + metrics_schema_version + language`.
4. Рассмотреть один initial summary endpoint либо последовательную lazy-load стратегию.
5. Задать бюджеты: API p95, payload size, first useful render.

Критерий приёмки: warm p95 основных read endpoints < 1 с, cold p95 < 3 с на reference hardware; health не деградирует при загрузке графа.

Доказательства: `.runtime/backend.err.log`, `backend/app/api/planner_graph.py`, `backend/app/api/planner_coverage.py`.

## 6. Средний приоритет — P2

### AUD-011. API-контракты частично не типизированы

В API около 80 routes, но `response_model` указан только у небольшой части. Не менее 15 мест используют raw `dict` payload/Body. Это облегчает скрытые breaking changes, лишние поля, неверные enum и 500 вместо понятного 422.

Задачи: Pydantic request/response models для planner/KAG/EPVO; enums для variant/language/verdict; versioned metrics schemas; OpenAPI snapshot/compatibility test; лимиты размеров строк/списков.

Критерий приёмки: все public write endpoints имеют typed request, все стабильные read endpoints — typed response; OpenAPI diff осознанно принимается в PR.

### AUD-012. Тесты содержат много source-text contracts вместо поведенческих проверок

Из 101 backend tests заметная часть проверяет строки/import seams. Они полезны при рефакторинге, но могут пройти при фактически небезопасном поведении, как произошло с ownership. Нет Hypothesis/property-based testing.

Задачи: заменить security contracts на HTTP+DB integration; сохранить source tests только для статических запретов; добавить test classification и coverage report; ввести property-based planner tests.

### AUD-013. Локализация имеет несколько параллельных источников

Есть основной `translations.js`, generated KK fallback, `clean` overrides, domain/cycle maps и 59 прямых `language === ...` веток. 21 находится в одном LOCoverageDashboard. Это повышает риск, что текст исправлен только на одной странице или один язык молча откатился к RU.

Задачи: единый каталог ключей; убрать inline tri-language branches; запретить fallback в release audit для обязательных экранов; проверять одинаковые key sets RU/KK/EN; версионировать content translations отдельно от UI copy.

Критерий приёмки: zero hard-coded UI language branches вне локализационного слоя; missing key ломает CI, а не молча показывает RU/key.

Доказательства: `frontend/src/contexts/LanguageContext.jsx:14-28`, `frontend/src/pages/LOCoverageDashboard.jsx`, `frontend/src/utils/planBuilderPresentation.js`.

### AUD-014. Accessibility и keyboard navigation не закрыты

В 100 button-разметках только малая часть задаёт `type`; ARIA используется редко. На графе кликабельные course cards сделаны как `div onClick` без role/tabIndex/keyboard handler; canvas-граф не имеет полноценной текстовой альтернативы для всех связей. Несколько modal-like cards не управляют фокусом.

Задачи: semantic buttons; labels/accessible names; keyboard graph/course selection; focus trap/return; текстовая таблица узлов и рёбер; contrast/reduced-motion/zoom tests; axe CI.

Критерий приёмки: основные сценарии выполняются только клавиатурой; axe не имеет serious/critical violations.

Доказательства: `frontend/src/pages/PrerequisiteGraph.jsx:208-252`, `frontend/src/pages/PrerequisiteGraph.jsx:271-329`.

### AUD-015. Frontend-контроллеры остаются чрезмерно крупными и связанными

`PlanBuilder.jsx`: 1065 строк, 32 state, 21 API call. `LOCoverageDashboard.jsx`: 855 строк, 24 state, 12 API calls. LOCoverageDashboard ищет кнопку bridge через `document.querySelector`, что связывает независимые компоненты по DOM-маркеру. В проекте 667 inline style usages.

Задачи: resource hooks/query cache; reducer/state machine для build/recompute; typed API client; bridge command через callback/context, не DOM; компоненты по user journey; design tokens и CSS modules/classes.

Критерий приёмки: pages координируют сценарий, но не содержат транспорт, polling и presentation одновременно; прямых DOM-команд между компонентами нет.

### AUD-016. Polling остаётся агрессивным и смешан с симуляцией прогресса

Build status опрашивается через 1,2 с, затем 3 с; recompute/apply используют интервалы и искусственный progress. Для минутной генерации это создаёт лишние обращения и может показывать прогресс, не соответствующий backend.

Задачи: exponential/backoff 3–10 с либо SSE; backend-authoritative stages; polling pause в background tab; stop после terminal state; общий hook.

Доказательства: `frontend/src/pages/PlanBuilder.jsx:124-151`, `frontend/src/pages/PlanBuilder.jsx:285-370`.

### AUD-017. Production perimeter неполон

FastAPI docs/OpenAPI включены по умолчанию. SPA shell от Nginx/Caddy не получает CSP/HSTS и остальные headers middleware backend. Нет request-size limits и login rate limiting. Login возвращает JWT одновременно в HttpOnly cookie и JSON; это допустимо для CLI, но смешивает browser и CLI threat models.

Задачи: environment-controlled docs; headers на Caddy; CSP; HSTS после TLS validation; body/upload limits; login throttling/lockout/audit; разделить browser cookie login и CLI token issuance; добавить request ID.

Доказательства: `backend/app/main.py:56-65`, `backend/app/main.py:93-97`, `backend/app/api/auth.py:35-88`, `frontend/nginx.conf`, `ops/Caddyfile`.

### AUD-018. Password stack содержит глобальный monkeypatch private API

`main.py` и `services/auth.py` патчат внутренний `passlib.handlers.bcrypt._bcrypt_detect_wrap_bug`, хотя реальные hash/check выполняются напрямую через bcrypt. Комментарий говорит Python 3.14, production image — Python 3.12. Это хрупкая заплатка и потенциальное отключение защитной проверки библиотеки.

Задачи: выбрать один поддерживаемый password stack; убрать Passlib/private monkeypatch; добавить hash-upgrade policy и тесты длинных/unicode passwords.

Доказательства: `backend/app/main.py:14-26`, `backend/app/services/auth.py:4-14`, `backend/app/services/auth.py:31-47`.

### AUD-019. Dependency/release security автоматизирована не полностью

Есть npm lock и прямые Python pins; `pip check` сейчас не находит broken dependencies, offline npm audit сообщает 0 известных production issues в локальном cache. Но `requirements.lock` не фиксирует transitive graph/hashes и Dockerfile устанавливает `requirements.txt`, а не lock. Нет Dependabot/CodeQL/pip-audit/npm-audit jobs; GitHub Actions и Docker base images не закреплены digest/SHA.

Задачи: настоящий hash-locked Python resolution; image SBOM; pip-audit/npm audit в CI; Dependabot; pin actions to commit SHA и images to digest для RC; документированный update cadence.

### AUD-020. Контейнеры работают с лишними привилегиями и инструментами сборки

Backend runtime содержит gcc/g++, запускается root. Frontend Nginx тоже не переводится на non-root. Это увеличивает blast radius и размер image.

Задачи: multi-stage Python build; non-root UID; read-only filesystem где возможно; tmp/uploads volumes с ограничениями; drop capabilities; container scan.

### AUD-021. Git UI несовместим с production image и не должен быть частью публичного runtime

Backend image собирается с context `./backend`; `.git` в него не попадает. В контейнере расчёт `parents[3]` для `/app/app/api/git_versions.py` даёт `/`, поэтому admin Git screen не сможет работать как локально. Если репозиторий смонтировать, branch creation из web app расширяет attack surface.

Задачи: пометить функцию dev-only и отключать routes/nav в production; либо вынести в отдельный admin service с отдельной auth/audit policy. Production smoke должен явно проверять ожидаемое отсутствие функции.

Доказательства: `backend/app/api/git_versions.py:18-20`, `backend/app/api/git_versions.py:49-73`, `backend/app/main.py:130`, `docker-compose.production.yml:20-22`, `backend/.dockerignore`.

### AUD-022. Startup выполняет DDL вопреки заявлению «только Alembic»

После условного SQLite `create_all` приложение всегда выполняет `CREATE INDEX IF NOT EXISTS`, включая PostgreSQL. Это противоречит комментарию, требует DDL rights у runtime user и может дать race/ошибку старта.

Задача: индекс только в Alembic; startup user без DDL; проверка schema head до запуска.

Доказательства: `backend/app/main.py:83-91`, `backend/migrations/versions/20260825_0003_planner_read_indexes.py`.

### AUD-023. Telemetry полезна, но пока локальна и неоперационна

Build telemetry хранит duration, stage timings, SQL count, cache hit и response bytes; endpoint считает p50/p95. Нет общего request ID, очереди/lease metrics, Prometheus/OpenTelemetry/Sentry, alert thresholds, retention policy и dashboards. Ошибка сохранения telemetry не видна клиенту и только логируется.

Задачи: correlation ID; structured logs; metrics endpoint/exporter; job queue depth/stale lease/failure rate; graph/load p95; alert rules; audit/telemetry retention and PII review.

### AUD-024. Runbook проверяет неправильный production health URL

Caddy отправляет backend только `/api/*`, но runbook предлагает `https://DOMAIN/health`; этот путь попадёт во frontend SPA. Нужен `/api/health` либо отдельный Caddy handle.

Задачи: исправить маршрут; проверять JSON body/database status, а не только HTTP 200; добавить compose E2E smoke.

Доказательства: `ops/Caddyfile:4-10`, `docs/PRODUCTION_RUNBOOK_RU.md:5-8`.

## 7. Низкий приоритет — P3

### AUD-025. Визуальная система не формализована

Нет `PRODUCT.md`/`DESIGN.md`; намерения и токены зашиты в JSX/CSS. Повторяющиеся accent-left cards, grid background и большое число inline styles могут создать впечатление шаблонного AI UI, хотя функциональность реальна. Некоторые transitions меняют width и вызывают layout work.

Задачи: короткий product surface brief; UI tokens/components; убрать повторяющиеся декоративные паттерны; проверка responsive layouts 320/768/1440; motion policy.

### AUD-026. Документация содержит исторические статусы рядом с текущими

Архивные STATUS/PLAN документы полезны как журнал, но новый участник может принять старые 38/38 или 98/98 и старые метрики за current truth.

Задачи: единый `CURRENT_STATUS.md`; исторические документы в `docs/history`; на каждом отчёте snapshot/commit/data/model IDs; generated index.

## 8. Приоритизированный backlog внедрения

### Этап 0 — блокеры staging (часть уже реализована)

1. **OPS-01 / Docker+PostgreSQL — P0, runtime закрыт:** устранены повреждённые временные sockets/reparse-точки на C, проверены engine `29.7.2`, persistent data root `D:\Docker\DockerDesktopWSL`, healthy PostgreSQL на 5433, миграции, `/health`, frontend и one-command launcher. Скрипты теперь чистят также sibling `Local\docker-secrets-engine`, а при недоступности reparse-point используют безопасный quarantine. Осталась только регрессионная автоматизация smoke/health для release candidate; VHDX не удалялся и factory reset не выполнялся.
2. **JOB-01 — P0, код закрыт, runtime открыт:** проверить `202 queued`, отдельный worker, heartbeat, cancel, stale recovery, retry и две параллельные генерации.
3. **SEC-01/02 — P0/P1, кодовая база закрыта частично:** провести authenticated HTTP smoke owner/other/admin, cookie+CSRF, rate limits, safe errors и production host/CORS.

### Этап 1 — корректность предметной модели

1. **DOM-01/02 — P1, код закрыт частично:** прогнать все поддержанные programme profiles, проверить UI/API parity и вынести оставшиеся нормативные формулы из Python в единственный versioned ruleset.
2. **PLN-01 — P1, код закрыт частично:** дополнить property/fixed-point tests реальными данным и доказать, что каждый repair сохраняет предыдущие hard-инварианты.
3. **QA-02 — P1, открыто:** провести blind review минимум двумя экспертами по кредитам, ГОСО, prerequisites, семестрам, релевантности и bridge-модулям.

### Этап 2 — доказательная acceptance и миграция

1. **QA-01 — P0 для release candidate:** выполнить 30–50 уникальных inputs разных уровней, языков, юрисдикций, длительностей и типов программ; сохранить manifest, latency и verifier results.
2. **DATA-01 — P0 для release candidate:** на пустой PostgreSQL выполнить SQLite→PostgreSQL counts/FK/hash compare, применить только утверждённую orphan policy и проверить backup restore на shadow DB.

### Этап 3 — frontend, API и CI

1. **FE-01:** завершить разбиение крупных контроллеров backend/frontend и убрать DOM/state coupling.
2. **I18N-01:** довести 197 legacy inline language calls до единого RU/KK/EN catalog; текущий gate лишь не допускает роста.
3. **A11Y/CI:** добавить authenticated Playwright и axe; устранить Vite deprecated warnings.
4. **API-01:** расширить typed request/response models и OpenAPI compatibility checks.

### Этап 4 — production hardening и наблюдаемость

1. **DEP-01:** hash-locked Python/npm graph, SBOM, image digest pinning, dependency scanning.
2. **OBS-01:** вывести request/build timings в dashboards, p50/p95 alerts и retention policy.
3. **OPS-02:** автоматизировать compose E2E, правильный health URL, расписание backup и периодический restore drill.
4. **DEV-01:** исключить Git/dev-инструменты из публичного runtime image и обновить release instructions/manifest/checksum.

## 9. Что можно заявлять после текущего аудита

Корректная формулировка:

> Curriculum-KAG — evidence-constrained система поддержки проектирования учебных планов. Она детерминированно формирует и проверяет варианты, использует экспертные и семантические доказательства, защищает формальные ограничения и сохраняет решение для человеческого утверждения. На фиксированных контрольных профилях текущая версия стабильна и проходит автоматические структурные проверки.

Пока нельзя заявлять без оговорок:

- «готово к безопасной многопользовательской эксплуатации»;
- «30–50 разных программ прошли acceptance» — текущий cohort заблокирован отсутствием Docker/PostgreSQL;
- «SQLite полностью и без потерь перенесён в PostgreSQL»;
- «автоматическая проверка доказывает академическую или юридическую правильность»;
- «поддерживаются все нормативные варианты через UI» — допустимые профили есть в коде, но полный UI/API acceptance ещё не выполнен;
- «production compose готов к запуску на реальном домене без дополнительных настроек» — нужен runtime smoke.

## 10. Рекомендуемый go/no-go

- Локальная демонстрация одному доверенному пользователю: **GO**.
- Закрытый пилот с одним оператором и ручным экспертным review: **GO с фиксацией ограничений**.
- Многопользовательский staging с реальными неопубликованными программами: **NO-GO до AUD-001, AUD-002 и минимального stale-job recovery**.
- Публичный/институциональный production: **NO-GO до P0 и основных P1, затем повторный security/data/acceptance audit**.

## 11. Дополнение аудита 2026-09-03

- **I18N-01:** `PlanSemesterGrid.jsx`, `LoCoveragePanel.jsx`, `PlanQualityPanel.jsx`, `BridgeReplacementPanel.jsx`, CEER-блок `EpvoComparison.jsx`, нормативный блок `ProjectWizard.jsx`, `LOCoverageDashboard.jsx`, основная часть `Repository.jsx` и orchestration/next-generation/change-report messages `PlanBuilder.jsx` используют единый RU/KK/EN catalog; динамические summary/time сообщения используют placeholders. Общий остаток legacy inline-вызовов снижен до **2 из 197**; gate, Vitest 7/7 и production build проходят. Остаток — два экранированных fallback-текста отсутствующих KK/EN описаний `Repository.jsx`, после них можно включить strict zero-inline gate.
- **API-01:** typed response contracts для `build-status` и `build-cancel` добавлены; PostgreSQL endpoint contract проверяет owner/other/admin изоляцию, список проектов и доступ к build-status: **6 базовых + 8 ролевых проверок проходят**.
- **API-01 / OBS-01:** endpoint `/planner/{project_version_id}/performance` получил typed `PlannerBuildPerformanceResponse` с p50/p95, SQL count, response bytes, cache rate и recent samples; контрактные тесты planner/async: **41 passed**, OpenAPI route подтверждает response model.

## 12. Дополнение аудита: закрытие I18N-01

- Все legacy-вызовы `localText(...)` удалены из `frontend/src`; проверка `npm run check:i18n` теперь strict и завершилась с результатом **0**.
- Замены покрывают RU/KK/EN через единый каталог, включая fallback-описания дисциплин в `Repository.jsx`.
- После изменения: Vitest **7/7**, production build успешен, собранный frontend скопирован в `.runtime/dist`.

## 13. Дополнение аудита: Docker repair

- В `scripts/repair-docker-runtime.ps1` исправлен порядок операций: stale-сокеты проверяются до запуска Docker Desktop.
- Ранее скрипт мог ошибочно завершаться ошибкой после успешного запуска, потому что Desktop штатно пересоздаёт эти ephemeral-сокеты.
- Скрипт не изменяет VHDX, WSL data-root, volumes или образы; изменяется только очистка runtime namespace.
- После одного запуска с повышенными правами stale `engine.sock` отсутствует, PostgreSQL отвечает на `127.0.0.1:5433`, PostgreSQL **16.14**, расширение `vector` доступно.
- Полный Docker engine через CLI из текущей оболочки не подтверждён: `docker.exe` не зарегистрирован в PATH. Это отдельный остаточный operational gap, а не ошибка PostgreSQL или переноса VHDX.

## 14. Дополнение аудита: текущий route inventory

- Сгенерирован свежий inventory FastAPI: **85 routes**, из них **45 object-scoped**.
- Для всех 45 object-scoped routes обнаружен access marker (`require_*`/permission dependency); необозначенных object-scoped routes в текущем срезе нет.
- Это подтверждает покрытие dependency-level, но не заменяет реальный owner/other/admin HTTP acceptance для каждого класса объекта.

## 15. Дополнение аудита: migration fail-closed

- Мигратор SQLite → PostgreSQL теперь выполняет preflight FK до подключения/записи в target.
- При грязном источнике без явного manifest миграция завершается ошибкой; на текущей копии это корректно выявляет **205222** нарушений.
- Manifest проверяется по SHA-256 источника и количеству нарушений; таблицы с policy `repair_or_review` блокируют cutover и не могут быть автоматически отброшены.
- Исправлен разбор Windows SQLite URL (`sqlite:///D:/...` и относительных путей). Backend regression после изменения: **131 passed**.
- **A11Y/CI:** authenticated Playwright + axe smoke проходит, frontend E2E — **5/5**. В текущем запуске сохраняются только известные предупреждения Vite о переходе с esbuild на oxc; это технический P2, не функциональный сбой.
- **Release state:** сборка обновлена в `.runtime/dist`; Docker/PostgreSQL не переобъявляются исправленными по одному факту сборки. Для RC по-прежнему обязательны runtime smoke, 30–50 acceptance cases, SQLite→PostgreSQL cutover/restore и dependency/telemetry checks.

## 16. Дополнение аудита: фактический orphan manifest

- Read-only manifest для текущего `backend/curriculum_kag.db` сформирован: **205222** FK-нарушения, source SHA-256 `d664734686c06be8d6648328219db8a00485dceac58b04be2419bb7275704b5d`.
- Классификация: `embeddings 197343` и `match_scores 7760` — discard/regeneration; `bridge_modules 115` и `match_feedback 4` — repair/review.
- Проверка мигратора с manifest корректно остановилась до target-записи на `bridge_modules, match_feedback`. DATA-01 остаётся заблокированным по содержанию данных, а не из-за отсутствия автоматизации.

## 17. Дополнение аудита: strict ownership inventory

- `audit_api_route_inventory.py` теперь завершает CI с ошибкой при любом object-scoped route без access marker; ранее такой отчёт был только информационным.
- Текущий strict запуск: **85 routes**, **45 object-scoped**, **0 unprotected**; backend regression после изменения: **131 passed**.

## 18. Дополнение аудита: breadth acceptance

- Runner получил режим `--resume --rerun-failed`, чтобы повторять только failed cases без повторной генерации всего cohort.
- Frozen breadth cohort подтверждён: **30/30 unique inputs**, **30 passed**, **0 failed**, **0 infrastructure failures**.
- Покрытие: bachelor/standard 6, bachelor/ict-medicine 6, bachelor/ict-agro 6, master/standard 6, doctorate/standard 6.
- Итоговый runtime-артефакт: `.runtime/quality-cohort-breadth-20260903-verified.json`; исходный manifest сохранён, SHA-256 `594003d39a69356e5fad7db94fb376b1da76e5e8b6d0fb376e8ab60bb08e2404`.

## 19. Дополнение аудита: migration safety regression

- Добавлены `backend/tests/test_migration_safety.py`: проверяется отказ dirty SQLite без manifest и отказ manifest, содержащего `repair/review` policy.
- Targeted access/migration safety suite: **16 passed**; Python compile и diff-check проходят.

## 20. Дополнение аудита: dependency maintenance

- Добавлен `.github/dependabot.yml` для weekly updates и security review по `pip`, `npm` и GitHub Actions.
- YAML проверен; полный backend regression после добавления migration tests: **133 passed**.
- Это закрывает регулярный maintenance-контроль, но не выдаётся за SBOM, hash-locked install или image digest pinning.

## 22. Дополнение аудита: rate limit дорогих операций

- `RequestGuardMiddleware` теперь ограничивает `projects/suggestions`, `repository/generate-courses`, `repository/auto-assign-requisites`, `kag/graph/build` и `kag/system/reindex` отдельным configurable лимитом `RATE_LIMIT_EXPENSIVE_PER_TEN_MINUTES` (production default: 10/10 min/IP).
- Добавлен regression-тест с проверкой `429` и `Retry-After`; полный backend regression после изменения: **135 passed**.
- Ограничение пока in-process и per-IP; для нескольких backend replicas требуется PostgreSQL/Redis-backed limiter до production scale-out.

## 23. Дополнение аудита: validation security limits

- Production startup теперь отклоняет неположительные `MAX_REQUEST_BYTES` и login/build/expensive rate limits.
- Добавлен regression-тест конфигурации; полный backend regression: **136 passed**.

## 21. Дополнение аудита: global planner mutations

- Исправлен privilege gap в `/projects` (POST) и `/projects/lo/weights` (POST): оба маршрута требуют `planner:write`; один лишь факт аутентификации больше не достаточен.
- Добавлен regression-контракт RBAC; access/HTTP suite: **17 passed**.
- Strict inventory после изменения: **85 routes**, **45 object-scoped**, **0 unprotected**.

## 24. Дополнение аудита: fail-closed для multiworker rate limit

- Production-конфигурация теперь явно передаёт `WEB_CONCURRENCY` в backend и запрещает значение больше 1, пока limiter остаётся process-local.
- Это устраняет скрытый режим, при котором несколько Uvicorn workers имели бы независимые квоты и фактический лимит обходился бы суммой worker-квот.
- Добавлен regression-тест на отказ `WEB_CONCURRENCY=2`; targeted suite: **18 passed**, полный backend regression: **137 passed**.
- Масштабирование backend replica/worker остаётся отдельной задачей: перед включением требуется общий PostgreSQL/Redis-backed limiter и соответствующий production E2E-тест.

## 25. Дополнение аудита: точные пары объёма программы

- `profile_for()` теперь сопоставляет `(кредиты, семестры)` как связанные пары, а не как два независимых множества. Это закрывает ошибку принятия, например, 180 кредитов за 8 семестров в international bachelor.
- Wizard использует тот же endpoint `/api/projects/program-profiles` для bachelor/master/doctorate и блокирует ручное рассогласование длительности при наличии профиля.
- Backend regression: **139 passed**; frontend Vitest: **7 passed**, i18n gate: **0 inline-language calls**, production build: **успешно**.

## 26. Дополнение аудита: security input hardening и CI gates

- Admin-only GNN/LSTM smoke routes больше не принимают произвольный `dict`: введены строгие Pydantic-контракты, `extra=forbid` и верхние границы вычислительных параметров.
- Это закрывает путь к неконтролируемому расходу CPU/RAM через `epochs`, `program_limit`, `batch_size` и `max_seq_len`; серверная RBAC-проверка admin сохраняется.
- Backend security regression после изменения: **139 passed**. Static quality gate, dependency profile и release hygiene: **passed**.
- Frontend graph-style gate, i18n gate и Vitest: **passed**; i18n inline-language calls: **0**.
- Остающиеся security/operations items: общий limiter для scale-out, SBOM/hash-locked install, image/action digest pinning и production runtime E2E.

## 27. Дополнение аудита: planner mutation permissions

- Все проверенные state-changing planner endpoints (`build`, `build-retry`, `build-cancel`, `recompute-matches`, course exclusions, `toggle-active`) теперь требуют `planner:write` поверх object ownership.
- Добавлен regression-контракт permission matrix; полный backend regression: **140 passed**.
- Strict API inventory: **86 routes**, **46 object-scoped**, **0 unprotected**.

## 28. Дополнение аудита: real authenticated browser CI

- Ранее authenticated Playwright сценарий полностью mock-ил API и доказывал только отрисовку оболочки.
- Добавлен отдельный CI job `authenticated-browser`: изолированный SQLite seed, реальный FastAPI, Vite preview и Playwright-проверка login, HttpOnly `access_token`, readable CSRF cookie, dashboard и axe critical/serious violations.
- Mock UI smoke сохранён отдельно; real-browser job не считается локально пройденным до запуска CI runtime.
- Статические проверки нового контура: seed, YAML parse, Python compile и diff-check — passed. Локальный frontend regression: **7/7**, build/i18n/graph gates — passed.

## 29. Дополнение аудита: typed planner body contracts

- Syllabus draft save/export и semester insight переведены с произвольных `dict` на вложенные Pydantic-контракты с ограничениями недель, часов, кредитов, режима и языка.
- OpenAPI теперь описывает эти входы явно; старые корректные frontend payload остаются совместимыми.
- Полный backend regression: **140 passed**; strict inventory: **86 routes**, **46 object-scoped**, **0 unprotected**.

## 30. Дополнение аудита: real browser smoke подтверждён

- Локальный изолированный runtime с FastAPI + SQLite seed + Vite proxy успешно прошёл `authenticated-real.spec.js`: **1/1**.
- Проверены реальный browser login, переход на dashboard, HttpOnly `access_token`, readable `csrf_token`, SameSite=Lax и axe critical/serious violations.
- Playwright `baseURL` и Vite backend target вынесены в environment overrides, поэтому старые процессы на стандартных портах больше не дают ложный результат.
- В CI сохранён отдельный job с тем же сценарием; production frontend build проверяется независимым job.

## 32. Дополнение аудита: production edge/static gates

- `verify-public-release.ps1`: **passed**, проверено **494 tracked paths**, tracked secrets/databases/models не обнаружены.
- Dockerfile backend запускается non-root; frontend healthcheck использует `/healthz`; backend/Compose healthcheck использует `/health`; Caddy проксирует `/api` и frontend раздельно.
- Docker Compose runtime validation и production E2E остаются pending, поскольку Docker CLI/Desktop недоступен в текущем shell.

## 31. Дополнение аудита: edge headers и устойчивый browser runtime

- Caddy теперь задаёт CSP и `Permissions-Policy` наравне с frontend nginx/backend.
- Vite proxy target и Playwright baseURL вынесены в environment overrides; это устраняет тихое переключение на другой порт при оставшихся старых процессах.
- Реальный authenticated browser smoke после запуска на свободных портах: **1/1 passed**; корректный backend regression: **140/140**.
