# Охват ограничения тяжёлой генерации

## Актуальное состояние после подключения

### Текущие процессы и историческая несогласованность job history

Read-only текущий снимок: API actual25580 слушает8000,frontend12832 слушает3001; worker wrapper10960/actual10128 обнаружены, время создания12Oct19:47:39 из host. В plan_build_status нет queued/running. В planner_build_jobs есть1running: id1/version137,started2026-09-08, текущий status того же public job timed_out. Также9attempts running: parent states timed_out1,rejected3,cancelled3,complete1,running1. Поэтому счётчики исторических running не доказывают активную генерацию; обнаружена несогласованность старой истории. Ни jobs/attempts ни процессы не изменялись. Нужен отдельный bounded reconciliation контракт с проверкой текущей identity/lease и rollback; массово переписывать историю нельзя. Наличие запущенного API не подтверждает загрузку всех новых source changes, версия ещё не аттестована.

### После восстановления Docker/PostgreSQL

Контейнер shadow healthy. Opt-in test_generation_capacity_postgres.py после перезапуска среды session63937 exit0,2/2: четыре одновременных соединения дают1admitted/3busy; после release новое получение успешно, nested выход сохраняет внешний slot; физическое отключение owner освобождает slot. Isolated DB curriculum_kag_restore_pilot_20261010, моделей/записи каталога нет. Обнаружены worker процессы10960/10128 со временем создания12Oct19:47:39 в host выводе; их версия и активные задания этим тестом не проверены, процессы не перезапускались. Это восстановленная доступность PG и admission/release контроль, не проверка нескольких пользователей с реальными моделями, не измерение RSS/throughput/cost. Переход к live rollout всё ещё требует отдельной проверки job state и версии процессов.

### Cohort runner: временная занятость

12 октября classifier родительского audit_quality_cohort.py научен распознавать зарезервированный дочерним CLI exit75 как retryable infrastructure failure даже при пустом stderr (busy payload находится в stdout/JSON). RED: test_capacity_busy_exit_is_retryable_without_stderr получил False вместо True; после исправления полный backend suite session79421 exit0, два opt-in skipped, сторонние deprecation warnings. Слово capacity_busy при exit1 не превращает содержательный отказ в инфраструктурный. Существующий бюджет двух попыток не увеличен; постоянная занятость по-прежнему завершает прогон без passed. Это исправление классификации, не доказательство ожидания очереди до освобождения или нагрузочной готовности. Live rollout и новые генерации не выполнялись.

Ниже сохранён первоначальный аудит и поэтапные результаты. Сейчас в исходниках защищены KAG scoring API, recompute API, synchronous build API, daemon/one-shot worker и frozen cross-level CLI. Async enqueue не занимает тяжёлый slot. Live сервисы ещё не обновлены; эта запись не описывает их текущую версию.

Полный suite после CLI session55446 завершился exit0,2opt-in skipped, только сторонние deprecation warnings.

### Реальный межпроцессный busy-контроль

`.runtime/capacity-entrypoints-process-20261012.json`: isolated DB curriculum_kag_restore_pilot_20261010, parent process удерживает PostgreSQL slot, отдельный child process вызывает реальные entrypoints. KAG/recompute/syncbuild получили503/Retry-After2; one-shot worker вернул2; CLI exit75/statuscapacity_busy. После release слот вновь получен. Probe98147 завершён exit0; каталог/планы не создавались, модели не запускались, live DB не использовалась. Это реальная интеграция busy-пути, НЕ многопользовательский model/queue benchmark, НЕ измерение throughput/RSS peak/стоимости.

Аудит текущего кода, без запуска параллельных моделей и без изменения продукта.

| Вход | Подтверждённый путь | Общий PostgreSQL slot |
|---|---|---|
| KAG scoring API | api/kag.py `_capacity_checked_matches` | Да, только scoring |
| Worker build | scripts/run_planner_build_worker.py `_build_one` → api/planner_build.py `build_plan` | Нет охвата всей операции |
| Build scoring | api/planner_build.py вызывает compute_all_matches напрямую | Нет |
| Recompute API | api/planner_build.py `recompute_matches` | Нет |
| Frozen CLI | scripts/audit_cross_level_generation.py scoring и последующий build | Нет |
| Joint solver | planner/joint_planner.py build_verified_joint_schedule | Нет |

Здесь «нет» означает отсутствие подключения существующего generation_slot в исследованных входах, а не утверждение об отсутствии durable claims. Claim задания защищает его идентичность; не ограничивает число разных тяжёлых заданий/пользователей.

## Обнаруженный риск

Отдельный durable worker по умолчанию работает последовательно, но второй процесс worker, CLI или recompute может одновременно загружать модель. Нынешний slot в KAG API не защищает этот общий ресурс. Нагрузочные прогоны до исправления охвата нельзя считать безопасной проверкой масштабирования.

## Проверяемые требования реализации

1. Worker получает slot ДО перевода queued в running и удерживает его до завершения/отмены/ошибки публикации; busy оставляет job queued, без нового failed attempt.
2. Синхронный build и frozen CLI охватывают одной областью model/scoring/solver, не отпускают слот между стадиями.
3. Прямой scoring/recompute защищается до модели; возвращает retryable busy, не запускает второй расчёт.
4. Вложенный вызов с тем же engine/thread не снимает внешний slot. Ни один sync slot не удерживается через async await.
5. Проверки потери connection/process, cancellation, release on exception, сохранности oldplan и fairness очереди обязательны; helper-only unit test не доказывает весь workflow.

После RED/GREEN интеграционных регрессий и полного suite — isolated PostgreSQL pilot нескольких пользователей с непрерывными PID/RSS/queue measurements. Стоимость рассчитывать из измеренного времени ресурса и явного тарифа, а не из цены неизвестного сервера.

## Первый TDD шаг: daemon

`test_worker_capacity.py` запускает настоящий цикл worker с заменой внешних DB/model операций: при занятом slot ожидались queued/no model, RED получил running/model_started. Первоначальная ошибка TEMP доступа не считалась RED; повтор в новом writable basetemp воспроизвёл именно нарушение контракта.

В daemon добавлен `_claim_and_build`: slot получается до durable claim и сохраняется во время всего `_build_one`; CapacityBusy не меняет job/attempt, цикл продолжает ожидание.25 целевых tests(worker/capacity/async contract) passed. Полный backend suite запущен, его итог ещё не подтверждён. Live worker не перезапускался. One-shot worker, direct API build/recompute и CLI пока не подключены; этот шаг не закрывает глобальную защиту или масштабирование.

## Подтверждение suite и one-shot

Полный suite первого шага session95235 завершился exit0,2opt-in skipped; deprecation warnings сторонних библиотек. Затем test_one_shot_busy сначала RED: код1 и owner query вместо retryable2/noquery. `_build_one` теперь получает тот же slot до lookup/build и удерживает до возврата, CapacityBusy возвращает2; с внешним daemon slot вызов реентерабелен на том же engine/thread.26 целевых tests прошли. Повторный полный suite для изменённого one-shot запущен; итог ещё требуется. Direct API build/recompute и frozen CLI всё ещё открыты. Не считать mocks проверкой конкуренции реальных процессов, не перезапускать live до отдельного bounded PostgreSQL контроля.

## API пересчёта

## Прямой build API

## Frozen CLI

Test_busy_cli сначала RED: попытка создать temporary project (тестовый exit99) вместо retryable exit75. audit_cross_level_generation теперь приобретает slot до создания проекта/репозитория/модели и удерживает через scoring,solver и cleanup. CapacityBusy пишет statuscapacity_busy, passedfalse,retryabletrue,RetryAfter2,exit75; не обозначается успешной программой. ExitStack закрывается в finally даже при ошибке DB cleanup. Полный backend suite запущен session55446; итог фиксировать отдельно. Автоматический retry родительского cohort runner при exit75 ещё не проверен; реальные concurrent процессы и memory/throughput не измерены. Live rollout не выполнен.

Фактический итог session24217: full backend/tests exit0,2opt-in skipped, сторонние deprecation warnings; процесс завершён.

Test_busy_synchronous_build сначала RED:409 и попытка claim вместо503 до claim. Публичный build wrapper теперь оставляет async enqueue свободным, а sync/worker исполнение охватывает generation_slot до `_build_plan_owned` и до возврата публикации. Busy503/Retry-After2 до создания running attempt. При worker вызове ownership реентерабелен по тому же engine/thread. Полный suite session24217 запущен; итог фиксируется после завершения. Frozen CLI ещё не подключён, live сервис не обновлён, реальный concurrent pilot не выполнен.

Фактический итог session19982: полный backend/tests exit0,2opt-in skipped, только сторонние deprecation warnings. Процесс завершён, не опрашивать как running.

Полный suite one-shot session34912 завершился exit0. RED test_busy_recompute сначала получил409 после попытки claim вместо503 до claim. В recompute endpoint slot теперь приобретается до owned операции; busy даёт503/Retry-After2, не создаёт running attempt и не превращается в generic500. Slot сохраняется до commit/status возврата. Прежняя реализация выделена в `_recompute_matches_owned`; route/dependencies сохранены. Полный suite после этого изменения запущен session19982; итог проверить отдельно. Direct build и frozen CLI ещё не защищены целиком; live rollout не выполнен.
