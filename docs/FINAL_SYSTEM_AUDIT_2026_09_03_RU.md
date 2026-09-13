# Финальный системный аудит Curriculum-KAG — 03.09.2026

## Краткий вывод

Система уже представляет собой полноценный прикладной сервис проектирования учебных программ, а не демонстрационный AI-прототип. В ней есть PostgreSQL-режим, миграции, асинхронная генерация с lease/heartbeat, RBAC и ownership, формальный валидатор планов, объяснимые evidence/bridge-связи, RU/KK/EN интерфейс, граф пререквизитов, экспорт и регрессионные проверки.

Текущий статус: **сильный staging-кандидат; production/RC ещё не подтверждён**. Главные незакрытые пункты — чистый production runtime E2E после reboot, исправление грязных SQLite orphan-данных, backend image SBOM/release evidence и эксплуатационные метрики/алерты.

Последнее evidence-обновление: OpenAPI gate расширен до **10 request-схем и 12 критичных операций**; typed contracts покрывают planner, bridge, feedback и EPVO priority mutation endpoints. Полный backend regression после расширения контрактов: **172/172 passed**; добавлены typed profile response, compose-security и cookie/CLI transport tests.

### Оценка инженерного аудита

| Измерение | Балл | Основание |
|---|---:|---|
| Backend correctness/security | 3/4 | 172 теста, RBAC/ownership/CSRF, typed API и cookie/CLI separation; runtime Postgres/Docker ещё не закрыт после reboot |
| Frontend a11y/hardening | 2/4 | есть axe smoke, error/retry и текстовая альтернатива графа; остаются сложные панели и длинные i18n-ветки |
| Performance/observability | 3/4 | stage timings, aggregate planner observability, Research Dashboard panel, structured 5xx logs, bounded health/backup monitor и retention есть; deployment-level p95/DB/restore alerts ещё не подключены |
| Data/migration assurance | 2/4 | backup restore подтверждён; SQLite имеет 205222 orphan FK и требует policy-driven cutover |
| Release/reproducibility | 3/4 | Compose/image pins, GitHub Actions SHA pins, hash-locked Python install и CI SBOM artifacts есть; финальный image SBOM и release CI evidence не завершены |
| **Итого** | **11/20** | **приемлемо для staging/контролируемого пилота; не release-ready** |

Это не оценка «система плохая»: баллы снижают именно недоказанные эксплуатационные свойства, а не наличие функций.

## Что проверено фактически

Последний локальный контрольный прогон: 03.09.2026. Backend regression и целевые security/migration/property tests проходят; при повторной диагностике Docker daemon снова не поднят (`dockerDesktopLinuxEngine` отсутствует), PostgreSQL `5433` недоступен, VHDX по-прежнему находится на `D:`. Дополнительная диагностика возвращает `WSL/EnumerateDistros/Service: E_ACCESSDENIED`, то есть текущий запуск не имеет доступа к WSL service layer.

Дополнительно подтверждено по коду: production settings отвергают не-PostgreSQL `DATABASE_URL`, короткий/шаблонный `SECRET_KEY`, небезопасные cookies, публичные docs, wildcard/URL в `ALLOWED_HOSTS` и невалидные CORS origins; соответствующие проверки входят в `backend/tests/test_access_layer.py`.

| Область | Результат | Статус |
|---|---|---|
| Backend regression | 172/172 теста через `backend\\venv\\Scripts\\python.exe`; добавлены migration source-path, security-header/CSRF, compose-security и transport-separation regression tests | закрыто |
| Backend coverage | CI запускает branch coverage и сохраняет XML artifact | baseline/порог ещё не подтверждены CI |
| Browser evidence | frontend и authenticated Playwright jobs сохраняют test-results при успехе/ошибке | workflow добавлено; GitHub run ещё нужен |
| API access inventory | 90 routes, 46 object-scoped, 0 без access-marker | закрыто на уровне кода; нужен HTTP acceptance owner/other/admin |
| OpenAPI planner contract | 10 typed request-схем и 12 критичных операций присутствуют | закрыто static gate’ом |
| Генерация breadth cohort | Post-domain-fix frozen manifest: 30/30 completed, 30/30 passed, 0 failed; 5 профилей по 6 случаев; `distinct_input_count=30`; SHA `959d6f2e…48eadb` | закрыто для текущего frozen cohort; production-image cohort ещё нужен |
| PostgreSQL stability cohort | 5/5 свежих прогонов, 0 failed: bachelor/master/doctorate standard, ict-medicine, ict-agro; 264.19 s суммарно | закрыто для текущего shadow runtime; production image cohort ещё не выполнен |
| Production image generation | frozen `ict-medicine` control case прошёл: 240 credits, hard violations 0, ГОСО/quality passed, 55.18 s; диагностический focus завершался контролируемым quality-fail без 500/timeout | расширенный production-image cohort ещё нужен |
| Quota diagnosis/fix | Исправлен разрыв alias admission `Medicine ↔ Здравоохранение` и рассинхрон bridge envelope; контрольный прогон 912: `domain2=69.5/68`, hard violations 0, quality/GOSO passed, 8 bridges включая отдельный core, bridge contract passed, 58.5 s; post-fix breadth 30/30 | production-image cohort и migration gates остаются |
| Frontend | Vitest 8/8, build, i18n inline gate 0, graph-style gate | закрыто на static/unit уровне |
| Реальный browser smoke | login, dashboard, cookies, axe: 1/1 локально | локально закрыто; CI-run pending |
| PostgreSQL backup restore | checksum, Alembic head, counts/FK в изолированной БД | подтверждено для имеющегося backup |
| SQLite → PostgreSQL | Frozen FK scan: 205222 orphan FK; non-destructive manifest с checksum `d6647346…704b5d` сохранён в `.runtime/sqlite-fk-discard-manifest-2026-09-03.json` | не закрыто по данным; требуется discard/regeneration и review policy |
| Docker Desktop | ранее подтверждены VHDX на `D:`, Docker 4.88.1/engine 29.7.2, PostgreSQL healthy на `5433`, one-command launcher и health smoke | в текущем сеансе daemon снова недоступен из-за stale runtime sockets; нужен ручной UAC repair и повторный runtime smoke, VHDX не переносится на `C:` |
| Production Compose isolation | backend image собран, миграции PostgreSQL прошли, все 3 сервиса healthy, proxy поднят на изолированных портах; исправлены передача `DOMAIN` в backend, Host-aware healthcheck, `init` и `no-new-privileges` | TLS/ACME требует реального домена и DNS; generation cohort именно внутри production image ещё не проведён |
| Supply-chain | exact version pins, Dependabot есть; production base/service images закреплены digest’ами, GitHub Actions закреплены официальными SHA, backend non-root, frontend `nginxinc/nginx-unprivileged`, runtime UID 101 подтверждён; frontend SPDX SBOM и backend CycloneDX dependency SBOM генерируются в CI artifacts; Python lock содержит hashes и Docker использует `--require-hashes`; `npm audit --omit=dev` и `pip-audit` чистые | backend image SBOM indexing и финальный release CI run требуют отдельного Docker/CI прогона |
| Performance telemetry | duration, stage timings, SQL count, p50/p95 сохраняются в audit event; EPVO fingerprint в scoring stage переиспользуется; performance API сравнивает p95 с `PLANNER_P95_BUDGET_MS` | telemetry retention добавлен; alerts/dashboard и runtime p95 budget ещё не подтверждены |

После аудита исправлен production backup runner: `scripts/backup-postgres-production.ps1` теперь явно требует `.env.production`, передаёт `--env-file` в Compose, читает `POSTGRES_USER/POSTGRES_DB` из того же файла и не зависит от состояния текущей PowerShell-сессии. Также production Compose теперь передаёт `DOMAIN` backend-контейнеру, а healthcheck отправляет разрешённый Host. Реальный backup-run остаётся частью Docker runtime smoke.

## Как система работает

1. Пользователь создаёт проект и версию программы: уровень образования, профиль, домены, язык, кредиты и семестры.
2. Backend проверяет входные ограничения, профильный объём и права пользователя.
3. Генератор синхронизирует/использует EPVO evidence, считает course–LO связи и строит варианты A/B/C.
4. План проходит admission и repair: кредиты, ГОСО, семестровую нагрузку, пререквизиты, дубли, уровень/контекст дисциплин и покрытие LO.
5. Для недостаточного реального покрытия создаётся явно помеченный bridge-module; он не маскируется под обычную дисциплину.
6. Результат сохраняется транзакционно; прогресс, lease, cancellation, retry и idempotency защищают долгую генерацию.
7. UI показывает варианты, качество, объяснение связей, граф, замены, семестры, локализацию и экспорт.
8. Audit trail хранит изменения, результаты проверок и измерения генерации.

## Найденные пробелы и задачи

### P0 — до внедрения

1. **Docker/операционная среда**
   - после следующей перезагрузки подтвердить запуск Docker Desktop с VHDX на `D:`;
   - проверить фактическую публикацию PostgreSQL на `localhost:5433`;
   - выполнить генерацию в чистом production runtime; image build, startup, `/health` и миграции уже прошли в изолированном Compose E2E;
   - запретить RC-тег без успешного production runtime smoke.

2. **Данные миграции**
   - отдельно обработать `embeddings` и `match_scores` по discard/regeneration policy;
   - исправить или экспертно разобрать `bridge_modules` (115) и `match_feedback` (4);
   - повторить полный SQLite→PostgreSQL compare, orphan check и restore;
   - не разрешать cutover при оставшихся repair/review orphan-строках.

3. **Финальный acceptance**
   - выполнить 30–50 новых программ в чистом PostgreSQL runtime;
   - добавить owner/other-user/admin HTTP-проверки для каждой группы object routes;
   - сохранить входной cohort, версии модели/ruleset, checksum базы и итоговый manifest.

### P1 — до RC

4. **Supply-chain и воспроизводимость**
   - сгенерировать SBOM;
   - включить hash-locked pip/npm installation (Python production lock уже закрыт; остаётся проверить npm provenance в release evidence);
   - Docker base/service images digest’ами закреплены; добавить автоматическую проверку pinning в release gate;
   - GitHub Actions уже закреплены официальными commit SHA; добавить автоматическую проверку обновления/allowlist в release evidence.
   - разделить CPU-only production ML dependencies и CUDA-пакеты: текущий full lock устанавливает CUDA wheels на CPU-хосте и заметно увеличивает время/размер сборки.

5. **CI quality gate**
   - дополнить pytest-запуск покрытием `coverage.py`;
   - определить минимальный порог backend/frontend coverage;
   - запускать настоящий authenticated browser job в GitHub и сохранять артефакты;
   - OpenAPI schema/contract check добавлен в workflow и локально проходит: 10 schemas, 12 operations;
   - coverage measurement и baseline `--fail-under=30` добавлены в workflow; после первого CI run baseline следует пересмотреть вверх по мере роста покрытия и сохранять результат как release evidence.

6. **Эксплуатация**
   - retention для planner telemetry добавлен через `purge_audit_telemetry.py`; подключить его к расписанию после backup;
   - добавить alerts на build failure, stale lease, p95 generation, 5xx, DB saturation и backup age;
   - вынести rate limiter из process-local режима перед масштабированием replicas/workers;
   - определить runbook восстановления и ответственного за backup restore drill.

### P2 — после RC

7. **Методическая валидация**
   - провести blind review двумя экспертами и посчитать inter-rater agreement;
   - отделить software correctness от предметной/аккредитационной валидности;
   - регулярно пересматривать ГОСО ruleset по версии, источнику и дате действия.

8. **Frontend hardening**
   - завершить декомпозицию крупных страниц;
   - добавить keyboard/ARIA/axe coverage для графа и сложных панелей;
   - убрать оставшиеся inline-копии и проверить fallback/длину строк KK.

## Дополнительный проход аудита — обнаруженные пробелы

### AUD-07 — inline-локализация остаётся системным риском (P2)

- `ResearchDashboard.jsx`, `GitVersions.jsx` и `planBuilderPresentation.js` используют общий `localizedCopy`; локальных `ru/kk/en` helpers теперь 0, inline-language gate проходит.
- Для новых/исправленных сообщений `Repository`, `PlanBuilder`, `LOCoverageDashboard` и error boundary добавлены ключи/локализованные fallback-строки; gate остаётся 0/0, выбор языка не ломается.
- Часть исследовательских подписей всё ещё хранится рядом с presentation-логикой через единый `l(ru, kk, en)`, поэтому полная централизация каталога остаётся P2-задачей, но это не дефект выбора языка.

Задачи: перенести оставшиеся presentation-строки в `translations.js`, добавить проверку отсутствующих ключей/параметров и проверить расширение KK на узких экранах.

### AUD-08 — повторяющийся визуальный anti-pattern и layout transition (P2)

Механический detector Impeccable нашёл 16 предупреждений: повторяющиеся `borderLeft: 4/5px solid` в `CourseSyllabus`, `EpvoComparison`, `LOCoverageDashboard`, `PlanBuilder`, `PrerequisiteGraph`, `ProjectDetails`, `ResearchDashboard`, `CompactSection`, `PlanBuildProgress`; также `transition: width` в `LOCoverageDashboard:634` и `PlanBuildProgress:31`, декоративную grid-подложку графа в `PrerequisiteGraph:204`.

Задачи: оставить акцентные границы только там, где они несут семантику статуса, перевести анимацию на transform/opacity или grid rows, затем выполнить один визуальный smoke на desktop/mobile и keyboard.

### AUD-09 — крупные файлы сохраняют стоимость изменений (P1)

Фактический скан показывает файлы более 30 KB: `backend/app/planner/scheduler.py` (68 KB), `frontend/src/translations.js` (121 KB), `frontend/src/pages/PlanBuilder.jsx` (58 KB), `backend/app/api/planner_coverage.py` (52 KB), `frontend/src/pages/LOCoverageDashboard.jsx` (50 KB), `backend/app/api/epvo.py` (47 KB), `backend/app/api/planner_build.py` (43 KB) и другие.

Это не доказательство неправильности, но повышает риск регрессий, скрытых условий и конфликтов при внедрении. Задачи: выделить orchestration/domain rules/serializers/hooks, зафиксировать публичные контракты тестами и рефакторить по одному модулю с регрессией после каждого шага.

### AUD-10 — production-доказательства ещё не автоматизированы (P1)

Static/локальные проверки проходят, однако в рабочем дереве нет факта успешного GitHub CI run после последних изменений. Coverage XML генерируется, но порог не установлен; authenticated browser job и production-image generation должны быть подтверждены артефактами конкретного запуска.

Задачи: выполнить CI, сохранить run URL/commit, установить минимальные thresholds после первого baseline, приложить 30–50 cohort manifest, image digest, DB checksum и backup-restore evidence к RC.

### AUD-11 — отдельные ML-smoke процессы не имеют надёжного контроля живости (P1, исправлено локально)

- `backend/app/api/epvo.py` сохраняет `pid` и текстовый статус для GNN/LSTM smoke, но status endpoint не проверяет, существует ли процесс с этим PID, и не переводит запись в terminal state при аварийном завершении без `metrics.json`.
- Риск: администратор видит вечный `running` и вынужден использовать `force`, что может запустить второй тяжёлый процесс и увеличить нагрузку/занять ресурсы.
- Исправлено: status и run endpoints проверяют PID, переводят orphaned status в `failed`, сохраняют диагностическое сообщение и не считают отсутствующий процесс живым. Добавлены регрессионные тесты для missing PID и живого процесса; полный backend regression после исправления — 145/145.
- Добавлены admin-only endpoints отмены для GNN/LSTM и кнопки отмены в Research Dashboard: PID проверяется по ожидаемому script path, безопасное завершение фиксируется как `cancelled`; неподтверждённый PID не трогается.
- Исправлена response-схема telemetry: p50/p95 допускают `null` при отсутствии samples, поэтому пустое состояние мониторинга не превращается в HTTP 500.
- Дополнительно добавлен bounded stale-timeout: живой smoke без metrics старше 6 часов переводится в `failed`; пока PID жив и лимит не истёк, второй запуск запрещён.

### AUD-12 — production backup runner ждёт native process без верхнего лимита (P1, исправлено локально)

- Исправлено: добавлен параметр `-TimeoutSec` (30–86400, по умолчанию 1800), ожидание с bounded timeout, остановка только процесса Docker CLI, сохранение stderr и понятная timeout-ошибка. Большой dump в runtime пока требует отдельного Docker smoke.

### AUD-13 — повторный EPVO fingerprint замедлял scoring stage (исправлено локально)

- До исправления `scoring_input_signature()` заново строил полный EPVO fingerprint, хотя build уже вычислил его для EPVO cache stage.
- Исправлено: scoring принимает и переиспользует готовый signature; добавлен regression-тест, запрещающий повторный вызов fingerprint в этом пути. Полный backend regression после изменения — 145/145.

### AUD-14 — отмена не должна продлевать lease зависшего worker (исправлено локально)

- До исправления `request_build_cancel()` проходил через общий `set_build_status()`;
  для состояния `running` это обновляло heartbeat и продлевало lease.
- Исправлено: cancel теперь сохраняет только `cancel_requested=1`, оставляя
  исходный lease неизменным; зависший worker не может скрываться дольше из-за
  повторных запросов отмены. Добавлен regression-тест; полный backend regression
  после изменения — 145/145. При гонке с завершением worker snapshot теперь
  синхронизируется с terminal-строкой под row lock и не публикует устаревший
  `running`.

### AUD-16 — staging tag должен проверять release policy manifest (исправлено локально)

- До исправления tag gate проверял наличие manifest и соответствие commit, но не
  валидировал обязательные поля поставки базы, миграций, модели и EPVO.
- Исправлено: перед тегированием проверяются все четыре поля, требование
  PostgreSQL backup/restore и отдельная поставка модели. Неполный manifest теперь
  отклоняется до создания тега.

### AUD-17 — прокрутка из LO-панели зависела от глобального DOM (исправлено локально)

- `LoCoveragePanel` находил семестр через `document.querySelector`, что связывало
  компонент с глобальной разметкой и могло ломаться при повторном рендере.
- Исправлено: `PlanBuilder` передаёт React ref-карту через `PlanSemesterGrid`, а
  панель вызывает явный `onShowSemester` callback. Проверки i18n `0/0`, Vitest
  `7/7` и production build проходят.

### AUD-15 — detached worker не должен оставлять job вечно queued (исправлено локально)

- До исправления stale-reconciliation обрабатывала только `running`; падение
  процесса между постановкой job в очередь и фактическим стартом worker могло
  оставить истёкший `queued` навсегда и блокировать retry.
- Исправлено: истёкшие lease для `queued` и `running` переводятся в
  `timed_out`; добавлен regression-тест для queued-сценария.

### AUD-01 — нормализация доменов неполная (P1)

- `backend/app/planner/scheduler_domain_rules.py:8-24` сопоставляет домен через substring-проверку.
- В данных одновременно встречаются `Medicine`, `Здравоохранение` и повреждённые/английские варианты. Для профиля `ict-medicine` это даёт воспроизводимый результат `domain2=44/68` при `quality_passed=true` и `hard_violations=1`.
- Это не следует исправлять снижением ГОСО-квоты или бесконтрольным увеличением bridge-модулей: нужен единый нормализованный справочник alias → canonical domain, provenance и отчёт о нераспознанных метках.

Исправление в текущем проходе:

1. `variant_admission.py` теперь использует canonical alias matcher для secondary-domain admission.
2. `bridge_policy.py` согласует interdisciplinary envelope с verifier/acceptance policy.
3. Контрольный прогон 912 подтвердил квоту `69.5/68` и `hard_violations=0`.

Оставшаяся задача:

1. Ввести полноценный canonical domain key для RU/KK/EN/legacy labels во всех слоях.
2. Добавить feasibility preflight: доступные реальные кредиты второго домена, prerequisites, остаточная квота и bridges.
3. Расширить regression-case в финальный cohort.

### AUD-02 — единый root-level pytest entrypoint (закрыто)

- Корневой `pytest.ini` задаёт `testpaths = backend/tests`, `pythonpath = backend` и единые options.
- Проверка из корня `backend\\venv\\Scripts\\python.exe -m pytest backend/tests -q`: **145 passed**.
- Команда добавлена в раздел Verification README; ручной аудит больше не зависит от текущей директории.

### AUD-05 — локальный frontend dependency tree повреждён/заблокирован (P2, исправлено локально)

- При повторной проверке `npm ci --ignore-scripts --no-audit --no-fund` восстановил дерево из `package-lock.json` (306 packages).
- После восстановления: production build успешен, Vitest 7/7, i18n и graph gates успешны. Остались только предупреждения Vite о deprecated `esbuild` options.
- Это была локальная средовая проблема; CI с чистым `npm ci` остаётся источником истины.

Задача: добавить в runbook безопасное закрытие процессов, удерживающих `esbuild.exe`, затем восстановление зависимостей из lockfile; не удалять рабочие данные и не использовать это как повод менять lockfile.

### AUD-03 — release provenance ещё не полностью доказана (P1)

- Frontend SPDX SBOM и backend dependency SBOM уже создаются в CI artifacts из lock-файлов; backend image SBOM требует отдельного Docker-прогона.
- `pip` lock фиксирует версии и hashes для прямых и транзитивных пакетов, а backend Dockerfile включает `pip --require-hashes`; GitHub Actions закреплены официальными commit SHA, PostgreSQL service image в CI также закреплён digest’ом, статический gate проверяет оба типа pinning. `pip-audit` добавлен в CI и локально не обнаружил известных уязвимостей; неподдерживаемая цепочка `python-jose` заменена на PyJWT. Backend image SBOM ещё требует отдельного Docker-прогона.

Задача: публиковать для каждого RC manifest, image digest, SPDX SBOM и hash-locked dependency evidence; тяжёлые CUDA-зависимости отделить от CPU-only production image.

### AUD-04 — runtime acceptance после переноса Docker остаётся внешним gate (P0)

- Ошибки `sailor-ingest.sock`, `dockerInference.sock` и `docker-secrets-engine/engine.sock` относятся к runtime-сокетам Docker Desktop в профиле пользователя, а не к возврату VHDX на `C:`.
- Текущий daemon/Compose smoke был успешен, но гарантия «навсегда» невозможна без повторного reboot на машине пользователя.

Исправление в текущем проходе: `start.ps1` теперь при обнаружении stale-сокетов вызывает существующий `repair-docker-runtime.ps1` через один контролируемый UAC-запрос и ждёт его завершения. Проверка WSL перенесена после cleanup: `E_ACCESSDENIED` больше не блокирует попытку очистить stale runtime; порядок закреплён launcher regression gate. `start.bat` возвращает ненулевой код при отмене UAC. VHDX/data-root/volumes не затрагиваются. Остался внешний runtime gate: после reboot нужно подтвердить фактический daemon/Compose smoke.

Задача: после reboot одним запуском выполнить `start.ps1 -NoBrowser`, проверить daemon, PostgreSQL `5433`, `/health`, миграции и одну длительную генерацию; при повторе сокета собирать diagnostics и выполнять только сценарий `Quit → stale runtime cleanup → restart`, не `Reset factory defaults`.

### AUD-06 — SQLite orphan data классифицирована, но не обработана (P0)

Создан non-destructive manifest `.runtime/sqlite-fk-discard-manifest-2026-09-03.json` с SHA-256 источника `d664734686c06be8d6648328219db8a00485dceac58b04be2419bb7275704b5d`:

- `embeddings`: 197343 — discard и regenerate после cutover;
- `match_scores`: 7760 — discard и regenerate после повторного scoring;
- `bridge_modules`: 115 — repair/review, не удалять автоматически;
- `match_feedback`: 4 — экспертный review до discard.

Manifest только описывает нарушения и не выполняет destructive action. До выполнения этих решений SQLite→PostgreSQL нельзя считать завершённой.

Техническая проверка orchestration проведена 03.09.2026 на отдельной пустой PostgreSQL target DB. Wrapper теперь корректно нормализует Windows source path и передаёт manifest; миграция остановилась fail-closed на ожидаемых `bridge_modules` и `match_feedback`, не создавая частичный cutover. В исходном SQLite эти записи относятся к 12 отсутствующим `project_versions` (115 bridge rows) и 2 feedback rows; требуется сохранить/экспортировать их review evidence и принять явное решение перед повторным запуском.

Полный read-only review archive создан в `.runtime/sqlite-orphan-review-archive-20260903.json`: 115 bridge rows и 2 уникальные feedback rows (4 FK violation entries), SHA источника совпадает с manifest. Backend regression после добавления инструмента: 145/145.

### QA-02 — усилена защита экспертной рубрики

`backend/scripts/score_expert_rubric.py` теперь требует непустые уникальные
анонимные plan IDs и строгие boolean-флаги для software/content validity.
Строковые значения, дубли и неанонимные записи отклоняются; software validity и
content validity по-прежнему считаются раздельно. Проверка рубрики: 3/3.

### I18N-01 — закрыты обнаруженные inline-строки в критичных действиях

Подтверждение удаления курса и кнопка предложения целей в `Repository` и
`ProjectWizard` переведены на единый каталог RU/KK/EN. После изменения
production build успешен, frontend tests `7/7`, i18n gate `0`.

В текущем проходе gate усилен: локальные `ru/kk/en`-helpers теперь являются
ошибкой CI, а не предупреждением. Повторная проверка: inline-language calls `0`,
local locale helpers `0`.

Дополнительно подписи retry, текстовой альтернативы, источников связей,
`aria-label` и карточек рёбер в `PrerequisiteGraph` переведены на каталог.
Остаточные inline-ветки в аналитических панелях остаются отдельной задачей
полного zero-inline перехода.

Ключевые панели покрытия и замен также больше не содержат видимых literal-
подписей `AI`, `EPVO` и `bridge`: они используют `ai_short`, `epvo_short` и
`bridge_short` из каталога. Проверены i18n gate `0/0`, Vitest `7/7` и build.

Предупреждение о неполной настройке ЕПВО и placeholder-подписи формы в
`ProjectDetails` также вынесены в шесть RU/KK/EN ключей; критичное объяснение
теперь не остаётся русскоязычным при переключении локали.

Дополнительно локализованы подписи `ЕПВО эксперт`, `эксперт`, сохранение
настройки и перестройка плана в `ProjectDetails` и карточке графа. Повторная
проверка каталога: i18n `0/0`, Vitest `7/7`, production build PASS.

Для долгой генерации polling в `PlanBuilder` увеличен до 30 секунд, повтор после
ошибки — до 60 секунд; это снижает лишнюю нагрузку на API/БД и не влияет на
скорость самого построения.

Блок объяснения семестра в `PrerequisiteGraph` также переведён на каталог:
состояние анализа, кнопка запуска AI и источник объяснения теперь имеют RU/KK/EN
ключи. Проверка после изменений: build успешен, Vitest `7/7`, i18n gate `0`.

### AUD-18 — граф вычислял активный семестр через глобальный DOM (исправлено локально)

- `PrerequisiteGraph` использовал `document.querySelectorAll` и `dataset` в
  scroll-handler, из-за чего состояние React зависело от глобальной разметки.
- Исправлено: `CourseStage` регистрирует элементы в локальной `Map` refs, а
  handler работает только с этой картой и удаляет refs при unmount. i18n gate
  `0/0`, Vitest `7/7` и production build проходят.

## Что нельзя заявлять без дополнительных доказательств

- Docker Desktop гарантированно исправлен навсегда — так заявлять нельзя; 2026-09-04 daemon и PostgreSQL прошли one-command runtime smoke, а production Compose config и изолированный backup restore прошли проверки. Остаётся повторить этот evidence после reboot на целевом staging-хосте.
- SQLite миграция завершена — legacy source содержит 205222 orphan FK.
- AI-рекомендации аккредитационно корректны — автоматические проверки доказывают программные инварианты, но не заменяют экспертную оценку.
- Система масштабируется горизонтально без дополнительных operational доказательств — production limiter уже общий через PostgreSQL, но нужны runtime/CI проверки нескольких workers и наблюдаемость.
- Release полностью воспроизводим — пока нет backend SBOM и подтверждённого CI release run.

## Оценка уровня

Для одного разработчика это **высокий уровень инженерной работы**: сложный доменный backend, PostgreSQL/pgvector, асинхронный worker-контур, формальные ограничения планировщика, multilingual frontend, explainability, миграции и security hardening находятся в одном продукте. До enterprise production уровня не хватает не «ещё одной фичи», а операционной доказательной базы: повторяемого Docker runtime после reboot, миграционного cutover, внешней экспертной валидации, supply-chain attestation и наблюдаемости.

Итоговая формулировка для внедрения: **система функционально зрелая для staging и контролируемого пилота; production release следует разрешать только после P0 и обязательных P1 gates выше**.
