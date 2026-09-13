# Задачи для поэтапного исполнения другими моделями

Это план работ, не отчёт о выполненных исправлениях. Все T01–T18 на момент создания документа — **не выполнены в рамках этого аудита**. Некоторые базовые механизмы уже есть; исполнитель обязан проверить актуальное дерево, чтобы не дублировать предыдущие изменения. Диагнозы F01–F16 и доказательства — в соседнем `01_SENIOR_AUDIT_RU.md`.

## Правила выдачи задачи

Рабочий каталог: `D:\curriculum-kag\curriculum-kag`. Не использовать `git reset/checkout` и не откатывать чужие незакоммиченные изменения. Не публиковать, не переносить данные, не запускать полный cohort без задачи T17 и разрешённого тестового окружения. Не выдавать mock/test-only прохождение за runtime-проверку PostgreSQL.

Один запрос исполнителю — один Txx или один указанный подпункт. Не объединять функциональное исправление с массовым форматированием. До исправления добавить regression, который демонстрирует проблему; после — подтвердить исправление и соседний неизменившийся контракт. Characterization фиксирует только приемлемое поведение: известный дефект не превращать в вечный golden.

Запрещено ради зелёных проверок: повышать max_new_courses; снижать минимальное покрытие; отключать ГОСО, second-domain quota, prerequisite или уникальность; менять входной смысл программы; увеличивать timeout без измерений; засчитывать старый output как новый; добавлять `if program_name == ...`.

### Очерёдность

| Волна | Задачи | Результат |
|---|---|---|
| 1. Доверять проверкам | T01, T02, T11 | Честные attempts, зафиксированные контракты и baseline времени |
| 2. Безопасно исполнять | T03a → T03b → T03c, T04, T05 → T06 | Предсказуемый job-протокол, снимок входа, атомарная публикация |
| 3. Исправить смысл | T07, T08, T09 → T10 | Ограничения пользователя и независимая проверка результата |
| 4. Ускорить и упростить | T12, T13 → T14; T15 после job-контракта | Общий контекст, cache, bounded repairs, согласованный UI |
| Параллельно данным | T16 | Честное сравнение и восстановление без вмешательства в рабочую БД |
| 5. Приёмка | T17 → T18 | 20 разных запросов, 60 вариантов и реальные экспертные решения |

T07/T08 можно делать параллельно с T03, если не пересекаются файлы. T14 пересекает scheduler/policies: не поручать нескольким агентам одновременно. Частичная техническая приёмка возможна до полного рефакторинга, но не до устранения влияющих на неё P1.

## T01 · P1/P2 · Ремонт доверия к QA-runner

Источники: [cohort runner](D:/curriculum-kag/curriculum-kag/backend/scripts/audit_quality_cohort.py), [EPVO status](D:/curriculum-kag/curriculum-kag/backend/app/api/epvo.py), [тесты](D:/curriculum-kag/curriculum-kag/backend/tests/test_quality_cohort_manifest.py). Связь F09/F15.

1. Каждый запуск и каждая попытка получают разные run_id/attempt_id и output-файлы. Писать progress через временный файл и атомарную замену.
2. Успех = exitcode=0 AND свежий завершённый report текущей попытки AND все проверки passed. Старый файл/битый JSON/пустой вывод/чужой manifest — failure, не success.
3. Retry только для явно классифицированной временной инфраструктурной ошибки, не для дефекта кредитов/смысла. Хранить все durations, включая неудачи и ожидания.
4. Resume с exclusive lock и проверкой process identity; на Windows — read-only handle/create_time, не отправка сигналов. Не делать вывод о конкретных падениях по одному `os.kill`.

Приёмка: искусственные child-сценарии success, exit1 со старым passed-файлом, timeout, повреждённый output, два concurrent resume, повторное использование PID. Тесты только на собственных disposable child. Parent проверяет завершение и число тестов/итоговый report, не один exitcode. Реальные генерации не нужны.

## T02 · P1 · Воспроизводимый тестовый контур

Источники: [audit_cross_level_generation](D:/curriculum-kag/curriculum-kag/backend/scripts/audit_cross_level_generation.py), [invariant ledger](D:/curriculum-kag/curriculum-kag/backend/app/planner/invariant_ledger.py). Зависимость: T01.

1. Снять manifest ревизий кода, model-content hash, каталога, нормативного ruleset, конфигурации, Python/пакетов, OS/hardware и seed. Секреты не сохранять.
2. Разделить component/contract/runtime/API/content/expert suite. Прямой вызов scheduler не подписывать как API acceptance.
3. Подготовить минимальные fixtures для F01/F02/F08 и кейса C=236/240, ложных prerequisites и пустого bridge; отдельную фиксированную тестовую БД для integration.
4. Изолировать approvals/feedback от общего каталога и пользовательских данных. Зафиксировать состояние до/после.

Приёмка: перестановка порядка кейсов не меняет corpus revision и результат детерминированных фикстур; никаких пользовательских project-id в cleanup. Повторный run читает тот же immutable input, результаты не подмешиваются. Неподдерживаемое окружение даёт not_run с причиной.

## T03 · P1 · Durable queue и ownership попыток

Источники: [planner_state](D:/curriculum-kag/curriculum-kag/backend/app/api/planner_state.py), [planner_build](D:/curriculum-kag/curriculum-kag/backend/app/api/planner_build.py), [PlanBuildStatus](D:/curriculum-kag/curriculum-kag/backend/app/models/plan_build_status.py), [worker](D:/curriculum-kag/curriculum-kag/backend/scripts/run_planner_build_worker.py). F05/F06. После T02; исполнять подпункты отдельно.

**T03a. Модель job/attempt.** Durable job_id, immutable request hash, state, enqueue/start/deadline/finish times; новый owner token на attempt. SQL-ограничение единственного активного build нужного scope. Один источник lease, без разночтения columns/payload. Внешний job_id не равен PID.

**T03b. Атомарные переходы.** Enqueue уникален; queued claim доступен только worker, не второму API enqueue. Обновление WHERE job_id + attempt/owner + ожидаемое состояние. Ошибка durable storage не разрешает in-memory альтернативного владельца. Fencing распространяется на публикацию результатов, не только heartbeat.

**T03c. Исполнитель.** Постоянный отдельный worker, preload модели, контролируемая concurrency, повторное получение queued после перезапуска. Предпочтительно использовать имеющийся PostgreSQL; новый broker вводить только с обоснованием. Логи stdout/stderr сохранять ограниченно, с run-id; не DEVNULL. Shutdown прекращает приём нового и корректно завершает/отдаёт lease.

Приёмка: два параллельных API запроса к одной версии; запуск двух workers; исчезновение worker до/после claim; restart API; SQL failure при enqueue; старый worker после нового claim; задания разных пользователей. Максимум одна публикация правильной попытки, никаких вечных queued, measured global cap. Проверять настоящим PostgreSQL, а не только mock Session.

## T04 · P1 · Cancel/retry/idempotency/deadline и ошибки

Источники: [planner_build](D:/curriculum-kag/curriculum-kag/backend/app/api/planner_build.py), [planner_state](D:/curriculum-kag/curriculum-kag/backend/app/api/planner_state.py). F06/F10. Зависимость T03.

1. CancellationToken/Deadline на scoring, A/B/C, repair, verify и перед публикацией; queued отменяется без запуска. При неподконтрольном native-вызове использовать контролируемый собственный дочерний процесс либо запрет публикации и принудительный teardown по deadline. Не убивать произвольное PID-дерево.
2. Heartbeat ≠ deadline: живой heartbeat не продлевает абсолютный SLA бесконечно.
3. `(owner, idempotency_key)` + input hash → один job. Тот же ключ/вход возвращает тот же job и после завершения; другой вход/тот же ключ — 409. Retry создаёт attempt с новым fence и сохраняет историю.
4. Разделить infeasible/insufficient_evidence/cancelled/timed_out/infrastructure_failed. Ожидаемый отказ не 500; HTTP/status JSON несёт причины с correlation-id, без SQL/stack/secrets.

Приёмка: cancel в очереди, scoring, каждом варианте и на границе commit; concurrent heartbeat/cancel; повтор запроса при сетевом обрыве; потеря worker; просроченная попытка пишет поздно. Отмена подтверждается не только флагом UI, но отсутствием позднего изменения активного плана.

## T05 · P1 · Неизменяемая спецификация программы

Источники: [project model](D:/curriculum-kag/curriculum-kag/backend/app/models/project.py), [projects API](D:/curriculum-kag/curriculum-kag/backend/app/api/projects.py), [profiles](D:/curriculum-kag/curriculum-kag/backend/app/services/program_profiles.py). F07/F16. После T02, согласовать job hash с T03.

1. ProgramSpecSnapshot фиксирует цель, LO/weights, язык, уровень/track, scope, кредиты/семестры, две области и квоты, bridge limits, policy/model/catalog revisions.
2. Изменение условий создаёт новую revision; старый план объясняется старым снимком. Worker не перечитывает изменившийся Project в середине run.
3. Валидировать finite weights/числа, совместимость track именно с education_level, цель↔LO↔scope; неподдерживаемые профили сообщать явно.

Приёмка: edit constraints/LO при queued и running не меняет уже поставленный job; старый экспорт воспроизводим; request hash детерминирован при перестановке ключей; stale master_track не влияет на doctorate. Не переписывать старые планы под новые условия.

## T06 · P1 · Атомарная публикация без разрушения последнего результата

Источники: [scoring](D:/curriculum-kag/curriculum-kag/backend/app/kag/scoring.py:489), [scheduler](D:/curriculum-kag/curriculum-kag/backend/app/planner/scheduler.py), [build](D:/curriculum-kag/curriculum-kag/backend/app/api/planner_build.py). F07. T03/T05.

1. Новые MatchScore/evidence и bridge принадлежат build_run/variant. Не удалять старое evidence до успешной публикации.
2. Исключить shared BridgeModule mutation между A/B/C. Кредиты item, модуль и экспорт должны совпадать после завершения всех вариантов.
3. Проверить все запрошенные варианты на финальном immutable наборе; publish атомарно и с fence. Частичный A-build не уничтожает валидные B/C другой сохранённой revision.

Приёмка: fault injection после удаления/до scoring/после A/во время B/перед commit; активный прежний план, evidence и graph идентичны исходным. После успеха нет mix старого/new run. Отмена и restart не оставляют частично опубликованных variants.

## T07 · P1 · Bridge как образовательная единица, не заполнитель

Источники: [policy](D:/curriculum-kag/curriculum-kag/backend/app/planner/bridge_policy.py), [scheduler](D:/curriculum-kag/curriculum-kag/backend/app/planner/scheduler.py:901), [verifier](D:/curriculum-kag/curriculum-kag/backend/app/planner/verifier.py:411). F01/F03.

1. Исправить budget: actual ≤ request и policy cap, core учитывается одинаково; `allow_new_courses=false` запрещает все generated-типы. Нельзя расширять budget по названию профиля.
2. Предлагаемый bridge получает содержание/LO/оценочную работу/трудоёмкость/prerequisites/evidence и approval_state. Наличие target_lo не является экспертным evidence.
3. Прекратить заполнение всех LO балансировочным модулем. Дефицит кредитов закрывать только предметно допустимым выбором, иначе infeasible.

Приёмка: лимиты 0/1/3/5/7, single/interdisciplinary/joint; все CORE/AUTO/QUALITY/LO_GAP/LOAD_SHIFT-типы; граничные кредиты; module с пустыми источниками и всеми LO не получает verified-real coverage. Тестовый дефицит не «лечить» поднятием cap.

## T08 · P1 · Типизированные домены и правила допуска

Источники: [domain_evidence](D:/curriculum-kag/curriculum-kag/backend/app/planner/domain_evidence.py), [variant_admission](D:/curriculum-kag/curriculum-kag/backend/app/planner/variant_admission.py), [candidate retrieval](D:/curriculum-kag/curriculum-kag/backend/app/planner/candidate_retrieval.py). F02.

1. Единый Domain/Scope resolver по данным ЕПВО; алиасы только на входе, без коротких substring совпадений.
2. Отдельно level eligibility, catalog membership, LO relevance и secondary-domain credit evidence. Одно не подменяет другое.
3. Сделать правила pure и табличными; unknown возвращает unknown/needs_review, не passed.

Приёмка: Literature/Hospitality не ICT; RU/KK/EN одного кода эквивалентны; дисциплина неверного уровня не допускается только по domain label; вторичные кредиты учитываются ровно один раз; валидные междисциплинарные дисциплины не теряются. Контрпримеры вне medicine/agro обязательны.

## T09 · P1 · Пререквизиты с происхождением и смыслом

Источники: [scheduler_prerequisites](D:/curriculum-kag/curriculum-kag/backend/app/planner/scheduler_prerequisites.py), [inference](D:/curriculum-kag/curriculum-kag/backend/app/planner/prerequisite_inference.py), [graph API](D:/curriculum-kag/curriculum-kag/backend/app/api/planner_graph.py). F04. После T08.

1. Трассировать подозрительные существующие рёбра из кейса 4 до источника и этапа импорта. Не править только отрисовку.
2. Развести occupational safety/environment и cybersecurity. Inferred relation помечается как hypothesis с причиной; не считать её подтверждённым обязательным prerequisite без основания.
3. Сохранять и проверять missing mandatory prerequisite, cycle и направление. Не удалять неудобные рёбра, чтобы получить DAG.

Приёмка: ecological safety→intro cybersecurity не проходит без явного предметного источника; algorithms→advanced ML имеет основание; required predecessor должен быть раньше или оформлен как admission requirement. Граф, schedule, API и экспорт показывают один набор с одинаковыми статусами evidence. Число рёбер не KPI качества.

## T10 · P1 · Независимый verifier и смысл вариантов

Источники: [verifier](D:/curriculum-kag/curriculum-kag/backend/app/planner/verifier.py), [build signature](D:/curriculum-kag/curriculum-kag/backend/app/api/planner_build.py:532), [ledger](D:/curriculum-kag/curriculum-kag/backend/app/planner/invariant_ledger.py). F03/F08/F10/F16. T05/T07/T08/T09.

1. Read-only verifier получает финальный PlanDTO + immutable evidence, не вызывает repair. Единый ready_for_review = hard_valid AND evidence_valid; expert_approved отдельно.
2. Разделить real evidence, generated proposal, regulatory evidence и not_evaluated. Не называть similarity вероятностью освоения LO.
3. Общий canonical fingerprint, устойчивый к порядку items. Дополнительная мера содержательного различия A/B/C, invariant к новым surrogate IDs.
4. Проверять критические компетенции из ProgramSpec, не только ICT keywords; semantic duplicates по темам/assessment, а не просто title equality.

Приёмка: 236/240 не выглядит полным успехом; перестановка массива не новый вариант; две одинаковые bridge-копии не альтернатива; пустой verifier для non-ICT — not_evaluated; тестовые повреждения credits/LO/prereqs/level/domain/bridge/duplicates обнаружены независимо от generator checks.

## T11 · P1 для оптимизации · Измерить полный путь

Источники: [build timings](D:/curriculum-kag/curriculum-kag/backend/app/api/planner_build.py), [telemetry tests](D:/curriculum-kag/curriculum-kag/backend/tests/test_planner_telemetry.py), [performance monitor](D:/curriculum-kag/curriculum-kag/scripts/monitor-planner-performance.ps1). F05/F11. T01/T02, затем повтор после T03.

1. Расширить существующую телеметрию: request/run/attempt-id, queue, process/model load, signature SQL, approval, shortlist, embeddings, ranking, A/B/C и каждый repair, verify, save, first UI result.
2. Фактические CPU/GPU/device, model mode/revision, unique texts/cache hits, SQL count/duration, peak RAM/VRAM, retries и failure latency. Не логировать секреты и полные пользовательские LO в метриках.
3. Baseline 3–5 фиксированных cases: cold/warm, concurrency 1, затем контролируемая 2. Приложить trace и таблицу, не только итоговую цифру.

Приёмка: сумма измеренных фаз объясняет wall time с учётом вложенных/параллельных spans; измерены failed/cancelled/queued, нет double counting. Никаких заявления «главный bottleneck X» без его measured share. SLO из аудита — цель для проверки, не уже полученный результат.

## T12 · P1/P2 · Честный model runtime и повторное использование embeddings

Источники: [embedding service](D:/curriculum-kag/curriculum-kag/backend/app/kag/embedding_service.py), [scoring](D:/curriculum-kag/curriculum-kag/backend/app/kag/scoring.py), [stage cache](D:/curriculum-kag/curriculum-kag/backend/app/services/planner_stage_cache.py). F11. T11, совместить с T03c.

1. Инициализация модели single-flight; health/startup сообщает actual model/device. Разные production/demo/research profiles явны.
2. Не смешивать SBERT и feature-hash vectors. Degraded режим разрешён только явной политикой и отражён в результате; ошибка encode не остаётся под прежней model-version.
3. Persistent key: model content + preprocessing + text hash + dimension. Batch уникальных cache misses; reusable corpus embeddings. Не вычислять неиспользуемый ranker при нулевом весе.

Приёмка: encode failure/model reload/другие веса под прежним именем/смена языка/конкурентный init; namespace и статус корректны, invalidation работает. На одинаковых входах warm embed work уменьшается, содержательная точность не деградирует. Числа до/после из T11.

## T13 · P2 · Убрать повторную подготовку данных и дорогие cache checks

Источники: [stage cache](D:/curriculum-kag/curriculum-kag/backend/app/services/planner_stage_cache.py), [scoring](D:/curriculum-kag/curriculum-kag/backend/app/kag/scoring.py), [candidate retrieval](D:/curriculum-kag/curriculum-kag/backend/app/planner/candidate_retrieval.py). T11/T12.

1. CatalogRevision транзакционно обновляется при вставке/правке/удалении/локализации/approval/feedback; request не пересчитывает ordered hash миллионов строк несколько раз.
2. Снять EXPLAIN для фактических hot SQL, заменить JSON-as-text LIKE/ORM N+1 там, где это измеренно выгодно. Не добавлять индексы вслепую.
3. Общий immutable CandidateContext и EvidenceMatrix на build для A/B/C; prefetch локализаций/prereqs. Оценить recall shortlist на большой базе, а не просто уменьшить candidate limit.

Приёмка: изменение средней строки при неизменном count/max инвалидирует cache; прежние результаты после смены config не используются. Измерено снижение scan/query/encode counts без потери релевантных дисциплин в golden cases. Full hash остаётся offline integrity-проверкой.

## T14 · P2 · Senior-рефакторинг вычислительного ядра

Источники: [scheduler](D:/curriculum-kag/curriculum-kag/backend/app/planner/scheduler.py), [variant strategy](D:/curriculum-kag/curriculum-kag/backend/app/planner/variant_strategy.py), [coverage API](D:/curriculum-kag/curriculum-kag/backend/app/api/planner_coverage.py), [EPVO API](D:/curriculum-kag/curriculum-kag/backend/app/api/epvo.py). T02/T06/T10/T13.

Подпункты — отдельные изменения: a) API→BuildService без изменения поведения; b) pure VariantStrategy над CandidateContext; c) ScheduleSolver/RepairCoordinator с явными invariants и progress/deadline; d) read-model assembler для coverage/graph; e) вынести управление исследовательскими процессами из epvo HTTP router.

RepairCoordinator имеет ограничение итераций, cycle detection, критерий допустимого изменения и откат ухудшения; no-op не вызывает следующий круг. Функции не должны скрыто commit и обращаться к глобальной mutable session. Не нужен искусственный норматив «каждый файл <200 строк».

Явно описать StrategyMode для deterministic scoped и experimental NSGA-II. Убрать зависимость возможностей top-up от момента присваивания no-op callback; каждый strategy получает один типизированный набор зависимостей. Условия предметной области не обязаны исчезнуть — они должны быть проверяемой политикой, а не неочевидным переключателем алгоритма.

Приёмка: characterization/golden compare, реальные небольшие PostgreSQL integration, нет скрытых SQL/commit в pure слоях; invariants проверены на каждой границе. Раздельно объяснить сознательные исправления поведения и нейтральные переносы. Полный rewrite optimizer/новый solver-library — отдельное решение после профиля, не часть этой задачи по умолчанию.

## T15 · P1/P2 · Frontend соответствует job и проверкам

Источники: [PlanBuilder](D:/curriculum-kag/curriculum-kag/frontend/src/pages/PlanBuilder.jsx), [ProjectDetails](D:/curriculum-kag/curriculum-kag/frontend/src/pages/ProjectDetails.jsx), [translations](D:/curriculum-kag/curriculum-kag/frontend/src/translations.js). T03/T04/T10.

1. useBuildJob/reducer: queued/running/cancelling/complete/infeasible/failed/timed_out. 202 не означает done. BuildMissing использует тот же протокол; idempotency key сохраняется на retry запроса.
2. Выделить transport, selection/editing state и presentation. Пустой успешный ответ очищает прошлый список, ошибка не замаскирована старым состоянием; запросы отменяются на unmount/change-version.
3. Общий DTO для plan/grid/graph/coverage/export. RU/KK/EN: названия, причины отказа, fallback и plural; no raw translation keys. Demo использовать тот же view-model, но явно маркировать synthetic и считать totals из данных.

Приёмка: browser E2E 202/refresh/cancel/retry/expired/session logout/missing variants; кнопка не разрешает duplicate во время job; граф совпадает с API, понятные независимые badges. Demo не отправляет фиктивные IDs в real API, не показывает непосчитанные «ГОСО passed». Публикация Vercel не входит в задачу без отдельного запроса.

## T16 · P1 для cutover · Доказать перенос и restore

Источники: [acceptance orchestrator](D:/curriculum-kag/curriculum-kag/backend/scripts/accept_sqlite_postgres_migration.py), [compare](D:/curriculum-kag/curriculum-kag/backend/scripts/compare_sqlite_postgres_counts.py), [restore check](D:/curriculum-kag/curriculum-kag/backend/scripts/check_postgres_restore.py), [последний отрицательный отчёт](D:/curriculum-kag/curriculum-kag/.runtime/sqlite-postgres-acceptance-20260906-final2.json). F13. Отдельная тестовая БД.

1. Для четырёх mismatch таблиц вывести PK/колонку/категорию различия с безопасными редактированными примерами. Не нормализовать важные различия до исчезновения mismatch.
2. Canonical JSON/date/float/NULL правила документированы и unit-tested; исправление переносит семантику, не переписывает эталон под целевой хэш.
3. Каждое FK-исключение сопоставлено review manifest/policy и источнику; количество нарушений не называть числом потерянных строк. Проверить полноту перечня всех релевантных таблиц, включая plans/items/bridges/jobs, а не только 15 перечисленных.
4. Восстановить backup в уникальную disposable PostgreSQL DB, сравнить schema/alembic, rows/content/FK, sequences и пробную вставку в транзакции; старую БД не трогать. Сохранить dump checksum, журнал и manifest.

Приёмка: aggregate passed=true только при всех обязательных gates; необъяснённые diff/orphans/пропущенные таблицы — fail/not_verified. Отдельный отчёт restore, не вывод «dump создан, значит восстановится».

## T17 · P1 · Выполнить 20 настоящих спецификаций

Вход: соседние `03_ACCEPTANCE_PROTOCOL_RU.md` и `04_PROGRAMS_20_RU.md`. Зависимости T01–T10, T11; T12/T13 если baseline не укладывается в согласованный SLO. Изолированный каталог/БД и пользовательские API. Не генератор одинаковых LO с новым порядковым номером.

Исполнитель по каждой спецификации разрешает реальные коды ЕПВО, передаёт явную цель и LO, получает A/B/C через тот же job endpoint, сохраняет input/request/job/evidence/планы/trace/снимки UI и независимые checks. Если область не поддержана — unsupported/insufficient_catalog, без тихой замены её на ICT. Не запускать все 20 параллельно. Контрольные состояния читать не чаще согласованного интервала; полные тяжёлые повторные проверки по событию завершения.

Приёмка: 20 уникальных смысловых inputs, ожидается 60 variant results; отсутствие/отказ — зафиксированная неполнота, не готовая программа. Все дефекты заведены, старые и новые попытки сохранены. Нет «20/20» по одним HTTP 200 или наличию JSON. Техническую и содержательную оценки не смешивать.

## T18 · P1 для внедрения · Независимая экспертиза и решение

Источники: [рубрика](D:/curriculum-kag/curriculum-kag/docs/QA_EXPERT_RUBRIC_RU.md), [packets](D:/curriculum-kag/curriculum-kag/backend/scripts/prepare_expert_rubric_packets.py), [scoring](D:/curriculum-kag/curriculum-kag/backend/scripts/score_expert_rubric.py). T17.

Подготовить обезличенные полные пакеты 20 программ/вариантов и независимые формы минимум двух реально привлечённых специалистов: предметный эксперт и специалист по проектированию ОП. Вне их компетенции нужен дополнительный профильный рецензент. Автор/вторая LLM не подменяют независимых экспертов.

Проверить syllabus/evidence/assessment, научную глубину postgraduate, кадровые и ресурсные условия, нормы и локальный порядок утверждения. Порог и veto из протокола фиксируются до просмотра итоговых баллов. Сохранить исходные независимые оценки, затем adjudication спорных пунктов.

Приёмка: решения «непригодно / существенная доработка / ограниченный пилот / проект к рассмотрению вузом», подтверждённые рецензентами. При отсутствии людей итог `expert_review_pending`, не fabricated expert_pass. Формальное вузовское утверждение выполняет вуз, не генератор и не агент.

## Готовый шаблон запроса более дешёвой модели

> Выполни только задачу Txx [или подпункт] из `D:\curriculum-kag\curriculum-kag\docs\senior-audit-2026-09-08\02_IMPLEMENTATION_TASKS_RU.md`. Сначала прочитай соответствующие Fxx и evidence.json, проверь актуальное дерево и зависимости. Сохрани чужие изменения. Напиши regression, внеси минимальное исправление в указанной границе, выполни предусмотренные проверки. Не ослабляй ограничения/пороги и не добавляй исключения под конкретную программу. Не запускай массовую генерацию, миграцию рабочей БД, Docker reset, публикацию или другой Txx. В конце: причина, изменённые файлы, выполненные тесты с числами, какие критерии доказаны/не проверены, риски и конкретный следующий подпункт. Если runtime недоступен — честно отметь это, не засчитывай mock как доказательство.

Оценка трудоёмкости без обещания сроков: T01/T07/T08 — небольшие/средние bounded изменения; T03/T05/T06/T10/T14 — крупные, требующие нескольких проверяемых шагов; T11–T13 зависят от профиля; T17 требует вычислительного времени; T18 — участия людей. Экономить стоимость модели лучше размером и точностью задачи, а не отказом от проверки.
