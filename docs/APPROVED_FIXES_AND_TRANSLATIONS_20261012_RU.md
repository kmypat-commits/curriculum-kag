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

## Приоритетный пользовательский пакет02

Главный агент прочитал18 переводов title/description и точные исходники9карточек:
39888/38772/37955/37799/35479/35212/35153/35021/35020. Exactsource guarded apply
prepared18/updated18/skipped0 exit0. Snapshot .runtime/userlist-translation-snapshot-20261013-02.json.
Неизменённые EPVO переводы помечены epvo_translation_recovered_reviewed, исправленные
и source-aligned переводы — machine_translation_gpt6_luna; provenance сохранён
в snapshot, все needs_review. Карточка44751 Связи с общественностью содержит
U+FFFD в исходнике и не изменялась. По пользовательскому списку пока применено
28языковыхзаписей14карточек, одна из первых15 требует восстановления источника.
Aristotle продолжает следующие15карточек в пакет03; это не завершённый каталог.

## Каталожный аудит источников переводов,13октября

Текущий PostgreSQL count57392courses; RU/KK/EN строки есть у каждого курса,
пустых title/description в наблюдаемых группах0. Наличие строк не означает перевод:
automatic_course_draft exactsourcecopy EN22556/KK22558/RU22634. Для исходного RU
совпадение нормальное и само по себе не является пропущенным переводом.
Все эти draft связаны с EPVO по точному коду; непустые исходные переводы EPVO
есть у EN22550/KK22552/RU22628. Это кандидаты восстановления, не доказательство
правильности переводов; verified/manual/source issues остаются защищёнными.
Первый SELECT ошибся из-за неоднозначного language, correctedqualifiedquery выполнен.
Readonly export100KK/EN candidates просмотрел101 строку, отклонил1 английский
текст с кириллицей; .runtime/epvo-recovery-review-20261013-01.json. DATABASE writes0.
После пользовательского пакета03 Luna проверяет все100 перед guarded import.
Массовый старый SQLite upsert не используется: он перезаписывает existing поля.

## Защита от повторного импорта при генерации

Обнаружен действующий путь planner_build→register_course_translations, который
безусловно заменял существующие переводы. Реальные SQLite ORM регрессии RED
воспроизвели перезапись manual/verified,epvo/verified,Luna/needs_review и уже
переведённого automaticdraft. Теперь обновляются только automatic_course_draft/draft
и только пустые либо sourcecopy поля; прочие строки сохраняются. Отдельный
characterization тест подтверждает восстановление описания без замены уже
переведённого названия. Первый GREEN выявил NameError из-за import в другой
одноимённой области; scopedimport исправлен, ненужный import удалён. Suite5670
exit0,двеopt-inskipped; после finaltest повторный fullsuite50763 проверен отдельно.
Это sourcefix, НЕlive rollout и НЕзавершение переводов каталога.

## Контролируемый rollout13октября

Перед перезапуском actual API25800/child29484 и worker19896/child18768 проверены
поCIM. Текущих plan_build_status queued/running0; historical job1/version137 имеет
deadline и lease от8сентября, не изменялся. Первая launcher попытка RestartBackend
остановила процессы, затем exit1 из-за taskkill уже остановленного child18768.
После подтверждения отсутствия всех старых PID повтор безRestartBackend создал
API16744/worker23644 (01:48:32/38 local), frontend22360 сохранён, same shadow5433.
HTTP health healthy/databasepostgresql. Launcher readiness log подтверждён, но
outer exec18025 пока не вернул terminalexit; не выдавать его за exit0.
Новый запуск наследует CONTENT_EVALUATION_MODE=prioritise. Обновлены A и защита
переводов; B/C остаются opt-in solver без исходного snapshot/UI. Generationcontrol
после rollout ещё не выполнен, health не подтверждает содержательную пригодность.

## Пользовательский пакет03 и реальный контроль A

### Проверка отчёта восстановления EPVO, 13 октября

Получен epvo-recovery-verdict-20261013-01.json: 100 языковых записей,
71 accepted / 29 rejected по машинному обзору Luna. Это НЕ проверка человеком:
поле human_semantic_review_complete ошибочно, запрошена отдельная исправленная
версия отчёта без переписывания исходного evidence. Агрегат exact matches100
противоречит отдельным db_checks=false; текущую БД этот агрегат не подтверждает.
Основной агент отдельно сопоставил все100 verdict с export по identity, EPVO ID,
source/target title+description: несовпадений0. Это сравнение файлов, НЕ live SQL.
Импорт этих записей пока не выполнялся. Отклонённые переводы включают подмену
магистрантов на undergraduates, дистанционных методов на дистанционное обучение,
технических СВЧ-генераторов на бытовые печи и пропуски профильного содержания.
Предстоят исправленные provenance, полный обзор принимаемых текстов и guarded
current-source проверка перед snapshot-backed записью; verified/manual защищены.

Основной read-only current DB check затем подтвердил eligibility всех71 draft,
courses57392, updates0; epvo-recovery-current-check-20261013-01.json. Это не
семантическое одобрение71. Прочитаны полностью первые8 принятых пар; отдельные
KK термины всё ещё требуют исправления (spacecraft передано как «ғарыш», embedded
systems как «енгізілген жүйелер»). Не импортированы автоматически по verdict.
Ограниченно восстановлены4 пары:26764en,26766kk,26767en,26768en, title+description.
Snapshot epvo-recovery-applied-snapshot-20261013-01.json записан эксклюзивно и
fsync до UPDATE; guarded apply exit0 updated4, courses57392→57392. SQL readback
подтверждает source epvo_translation_recovered_reviewed/status needs_review.
Это машинный обзор с обязательной последующей проверкой, не human approval.
После readback английское title26764 уточнено: spacecraft вместо space.
Отдельный before/after snapshot epvo-26764-en-title-correction-20261013.json;
guarded UPDATE1 и SQL readback подтверждены, описание/статус не менялись.

Следующие12 принятых Luna пар полностью прочитаны основным агентом. В26771kk
найдено искажение трибомеханики («тайпемеханикалық»),26770kk требует грамматической
переработки,26775kk меняет создаваемые системы на созданные; эти3 не импортированы.
Применены9пар:26768kk,26770en,26772en/kk,26773en/kk,26775en,26776en,26779en.
KK названия26768/26773 уточнены до жерсеріктік байланыс/қашықтықтан зондтау;
EN описание26770 грамматически исправлено без добавления темы. Snapshot02 до записи,
guarded updated9 и exact readback title/description/status9, count57392→57392.
Всего из100 recovery применено13 языковых записей; это не завершение каталога.
Исправленный verdict-v2 явно machine_semantic_review_luna_not_human, withdraws
старые db_checks и ограничивает exactcrossmatch сравнением export/artifacts.

Следующие10пар (accepted индексы20–29) прочитаны полностью. Восстановлены8:
26779kk,26780en/kk,26782en,26783en/kk,26784en,26786en. Уточнены EN titles
Applied Earth Sciences and Environmental Management / Testing Systems for Space
Equipment и KK жерсеріктік деректер; snapshot03 до записи, updated8/readback8,
courses57392→57392.26782kk требует проверки термина reinforcement learning;
26785en использует polygraphy вместо printing для полиграфии — эти2 не применены.
Recovery всего21/100, остальные не считаются завершёнными; machine needs_review.

13 октября повторный read-only committed readback пакетов02/03 подтвердил
точные9+8 языковых записей, count courses57392. Luna Aristotle получил следующие
20 ещё не применённых пар из оставшихся79; PR44751 не повторять, snapshots01–03
исключить. Только новый artifact без DB writes, затем полная проверка main и
guarded snapshot-backed apply. Предыдущий completed ответ касался PR, не79пар;
новое поручение отправлено отдельно. Переводы каталога ещё не завершены.

Пакет luna-epvo-recovery-revised-20261013-02 полностью прочитан:15переводов,
5holds. Main сверил exact exportsource и отсутствие overlap21; guardedupdated15,
skipped0, exclusive snapshot epvo-recovery-revised-snapshot-20261013-02 до записи,
отдельный committed readback15. Recovery теперь36/100 needs_review, неhumanapproved.
Hold26776kk неверно относил повреждение старого target к целому source: передан
на отдельный перевод без угадывания. Другие4holds требуют восстановления source.
Агенту поручены следующие20 вне уже рассмотренных41, безDBwrites.

26776kk отдельно переведён из целого exact source, полностью прочитан main;
guarded updated1 и committed exact readback1, snapshot luna-26776-snapshot-20261013.
Recovery37/100. Старый отказ по damaged source для этой пары опровергнут, а не
обойдён угадыванием. Другие повреждённые источники всё ещё отложены.
Перед live rollout SQL queued/running0; API listener16136 StartTime13Oct01:48:32,
uvicorn loopback8000, parent16744 отсутствует. pids.json stale: штатный restart
может пропустить orphan API. Live пока не перезапущен; требуется адресная проверка
API/worker identities и контролируемый запуск, не изменение пользовательского start.ps1.

Повторный CIM full query опроверг предыдущую запись об absent parents:16744/23644
существовали с ожидаемыми commandline/StartTime. Ошибку наблюдения не выдавать за
реальную потерю процесса. После freshSQL active0 и identity guards выполнен адресный
restart только API/worker trees. Новые wrappers15296/12328 StartTime13Oct02:26:02,
children20456/14832. Healthhealthy/PostgreSQLconnected, workerstarted подтверждены.
Same shadow5433/prioritise/loopback, threads4; frontend2024/dist/start.ps1 неизменны.
Runtime pids.json обновлён. Код4609ca0/evaluator1.8 загружается новым процессом;
это availability rollout, не fresh generation/content/load acceptance.

Luna revised03: все20 полных source+target прочитаны main, сохранены уровни
магистратуры, GEONETCast/ILWIS, CAD/NASTRAN, SAR и КОМПАС. Exactexport/allprevious
exclusion guards, updated20/skipped0; committedreadback20, count57392unchanged.
Snapshot epvo-recovery-revised-snapshot-20261013-03 до записи. Recovery57/100,
4holds повреждённых source (26761en/kk,26771en/kk), оставшиеся39 ещё не обработаны.
Следующие20 поручены Luna в revised04, безDBwrites; никакой humanapproval не заявлен.

Revised04 полностью прочитан main:19/20 применены guarded/exclusive snapshot04,
exact committed readback19.26809kk удержан: airframe/планер был сужен до фюзеляжа;
агенту поручено отдельное исправление без перезаписи artifact04. Recovery76/100,
4sourceholds+1translationhold, ещё19 необработанных пар. Luna готовит исправление
26809kk и remaining19 batch05. Source заявления о prerequisite26803 сохранены
только текстом; graph edges не создавались.

Свежий полный SQL inventory: automaticdraft EN22487/KK22489/RU22632; все эти
строки exactsourcecopies (title+description), emptytitles0. Это не число доказанно
missingtranslations: язык исходника/международныеназвания требуют классификации.
MachineLuna needs_review EN117/KK121/RU1. Для EN/KK countdistinct fullsourcepair
равен22487/22489: exactfulltext reuse не сокращает этот остаток. Текущий100pair
recovery не представляет весь каталог; не объявлять завершение всехпереводов после100.
НовыеCourse не создавались. Проверки readonly, никаких masswrites/modelruns.

### Пользовательский список: пакет04 применён

Полностью прочитаны16карточек source+30KK/EN targets, включая последнюю
Управление брендингом. Frozen batch SHA256
b9a6218cb792a10da79730667f86ee1e75053d8ffb5714ef17acb3ce171ee4b8 проверен
до guarded apply. Prepared30/updated30/skipped0, snapshot04 записан до UPDATE.
Отдельная read-only проверка после commit подтверждает точные30 title/description/
source/status; count57392. Userlist теперь89языковыхзаписей44карточек из46.
44751 Связи с общественностью — повреждённый исходник;35002 Промышленный маркетинг
— description обрывается на «модель К», пока не переведены полностью. Переводы
не считаются академически утверждёнными: machine_translation_gpt6_luna/needs_review.
Казахское название35002 в RU также остаётся отдельным открытым исправлением.
Затем RU название35002 отдельно исправлено до «Промышленный маркетинг» без
изменения обрезанного описания. Snapshot userlist-35002-ru-title-snapshot-20261013.json,
guarded updated1 + exact committed readback1. Source machine_translation_title_only,
needs_review; KK/EN полные описания по-прежнему отложены. Userlist90 языковых правок,
44 полностью обработанные карточки + одна с исправленным только RU названием.

### Источники двух отложенных карточек

Read-only просмотр всех exact normalized source_keys7881 (8 raw records) и20866
(1 raw record) выполнен. Courses44751 description совпадает с повреждённым
raw1488284. Raw672761 содержит неповреждённые «коммуникативной» и
«коммуникационных» в соответствующих контекстах; сам672761 повреждён в других
местах, целиком заменять описание нельзя. Возможна точечная source-backed
коррекция двух фрагментов с отдельным snapshot и защитой draft/manual полей,
пока НЕ применена. Другие raw PR описания содержательно отличаются, одного
названия недостаточно для их взаимозаменяемости. Raw2126433 также обрывается
на «модель К»; полного continuation в exact-code источниках не найдено.
Evidence source-recovery-candidates-userlist-20261013.json, database_updates0.

Затем source-repair выполнен отдельно: dry-run подтвердил2точных повреждённых
фрагмента,3eligible sourcecopydraft. Snapshot pr-source-repair-snapshot-20261013.json
включает courses/normalized content_json/localizations before+after и sourcekeys.
Guarded transaction исправила только2слова в Course44751,normalized7881RU и3draft
копиях. RawEPVO не изменён, manual/verified не затронуты. SQL после commit:
оба восстановленных слова присутствуют, U+FFFD отсутствует, count57392.
Новый исходник передан Luna для KK/EN; сами переводы ещё НЕ применены.
Существующие score/vector caches и course chunks не удалялись; перерасчёт/проверка
актуальности содержания остаётся отдельной задачей до содержательной приёмки.

PR44751 новые KK/EN title+description Luna полностью прочитаны основным агентом,
сверены с source_after snapshot, guarded prepared2/updated2/skipped0, отдельный
snapshot05-pr и exactcommittedreadback2. «Пререквизиты отсутствуют» сохранено как
текст описания, prerequisite graph не менялся. Userlist45/46 полностью переведённых
карточек,92языковые правки;35002 имеет правильный RUtitle, полное описание ещё
не восстановлено. Машинные переводы остаются needs_review, не human approval.

Прочитаны все30KK/EN title+description и15точных исходников пакет03; guarded apply
prepared31/updated31/skipped0 exit0, snapshot userlist-translation-snapshot-20261013-03.json.
ДобавленRUtitle35009 Продукт, ориентированный на сообщество и KKtitle Қауымдастыққа
негізделген өнім вместо untranslatedEnglish; ENназвание сохранено. Исправлена
переносная опечатка seg-mentation в EN35011. Userlist total59языковыхзаписей29карточек,
44751 damagedsource остаётся отложенным; дальнейшие16карточек ещё не применены.

Один immutable frozen10251 A control ledger recheck-abc-a-20261013-cases-20260927.json
terminalpassed1/1, actualrunner14688 завершён. Report diag-10251-abc-a-20261013-20260927.json:
48.70s,243credits,hard0. Independent check_variant issues[],8семестров/27–33нагрузка.
Первый helper ошибочно сравнил fileSHA с reportedcanonicalSHA и выдалfalse; исходник
не менялся. Исправленный отдельный evidence check-abc-a-control-20261013-v2.json:
fileSHA и canonicalSHA совпадают с frozenmanifest, canonicalSHA с report — true.
Содержательно46courses/16needs_review/core_definition_missingtrue: это не экспертная
приёмка и не допуск40. Старый неверный helperoutput сохранён, не подменён.

13октября: последний recovery batch05 полностью прочитан;16пар и исправленный
26809KK применены guarded prepare/apply с exclusive snapshot
.runtime/epvo-recovery-final-reviewed-snapshot-20261013.json. Exact committed
readback17; courses57392 неизменны. Recovery100 теперь93applied,4sourceholds,
3translationholds:26822EN термин вепольного анализа,26828EN/KK подмена
«активности» на «эффективность». Эти3 не применены; все переводы needs_review,
не предметное одобрение. Исходные артефакты и прежние snapshots сохранены.

Recovery correction06: полностью прочитаны3source/target, термин26822EN исправлен
на substance-field analysis;26828EN/KK сохраняет activity/белсенділік с явным
machine review_note о неоднозначности исходника. Guarded updated3, exact committed
readbacks3; exclusive snapshot .runtime/epvo-recovery-holds-snapshot-20261013-06.json.
Теперь96/100applied,4повреждённых/неоднозначных исходных записи остаются held.
Courses57392 unchanged. Это завершение данного пакета, НЕ всех переводов каталога
и НЕ human approval; source/raw и предыдущие артефакты не менялись.

Sourcecopy07: текущий readonly export26, Luna24translations+2sourceholds26836.
Main полностью прочитал26source/target;19 guarded applied/readback19,
exclusive .runtime/luna-sourcecopy-snapshot-20261013-07.json, courses57392 unchanged.
Пять reviewholds:26829EN/KK неоднозначное «полевое загрязнение» (KK добавляет
егістік);26834EN различие ЦММ/ЦМР требует точной терминологии;26841EN/KK
soil-adjusted index необоснованно уточняет почвенно-вегетационный индекс.
Два sourceholds26836 содержат склейки терминов; пока не применены. Все записанные
переводы machine needs_review, защищённые поля/исходники сохранены.

Correction08 полностью прочитан:26834EN сохраняет различие ЦММ/ЦМР буквальными
терминами и исходными сокращениями;26841EN/KK soil-vegetation без выдуманного
soil-adjusted. Updated3/readbacks3; exclusive snapshot08. Sourcecopy07 теперь
22/26applied,26829EN/KK неоднозначное загрязнение и26836EN/KK склейки held.
Live PID registry изменён внешним запуском: wrappers21252/10512 и frontend2464,
actual backend8704/worker8784, CreationDate13Oct10:47:08/19 local. Старые PID
не действуют. DB queued/running0 при проверке; этот агент сервисы не перезапускал.
Загруженная версия этим наблюдением не подтверждена. Дизайны baseline/model
запрошены для письменной проверки, цели/разрешённые переводы повторно не согласуем.

Sourcecopy09 main полностью перечитал длинные тексты boundedchunks:24translations
guarded applied, exactcommittedreadbacks24, exclusive snapshot09; courses57392
unchanged. Магистратура, отрасли и пометка26852 «на русском языке» сохранены.
26848EN/KK held: грамматическая неоднозначность цели «при разработке, анализ»;
ничего не додумывалось. Машинные записи needs_review, не экспертное одобрение.
Отдельно: baseline CSV/XLSX design прямо approved, см.ABC_STRATEGY_CONTRACT;
обучаемая модель ещё ждёт решения после объяснения деталей.

Sourcecopy10: main прочитал все13source и26target без итоговой усечки после
bounded повторов.24guarded applied/readbacks24,exclusive snapshot10,courses57392.
26869EN/KK held: потеря указания магистратуры из исходника; остальные темы,
программные бренды и уровни сохранены. Статус needs_review, не human approval.

Correction11:26869EN/KK полные source/targets сверены, master's students/
магистранттар восстановлено. Guarded updated2, exactcommittedreadbacks2,
exclusive snapshot11. Sourcecopy10 теперь26/26applied, courses57392 неизменны.
Это полнота данного пакета, не всего каталога. Машинный статус needs_review.

15 октября, sourcecopy26+corr27: все13пар source/title/ENKK прочитаны;
guarded updated26, exact committed readbacks26, courses57392 unchanged.
Exclusive snapshot .runtime/luna-sourcecopy-snapshot-20261015-26.json.
26968KK локализация робота исправлена с изоляции на определение положения.
Manual/verified защищены; все записи machine needs_review, не human approval.
Это завершение пакета, не переводов всего каталога и не общей цели.

15 октября, sourcecopy24+corr25: все source/targets полностью прочитаны,
guarded updated24, exact committed readbacks24, courses57392 unchanged.
Exclusive snapshot .runtime/luna-sourcecopy-snapshot-20261015-24.json.
26961KK очистные горные работы переведены как өндіру, не бытовое тазарту.
26952EN/KK held: название и начало про методологию исследований, остальное
описание про software engineering/testing. Исходник не переписывался.
Записи machine needs_review, не human approval; весь каталог ещё не готов.

15 октября, sourcecopy22+corr23:24 guarded applied,24 exact committed readbacks,
courses57392 unchanged; exclusive .runtime/luna-sourcecopy-snapshot-20261015-22.json.
Все source/targets прочитаны полностью; EN stability/master's students исправлены.
26933EN/KK held: неоднозначные категории параллельных/последовательных цепей.
Первый apply остановлен доDB из-за trailing comma в holds исходного JSON22,
которую PowerShell принимал. Оригинал сохранён как22.invalid-json, удалена только
запятая; Python json.tool RED→GREEN, затем exactsource guarded apply/readback.
Переводы machine needs_review, не предметное одобрение. Каталог не завершён.

15 октября, sourcecopy18+corr19/20/21: все исходники и target тексты прочитаны;
guarded updated24, exact committed readbacks24, courses57392 unchanged.
Exclusive snapshot .runtime/luna-sourcecopy-snapshot-20261015-18.json.
26927 опечатка названия интерпретирована по явному тексту описания, source
не изменён; review_note correction19 сохранён при замене KK предложения21.
26920EN scientific вместо необоснованного basic.26929EN/KK остаются held:
неоднозначное «Квалификация объектов управления» не исправлялось по догадке.
Все записи machine needs_review, не human/академическое одобрение.

15 октября, sourcecopy17: все12пар source/title/EN/KK прочитаны полностью;
guarded updated24, exact committed readbacks24, courses57392 unchanged.
Exclusive snapshot .runtime/luna-sourcecopy-snapshot-20261015-17.json.
Две26910EN/KK held: повреждённая конструкция «рассмотрены подготовка специалистов»;
предполагаемый смысл не подставлялся. Все записанные переводы machine needs_review,
не академическое или human approval. Полный каталог ещё не завершён.

15 октября, sourcecopy14: полностью сверены13исходников и24перевода,
correction15 прочитан отдельно после усечённого первого вывода.26887 сохраняет
электрическую энергию и неполный исходный пункт с review_note. Guarded updated22,
exact committed readbacks22, courses57392 unchanged. Exclusive snapshot:
.runtime/luna-sourcecopy-snapshot-20261015-14.json. Четыре строки held:
26894EN/KK неоднозначное «нанодротики» не заменяем nanowires;26898EN/KK
оборванный пункт НИР. Статус machine needs_review, не human approval.

15 октября: после восстановления Docker пакет sourcecopy12 с correction13
применён: updated26, exact committed readbacks26, courses57392 unchanged.
Все26 source/targets прочитаны; исправлены KK радиус действия робота26875
и сохранена неполнота исходного пункта26886 без выдуманного глагола.
Exclusive snapshot: .runtime/luna-sourcecopy-snapshot-20261014-12.json,
с исходными значениями, source hashes и hashes обоих translation artifacts.
Manual/verified защищены guarded importer; записи machine needs_review,
не human/академическое одобрение. Это не завершение всех переводов каталога.

15 октября, sourcecopy28: все26 source/targets прочитаны полностью; guarded
updated24, exact committed readbacks24, courses57392 unchanged. Exclusive
snapshot: .runtime/luna-sourcecopy-snapshot-20261015-28.json. Две строки
26989EN/KK held: термин «грубость» переведён как roughness/дөрекілік, но
специализированная терминология требует отдельного подтверждения; догадка
не применялась. Manual/verified защищены, записи machine needs_review, не
human/академическое одобрение. Это завершение пакета, не всего каталога.
