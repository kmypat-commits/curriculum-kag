# Согласованные исправления и аудит переводов, 12 октября

Прямое пользовательское согласие на ранее предложенные исправления получено; затем пользователь повторно подтвердил. Старые ограничения heartbeat «SQL/UI/оценщик ждут согласования» устарели; prompt обновлён. Новое требование: недостающие RU/KK/EN переводы проверять и переводить лёгким субагентом. Luna агент Kuhn 01a130f8-00cc-7851-8c6b-ed1d9014ffa2 выполнил read-only аудит и предложил пять кандидатов без записи в БД.

## SQL expert links

Реальный SQLite regression: по40links на две дисциплины, должны материализоваться только первые32 поid каждой. RED:80 ORM loads вместо64; retainedIDs уже корректны. Исправление переносит per-discipline ограничение в SQL через row_number, оставляет порядок/aliases/firstIDs. GREEN: весь test_scoring_frontier.py exit0,11tests. Полный backend suite запущен отдельно, итог ещё не подтверждён. PostgreSQL equivalence и фактическая память/время ещё не проверены; window query не гарантирует снижение памяти самого PostgreSQL. Live rollout не выполнялся.

## Переводы

Полный suite первый запуск остановился на collection ModuleNotFoundError:backend (не ошибка SQL regression). Повтор запущен с PYTHONPATH repo+backend и новым TEMP/basetemp; конечный итог ещё ожидается.

Повтор полного backend suite exec19037 завершён exit0,100%,две opt-in skipped; предупреждения deprecated FastAPI/Starlette/reportlab/openpyxl/SQLAlchemy сохранены в выводе. Команда: venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp freshroot; PYTHONPATH repo+backend. PostgreSQL equivalence/load benchmark остаются открыты, live не перезапускался.

Главный агент независимо подтвердил текущий count(courses)=57392, не прежние52394. Причину прироста этот count не доказывает; нельзя приписывать его каждому generation. Субагент установил формальное наличие всех RU/KK/EN слотов и title, но это не наличие настоящего перевода: automatic_course_draft копирует исходные title/description. Главный read-only запрос подтвердил67907 таких draft rows. Статус verified и source следует сохранять, не массово перезаписывать.

Выборка Luna: Тайм-менеджмент, Майнор1, Бизнес-информатика, Неврология, Биостатистика/биоэтика. Все предполагаемые KK отсутствия определены по равенству строк. Международные термины могут корректно совпадать, поэтому эта выборка НЕ подтверждает пять missing translations и НЕ готова к массовому сохранению. Ни одного перевода не сохранено. Следующая выборка должна содержать явно русские нетривиальные описания/названия в KK/EN строках с provenance source_copy, отдельно от интернациональных терминов. source_id EPVO не заменяет integerCourse.id: перед записью нужны точные ID, hash исходника и защита существующих переводов.

## Следующие приёмки

1. PostgreSQL cap equivalence и fullsuite; не повторять тяжёлый pilot до решения RAM.
2. Кеш текущего description отдельно от combined scoring text; actual semantic/lexical/unavailable, без index_course удаления chunks.
3. Исправления fullscreen focus и маркировка viewedA/lastC; реальный running motion/overhead всё ещё открыты.
4. Переводы: ограниченная проверяемая выборка Luna, ручной review, затем обратимое пакетное заполнение только missing/source_copy.
5. Wood pairs требуют документированного предметного review в рамках разрешённой обратимой миграции, не массового удаления.

Технические20/20 не содержательная приёмка;40offset20 не запускаются до новых согласованных контрольных проверок. Статья/start.ps1/unrelateddirty/active.runtime.dist/backups не изменяются.

## Реальное сохранение и rollout, 12 октября 21:52 (+05)

Пользователь повторно прямо потребовал перевести найденное и развернуть исправления. Luna Banach01a13106-7593-7a42-b8c7-184af81e5e8e подготовил9title+description переводов для23131(en),26746/26753/26760/26769(en,kk). Главный агент прочёл JSON/проверил терминологию и сохранение master уровня26769; затем guarded importer подтвердил exact source strings и current source_copy drafts. Apply: prepared9,updated9,skipped0 exit0. Read-back PostgreSQL подтвердил9 строк source=machine_translation_gpt6_luna,status=needs_review. Новые Course не создавались. Snapshot .runtime/luna-translation-snapshot-20261012-01.json содержит before/after/source hashes; CLI --restore сравнивает текущее after и исходный Course перед обратной записью. Машинный draft не объявляется утверждённым переводом.

Importer backend/scripts/apply_localization_batch.py: RED два поведенческих теста (не менялись sourcecopy/не отклонялся изменённый источник), GREEN2/2. Полный backend suite53413 после importer exit0,100%,две opt-in skipped; предупреждения dependencies preserved. Непустые переводы/не-copy и verified строки не перезаписываются; field-level оригинальные переводы сохраняются. Whole-catalog rollout ещё не выполнен.

Перед rollout найдена одна historical running command от8сентября projectversion137 с expired deadline/lease и snapshot timed_out, действующих queued/running snapshots нет. История не изменялась. start.ps1 -RestartBackend сначала остановил старые API/worker и завершился taskkill error на уже убитом child10128. Проверено отсутствие старых PID; повтор БЕЗRestartBackend создал один API/worker, exit0. Health healthy/postgresql/connected, same shadow5433. Новые wrapperPID19988/24960 created21:52:20/26; CONTENT_EVALUATION_MODE=prioritise передан окружением. Источник start.ps1 не редактировался; frontend bundle не менялся. SQLcap и текущие sourcefixes теперь загружены свежими процессами, но это не подтверждение новой генерации/нагрузочной приёмки.

Следующий Luna Pasteur01a1310a-0d28-7aa2-9e21-353706d6a906 работает над batch02:20курсов, только явные sourcecopy drafts; предыдущие5ID исключены. Отчёт о полноте каталога пока невозможен.

Batch02 завершён:20targettranslations. При review выявлен damagedsource26926 с U+FFFD; контекстное восстановление не принято. Добавлен regression RED→GREEN3/3, importer пропускает damaged_source. Затем apply prepared19/updated19/skipped1 exit0. Snapshot .runtime/luna-translation-snapshot-20261012-02.json; итого28 языковых записей title+description сохранено за этот этап, все needs_review. Пропущенный курс остаётся на восстановление первоисточника, не на угадывание. Course26816 имеет общий исходный текст дизайна при названии о спутниках: перевод буквальный, это content-sourceissue, не исправленная предметная пригодность.

PostgreSQL actual function bounded readonly capcheck по31302/31308:2courses,3aliasgroups,3retainedIDs equaltrue exit0. Это tiny compatibility check, не проверка большихгрупп/benchmark. Первая diagnostic -c команда имела PowerShell quoteSyntaxError, ничего не исполнялось; correctedcommandpassed.

Luna Hegel01a1310d-744a-7382-86bb-3acccbc5e69b запущен на batch03,25targetrows. После фактического commitbatch02 отправлено refreshуточнение: перепроверить актуальные sourcecopytargets, не исключатьcourseцеликом, поскольку другойязыкможетоставатьсянепереведённым. Fullsuite77997 послеdamagedguard запущен;конечныйстатуспроверятьпоsession.

Актуально: suite77997 завершёнexit0,100%,двеopt-in skipped. Read-backlocalizations15en+13kk=28,Coursecount57392unchanged. Batch03agentещёнеполучен/несохранён;automationобновленаэтимреальнымсостоянием.

## Batch03: фактическое сохранение

Hegel завершил25 переводов (13EN/12KK,21курс). Главный агент проверил исходные и переведённые тексты; перед импортом убрана завершающая запятая, недопустимая в strict JSON. Guarded apply: prepared25/updated25/skipped0,exit0. Snapshot .runtime/luna-translation-snapshot-20261012-03.json. Read-back:28EN+25KK=53 записи needs_review; courses57392, без создания дисциплин. Перевод26816 сохраняет общий исходный текст дизайна: предметный дефект исходника остаётся. Наличие машинного перевода не означает методическое утверждение. Hegel продолжает batch04 по актуальным sourcecopy строкам; новых массовых генераций не запускали.

## Batch04 и разрешение полной очереди

Пользователь прямо разрешил все недостающие переводы и коммиты/push. Код и отчёты опубликованы f1e7b3d; frontend59/59, backend fullsuite exit0 и Vite build exit0 проверены перед публикацией. start.ps1 и локальные данные не включались.

Batch04:25title+description переводов сверены с исходными текстами; guarded apply prepared25/updated25/skipped0 exit0, snapshot .runtime/luna-translation-snapshot-20261012-04.json. PostgreSQL read-back40EN+38KK=78needs_review, courses57392unchanged. Hegel продолжает batch05 на50 актуальных языковых записей с расширением предметной выборки; полнота каталога не заявляется. A/B/C разные objectives ещё не реализованы: joint_solver пока минимизирует общую отрицательную utility с двухфазным предпочтением покрытия.

## Возобновление 13 октября

Batch05 найден на диске: strict JSON валиден,50уникальныхпар (26EN/24KK), damagedsource U+FFFD0. Старый агент Hegel возвращает not_found, не считается работающим. Пакет ещё НЕ применён: нужна содержательная сверка всех текстов. Первый PostgreSQL read-back попал в запуск контейнера (socket ещё отсутствовал); docker logs подтверждают штатную остановку18:18UTC и новый старт20:22UTC, ready-to-accept, не повреждение данных. Повторный read-back выполнен отдельно. Перезапуск или новая генерация не инициировались.

## Batch05 и пользовательский список

Luna Aristotle01a131c9-0369-76b3-a284-16b205e018a2 отдельно reviewed50/accepted50; отчёт .runtime/luna-translation-review-20261013-05.json, совпадение всех targetpairs проверено главным агентом. Exactsource dryrun prepared50/skipped0; apply prepared50/updated50/skipped0 exit0, snapshot .runtime/luna-translation-snapshot-20261013-05.json. Read-back66EN+62KK=128машинныхязыковыхзаписей needs_review. Выявленные sourceissues26737/26751/26758/26742 сохраняются, перевод не подтверждает предметную пригодность.

Пользовательский pastedlist содержит46missingmarkers/45EPVOcodes; первый курс Лидерство и стили руководства без кода требует точного сопоставления. Aristotle готовит приоритетный .runtime/luna-translation-userlist-20261013-01.json, DBreadonly. EPVO-190709 internal57969: пользователь подтвердил ошибку казахского названия вRU. Guarded correction одногоRUtitle на Изучение наследия Узбекали Жанибекова, statusneeds_review/provenanceuser_reported_translation_correction; KK/ENunchanged read-backverified. Snapshot .runtime/ozbekali-ru-correction-20261013.json совместим с apply_localization_batch.py --restore. Course.title/rawEPVOнепереписаны, localizationsсодержатисправление.

Пользователь прямо согласовал контракт A/B/C: B относительно исходного плана вуза, не A; отсутствие исходной базы должно быть явной диагностикой. Реализация этой целевой функции пока не выполнена.

## Приоритетный пользовательский пакет01: сохранён

Первые5 карточек пользовательского списка сопоставлены с Course50855/50850/50849/50841/46676; первая карточка без кода однозначно соответствует EPVO-29033. Все10KK/EN названий и описаний прочитаны перед применением. Найденные в EPVO переводы импортированы с честным source=epvo_translation_recovered_reviewed и status=needs_review, не обозначены заново сгенерированными Luna. Явная опечатка EN46676 исправлена на International Customs Law. Exact-source guarded apply prepared10/updated10/skipped0 exit0; PostgreSQL read-back всех10 записей и RU57969 подтверждён. Snapshot .runtime/userlist-translation-snapshot-20261013-01.json поддерживает защищённый откат. Подтверждённые/manual записи не перезаписывались. Aristotle готовит следующие10 карточек в userlist-20261013-02; на момент проверки файл ещё отсутствует, это не применённый пакет.

Режим A подключён в исходном коде (5abf48e), а не только opt-in solver: weighted-max-lo-1, веса и стратегия включены в frontier hash. B/C и отдельный исходный snapshot ещё не реализованы. Live rollout нового A не подтверждён. Текущая running строка planner_build_jobs id1 имеет updated_at 2026-09-08; одной этой строки недостаточно для утверждения о живом процессе или разрешения перезапуска.
