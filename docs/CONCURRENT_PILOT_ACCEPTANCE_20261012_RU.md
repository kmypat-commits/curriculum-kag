# Приёмка очереди нескольких пользователей

## Что прежний сценарий не доказывает

Проверены .runtime/prepare-isolated-queue-20261010.py и run-isolated-queue-20261010.py. Producer создаёт два проекта одного User1; consumer последовательно вызывает _build_one в одном процессе. Поэтому прежнее2/2 — последовательное исполнение двух команд, не одновременные запросы разных пользователей и не конкуренция daemon workers. Старые отчёты не переименовывать в multi-user acceptance.

## Следующий реальный сценарий

Изолированная восстановленная БД, новый run_id и новые evidence paths. Не использовать старые cases/job IDs. Два разных тестовых пользователя и отдельные проекты с неизменённым одним frozen input; одинаковый input здесь контролирует нагрузку, не заменяет cohort20→40. Точные hashes и версии source фиксируются до producer.

Два одновременных enqueue запроса; ownership check обязателен. Два отдельных daemon worker процесса с фильтром только pilot job IDs; не запускать общий consumer старой очереди из восстановленной БД. Общий PostgreSQL capacity slot допускает лишь одно реальное тяжёлое исполнение, другое задание остаётся queued без failed attempt. Никакой симуляции scoring/solver и никакого искусственного sleep вместо модели.

Для каждого job фиксируются queued/claimed/published timestamps, wait/service latency, plan hashes, исходный published plan до/после отказа, event sequence и независимая structural check. Изоляция событий/планов проверяется между пользователями. Второй запрос не обязан мгновенно вычисляться: одновременный submit и последовательный compute при одном слоте — ожидаемая политика ограниченной памяти.

Снимать process tree RSS/CPU и host available RAM во время обоих jobs, с периодом1сек; хранить raw samples, учитывать реальные children и исключать double counting. Выводить peak working set отдельно от committed memory; отсутствие committed counter отмечать, не называть RSS полным лимитом памяти. Throughput — успешные завершения/время всего окна, не3600/среднее отдельного кейса. Из двух jobs нельзя экстраполировать устойчивую производственную пропускную способность.

Потом bounded crash/recovery того же job с сохранением предыдущего плана; повторное исполнение не создаёт новый logical job. Capacity owner release и lease/attempt closure проверять раздельно. Ошибка pilot останавливает новые jobs и сохраняет evidence. Не прекращать чужие live процессы.

## Ограничения стоимости и готовности

Локальный inference не равен бесплатной генерации. Измерять runtime/CPU/RAM; цену за генерацию рассчитывать только с явно заданной стоимостью хоста/электроэнергии и способом распределения idle времени. Без тарифа публиковать ресурсы, не выдуманные тенге/доллары. До network rollout заменить weak admin, проверить доступ и восстановление; этот pilot не снимает этих условий.

## Статус

Реальный новый multi-user pilot ещё не запущен. Существующий isolated PG slot тест и межпроцессный busy probe являются необходимыми, но недостаточными доказательствами. Следующий шаг реализации — ограниченный consumer только именованных pilot jobs и recorder процесса; перед запуском перепроверить live jobs/RAM и отсутствие других model runs.

## Подготовка ограниченного consumer

12 октября добавлен необязательный --only-job-id (можно указать несколько раз) для daemon. Allowlist применяется в SQL до LIMIT и claim; без параметра прежняя очередь не меняется. Тест test_scoped_daemon_never_claims_jobs_outside_pilot на реальной SQLite БД проверяет, что старое чужое queued-задание не передаётся на исполнение и остаётся queued. RED после исправления тестового fixture воспроизвёл отсутствие параметра, GREEN: три worker-capacity теста прошли. Это не доказательство PostgreSQL-конкуренции или работы модели.

Ruling: scoped consumer реализован параметром production daemon, а не отдельным упрощённым исполнителем — пилот должен проверять тот же claim/capacity путь. Стоимость ошибки: недостаточная изоляция пилота; поэтому allowlist проверяется до запуска и используется только с isolated DATABASE_URL. Для двух пилотных процессов HEARTBEAT_FILE должен быть отдельным от live heartbeat; текущий default разделяется, запуск без изоляции heartbeat пока не разрешён. Recorder, два тестовых владельца и actual load evidence ещё не готовы.

Полный backend pytest на этом состоянии завершён exit0 (exec session92626), два opt-in теста пропущены. Live workers не перезапускались, новые задания не создавались. Продолжение: изолировать heartbeat пилота, подготовить producer двух пользователей и sampler памяти, затем реальный bounded запуск.

## Heartbeat и проверка ресурсов перед запуском

Добавлен --heartbeat-file; default остаётся прежним. Реальный тест daemon подтверждает создание отдельного pilot-heartbeat и отсутствие записи в default heartbeat. Три worker-capacity теста прошли после RED на отсутствующем параметре. Это безопасное условие пилота, не результат нагрузочной генерации.

Проверка PostgreSQL перед запуском: live plan_build_status не содержит queued/running; isolated curriculum_kag_restore_pilot_20261010 существует. Win32_OperatingSystem: FreePhysicalMemory=3249084 KiB (~3.10 GiB), TotalVisibleMemorySize=14366200 KiB (~13.70 GiB). psutil не установлен в используемых Python; измерение произведено штатными CIM/Get-Process, не выдано за временной ряд.

Действующий worker actualPID10128 (wrapper10960), StartTime12Oct19:47:39: WorkingSet=115.4 MiB, PrivateMemorySize=4431.1 MiB. Это одиночный снимок, не peak под нагрузкой. Working set нельзя называть всей памятью процесса; private bytes нельзя складывать с ним как два независимых потребления. API wrapper25528 и frontend actual12832 также существуют; команды/parent PID проверены.

Новая существенная граница capacity: advisory slot ограничивает одновременно выполняемый тяжёлый участок, но не гарантирует освобождение загруженной модели после completion. Два постоянных daemon могут последовательно загрузить модели и затем держать обе в памяти. Реальный пилот обязан фиксировать память после первого завершения и до/после второго, а не только число running jobs. Новые тяжёлые процессы при этом снимке не запущены; чужие процессы не остановлены. Нужен sampler с контрольным запасом RAM и ограниченным завершением только принадлежащих пилоту процессов, затем повторная preflight-проверка. Это не основание объявлять систему масштабируемой или снижать качественные gates.

Полный backend suite после heartbeat изменения завершён exit0 (exec99082), два opt-in теста пропущены. Пилот/throughput/стоимость остаются непроверенными.

## Сборщик метрик

backend/scripts/pilot_resource_metrics.py: read-only bounded observer, PID+create_time защищает от повторного использования PID, descendants дедуплицируются по process identity, working set/private bytes раздельно. CPU хранится накопленным временем процесса, не выдаётся за долю CPU или цену задания. При нехватке available RAM сохраняет memory_guard_triggered и exit2; сам не останавливает процессы. Завершение только принадлежащих пилоту процессов остаётся задачей orchestration controller.

psutil7.2.2 установлен --no-deps --target .runtime/pilot-metrics-lib, не в application venv и не как новая production dependency. JSON не содержит command lines или секретов. Existing evidence не перезаписывается при запуске.

Короткое наблюдение live worker wrapper10960/actual10128: .runtime/idle-worker-resource-samples-20261012.json, exit0, шесть samples/5.0 секунд, peak working set44281856bytes, peak private4648849408bytes, минимум свободной памяти3233218560bytes. Это IDLE, generation_load=false, generation_cost=null; не устойчивый memory limit и не throughput benchmark. Unit-проверка summary прошла, добавлены subprocess-проверки реального процесса и guard (без mock модели). Следующий шаг — producer двух пользователей и контроллер запуск/наблюдение/завершение scoped worker с guard.

Полный backend suite с collector tests завершён exit0 (exec7380), два opt-in PostgreSQL теста пропущены. Новые задания/модели не запускались.

## Первый реальный двухпользовательский пилот: остановка по RAM

После повторной preflight свободно ~4.48 GiB, live plan_build_status не содержал queued/running. Запущен .runtime/run-multiuser-pilot-20261012.py, ledger .runtime/multiuser-pilot-085cbaf044ce/report.json, actual controller23988, worker wrappers7880/24768. Не перезапускать этот report: терминальный failed, все пилотные процессы завершены.

Изолированная восстановленная БД; два новых разных methodist-владельца3/4, версии1614/1615; один неизменённый frozen program10251, file/canonical SHA256 в ledger. Два threads с barrier вызвали обычный build command одновременно (submit_window0 на разрешении monotonic timer). Проверен отказ404 чужому владельцу. Это direct-command integration, не authenticated HTTP test. Код app и начальный content catalogue fingerprint сохранены. Два настоящих daemon используют allowlist только двух jobs и собственные heartbeat.

На ~25.91 секунде после старта контроллера available RAM1601323008bytes <1.5 GiB: guard завершил пилот exit1. Последний snapshot: первое задание running, второе queued; планов0. Семнадцать samples за16.421 секунды окна наблюдения: peak working set301744128bytes, peak private1727385600bytes. Это неполное окно: нет completed jobs, throughput/service/cost не доказаны. Логи worker в той же директории сохранены. Не выдавать RAM guard за ошибку качества модели или доказанный её memory peak: рост памяти tracked trees не объясняет полностью падение host available RAM.

После остановки verified pilot processes отсутствуют. Отдельный guarded script cancel-stopped-pilot-085cbaf044ce.py проверил isolated DB и точные public job IDs, завершил только версии1614/1615 как cancelled. Live DB и чужие процессы не изменялись. Старые raw samples/error ledger не переписаны.

После остановки крупные потребители хоста: vmmemWSL~1922.5MiB WS/4047.7MiB private, browser11156~1161.7MiB WS, Memory Compression~1029.2MiB WS. Это снимок после остановки, не атрибуция всей динамики. Следующий шаг: включить host-wide memory/process observations и привязать их к окну пилота; повторять лишь с новым report и достаточным ресурсным запасом, без закрытия браузеров/WSL пользователя самовольно. Качественные/структурные gate не менялись, старые20/40 не запускались.

## Уточнение измерений и попытка повторного preflight

Collector теперь сохраняет host_memory (physical total/available, swap total/used), top10 процессов по working set и число недоступных записей; не сохраняет command lines/секреты. Subprocess regression сначала воспроизвела KeyError host_memory, затем3collector testsGREEN и полный backend exit0 (exec35766), два opt-in теста пропущены.

Контроллер включён в отдельный measured identity set, но исключён из списка остановки. Ранее peak относился только к worker trees и не учитывал контроллер — прежние числа нельзя называть полной стоимостью пилота. Failed cleanup автоматически закрывает только свои точные running/queued commands после завершения subprocesses; чужие статусы не изменяет.

Вторая попытка .runtime/multiuser-pilot-13578cb7dbe9/report.json terminalfailed exit1 ещё на предварительном требовании4GiB available. До старта shell видел4498520KiB свободной памяти, но после импорта контроллера условие не выполнилось. Cases/workers/samples пусты: новых пользователей/проектов/заданий не создавалось, это не второй нагрузочный прогон. Предыдущий085cbaf044ce остаётся failed, cancelled commands preserved. Не снижать порог и не перезапускать циклически на меняющейся памяти. Следующий запуск требует стабильного resource headroom; другие независимые задачи цели остаются доступными.

## Отдельное измерение импорта API без генерации

12 октября свежий live PostgreSQL не содержит queued/running. CIM сообщил4428104KiB свободной физической памяти. Чтобы не повторять пограничный тяжёлый пилот, отдельный короткоживущий процесс импортировал только `app.api.planner_build.build_plan`, без его вызова и без изменений БД. Процесс завершён exit0 за0.969сек импорта.

- Working set до/после:17518592 /110444544bytes (рост92925952bytes).
- Windows private до/после:9617408 /825921536bytes; это отдельный показатель, не RSS и не сумма с ним.
- Host available до/после:4531773440 /4427038720bytes. Разницу нельзя полностью приписывать процессу без непрерывного host trace.
- `torch` и `sentence_transformers` отсутствовали в `sys.modules` после импорта.

Это опровергает предположение, что именно импорт build API уже загружает torch/SBERT, но не измеряет полный producer (другие импорты, хэширование каталога, ORM) или реальные workers. Не объявлять825MB физическим расходом и не считать этот замер стоимостью генерации. Новый multiuser pilot не запущен, пороги безопасности не снижены. Следующий диагностический шаг — раздельное измерение остальных импортов/каталожного fingerprint и резидентных workers; нужны реальные завершения двух jobs для throughput/service metrics.

## Повтор с host/process измерениями: 5fe8124ee7cf

Короткий раздельный import probe: API0.969сек, audit_cross_level_generation0.015сек и315392bytes дополнительного working set, independent_curriculum_checks4096bytes. Torch/SentenceTransformers не загружены. Вспомогательные импорты не подтвердили гипотезу о преждевременной загрузке модели; менять их без причины не следует.

После проверки отсутствия live queued/running выполнен один новый реальный isolated pilot, отчёт `.runtime/multiuser-pilot-5fe8124ee7cf/report.json`, exec48280. Пользователи5/6, версии1616/1617. Контроллер18696, wrappers5808/1940, actual workers19592/25484. Два simultaneous enqueue; один running, второй queued. Через26.05сек контроллера RAM guard остановил пилот: available789680128bytes. Exit1, terminalfailed, двенадцать samples/16.266сек; peak measured working set442064896bytes, private2579570688bytes (включая контроллер). Ноль завершённых генераций; throughput/cost не доказаны.

Host snapshots сохранены в каждом sample; на предпоследнем vmmemWSL имел3080204288bytes working set при measured pilot tree working set менее0.5GiB. Это не доказывает, что весь провал available RAM вызван workers; причины нагрузки PostgreSQL/WSL требуют отдельного исследования по временному ряду. Порог1.5GiB сохранён.

После завершения проверено отсутствие всех пяти собственных процессов и SQL: обе isolated команды cancelled. Логи workers сохранены; live планы/очередь не изменялись. Не повторять тяжёлый пилот на той же среде без нового решения по памяти. Следующий шаг — анализ host temporal samples и DB catalog-query footprint, затем улучшение ресурсной архитектуры с отдельным согласованным дизайном, а не снижение guard. Старые отчёты не переписаны.

### Локализация скачка по сохранённому временному ряду

В12samples между18.469 и26.047сек available RAM снизилась3972→753MiB. Working set measured pilot tree изменился350→422MiB, тогда как vmmemWSL821→4279MiB. Основной наблюдаемый прирост физической резидентности находится в WSL, а не в измеренных Windows workers. Это не позволяет автоматически обвинить PostgreSQL или его конкретный запрос: Docker, Linux page cache и другие WSL consumers не разделены в исторических samples.

После остановки `docker stats --no-stream`: единственный показанный контейнер curriculum-kag-postgres-shadow195MiB /6.622GiB. Это текущий снимок, не пик во время нагрузки; WSL working set и container memory — разные границы учёта. PostgreSQL work_mem4MB, shared_buffers128MB, max_parallel_workers_per_gather2. Isolated DB размер6904MB. По live shadow крупнейшие таблицы: epvo_discipline_lo_links2407MB, raw_epvo_programs1681MB, raw_epvo_disciplines1556MB, raw_epvo_expert_checks1342MB, normalized496MB; эти размеры не утверждаются размерами isolated таблиц.

Следующий конкретный probe должен наблюдать container memory_stats anon/file/cache и активные SQL внутри уже ограниченного isolated workload. Уменьшение числа worker или ленивый импорт API без этих данных не устраняет установленный WSL скачок. Не менять глобальные лимиты WSL/Docker и не очищать Linux cache пользователя без отдельного решения. Пилот не повторён, БД/конфигурация не изменены.

### Счётчики контейнера и фактический достигнутый этап

Read-only cgroup v2 snapshot после остановки: memory.current229769216bytes, anon29024256, file190562304, shmem147079168. Shmem входит в file: эти значения нельзя суммировать как независимые категории. memory.events oom/oom_kill/max/high=0. `/proc/meminfo` MemTotal6943380KiB, MemAvailable5924468KiB. Это текущий покой, не исторический пик и не доказательство отсутствия Windows memory pressure.

Сохранённые реальные audit events версии1617:975epvo_repository,976scoring,978cancelled. Значит работа успела пройти подготовку EPVO и перейти к scoring; пустые worker logs не означают отсутствие этого этапа. Предыдущая гипотеза о падении исключительно до scoring неверна.

Код planner_stage_cache для каждого epvo_input_signature собирает stamp шести глобальных таблиц; `_table_stamp` выполняет max/count и, где доступно, упорядоченный checksum digest. Это корректная проверка изменения источника, но потенциально дорогая для повторных jobs. Read-only EXPLAIN (НЕ ANALYZE) в isolated DB: count(raw_epvo_programs.id) использует Seq Scan12215estimatedrows; checksum digest raw_epvo_disciplines использует Index Scan408638estimatedrows. Это план запроса, не фактическое время/память и не подтверждённая причина4GBWSL роста. Для точного root cause нужны совместные cgroup/SQL/stage samples, особенно первого scoring. Ослаблять fingerprints или считать max(id) полноценной заменой нельзя: обновления записей на месте должны инвалидировать кеш.

## Конкретный избыточный prefetch scoring

`_prefetch_epvo_expert_links` загружает через `.all()` все связи выбранных normalized aliases, сортируя по discipline_id,id, и лишь потом сохраняет первые32 для каждой дисциплины. Вызов происходит для полного project_courses ДО lexical frontier. Поэтому ограничение32 сейчас ограничивает конечный Python cache, но не SQL result/ORM materialization.

Read-only aggregate в isolated DB с statement_timeout3s: scopeB039/6B031 имеет4774normalized/2343approved; для2342approved дисциплин найдено88402LOlinks. При существующем cap32 сохранялось бы22291 (крупнейшая группа4871). Это scope-wide probe; actual aliases конкретного worker не сохранены, поэтому числа нельзя называть точным query-size этого запуска. Обнаружен самостоятельный подтверждённый inefficiency: загруженные сверх32 строки заведомо отбрасываются. Не установлено, что именно он объясняет весь WSL пик.

Предлагаемое bounded исправление: перенести тот же cap32 в SQL по каждой discipline_id, сохранив первые id, точную alias принадлежность и порядок; SQLite/PostgreSQL должны выдавать идентичные retained records. Regression сначала RED на returned row count при >32links и на содержимое первых32; затем GREEN, fullsuite и PostgreSQL эквивалентность на текущем scope. Глобальный LIMIT32 недопустим, экспертные оценки/gates не меняются. До одобрения этого короткого дизайна продуктовый код не менять; оптимизацию не считать нагрузочной приёмкой.

### Read-only проверка вариантов SQL до реализации

Полное сравнение scope через window row_number + baseline array_agg остановлено statement_timeout5s (exit1); транзакция READ ONLY, данные не изменены. Это не успешная проверка и не основание обещать ускорение window-варианта.

Суженная проверка20normalized дисциплин того же профиля, детерминированно ORDER BY id, в READ ONLY/timeout3s завершилась exit0:635retainedIDs,0changedgroups между прежним ordered array[1:32] и коррелированным ordered LIMIT32. Это подтверждает эквивалентность только этих20групп, не всей системы. Отдельный EXPLAIN LATERAL варианта показывает индекс discipline_id, сортировку и LIMIT внутри каждой группы. Индекс не покрывает combined discipline_id,id, поэтому сортировка внутри группы сохраняется. Фактический выигрыш по времени/памяти пока не измерен.

Решение дизайна следует выбрать по PostgreSQL/SQLite совместимости и реальным retainedIDs, не по более красивому SQL. Не заменять упорядоченные первые32 случайной выборкой и не дробить общий LIMIT без per-discipline семантики. Продакт код и конфигурация не менялись; одобрение короткого дизайна ещё ожидается.
