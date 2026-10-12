# Реализация оценки содержания — 2026-10-08

План: docs/superpowers/plans/2026-10-08-content-evaluation-live-map.md.

Ruling: работа в существующей feature-ветке и текущем checkout — пользователь
требует внедрение в действующую систему; start.ps1 и чужие output/tmp сохраняются.

Контракты: оценка передаёт доказательства и advisory приоритет frontier; журнал
передаёт реальные события UI с job_id; сохранённые оценки привязаны к snapshot.
Эквивалентность с неопределённостью не меняет hard gate. Неизвестное содержание
не получает ложную положительную оценку. Резервное восстановление проверяется
на отдельной тестовой БД, а не поверх пользовательских данных.

- Локальный оценщик v1.2: версия, исходные фрагменты, hash, раздельные показатели;
  недостаточные данные/неопределённость не превращаются в положительную оценку.
  Embeddings используются для advisory-повторов, совместимость моделей/уровней
  сохраняется; повреждённый необязательный vector даёт finding, не исключение.
- Режим shadow по умолчанию; opt-in prioritise меняет только utility/frontier.
  Существующие hard gates и подтверждённые обязательные блоки не изменены.
- Оценка сохраняется в общей границе persist_plan_result, включая CLI.
  Cohort сохраняет её до удаления временного проекта. API проверяет владельца,
  роль и plan/version identity; stale вычисляется по фактическому snapshot.
- Durable AuditEvent-журнал по job_id, cursor, worker ownership; чужой/старый
  worker и диагностический вызов без ownership не могут дописывать запуск.
  32 точно распознанных синтетических события тестов проекта15 перемещены
  в action=planner_build_test_quarantine, не удалены; исходный snapshot:
  .runtime/content-test-events-quarantine-20261009.json. Пользовательские планы
  не изменялись. Старые события не представляются как реальная генерация.
- UI: кнопки оценки и карты, lazy Cytoscape, максимум150 nodes, агрегаты;
  пауза polling в скрытой вкладке, stop terminal/superseded; mobile/reduced
  motion и переключатель графа используют текстовый вариант. При partial
  publication отклонённая альтернатива не подсвечивается как сохранённая.
- TDD RED→GREEN: оценщик, приоритеты, ownership, публикация, API, PATCH proxy,
  identity race, частичная публикация, text fallback, stop-on-failure runner.
- 2026-10-09: полный backend 444/444 до последней защиты invalid embeddings;
  её targeted14/14; финальный suite ниже обновляется после выполнения.
  Frontend29/29, production build exit0, git diff --check exit0.
- Финальная проверка2026-10-09: backend445/445, exit0;
  .runtime/content-evaluation-backend-release-20261009.log. Сохранились
  предупреждения зависимостей (Starlette/utcnow), failures нет.
- Bounded browser pass: desktop1280×900 и mobile390×844, общая ширина
  документа1265/381 соответственно; новый overflow не обнаружен. Escape
  закрывает развёрнутый режим. Mobile действительно использует text fallback;
  старый CLI-план честно показывает отсутствие сохранённого журнала.
  Настоящая animated job QA и graph-open overhead ещё не закрыты.
- Реальная shadow-проверка сохранённых версий1602–1611:10/10 прочитаны,
  .runtime/local-content-shadow-20261008-ten-v2.json,3.599с. Это review,
  НЕ новая генерация и НЕ академическая приёмка.
- Сравнение1603: оба режима в одной PostgreSQL REPEATABLE READ transaction,
  никаких опубликованных изменений; полный rollback. Evidence:
  .runtime/local-content-comparison-1603-20261009.json. Shadow1.950с:
  mismatch5/supported32; prioritise2.099с: mismatch2/supported38; оба verified.
  Это один пример, не доказательство общего улучшения или ускорения.

## Открытые условия приёмки

- Явно отрицательная контекстная проверка пока ограничена древесиной/металлом;
  остальные неопределённые случаи требуют предметной проверки. Полнота ядра
  без подтверждённых профильных блоков не установлена. Не вводить общий процент.
- Новая серия20→40 должна быть повторена с теми же frozen inputs; нельзя
  подменить её прежними60 или десятью сохранёнными review-планами.
- Нужны финальная desktop/mobile/keyboard QA на реальном новом журнале,
  измерение graph-open overhead, параллельные/restart задания и фактический
  backup/restore пилот. Admin пароль пока не заменён, только loopback;
  сетевой выпуск запрещён до безопасной настройки доступа.
- Self-review: нет инструмента subagent. Независимого code reviewer не было.

## Исправление ложных оснований соответствия — v1.3

- Живая review-проверка обнаружила, что общие слова из mission/goal
  (научное/социальное/национальное развитие) делали пищевой курс supported
  для деревообработки. RED regression → GREEN11 evaluator tests.
- Положительное основание теперь требует признака именованного профиля;
  общий mission statement и высокий LO score сами по себе недостаточны.
  Подтверждённые профильные синонимы древесины/мебели сохранены.
- Новый REPEATABLE READ контроль1603, .runtime/local-content-comparison-1603-20261009-v13.json:
  shadow2.108с,55курсов,mismatch5,supported8,needs_review29;
  prioritise5.442с,52курса,mismatch0,supported28,needs_review11,duplicate_groups1.
  Оба verified; опубликованные планы не менялись. Неопределённый дубль
  требует разбора, а не автоматического удаления. Это не общий speedup.
- Первый замерv1.1 не использовать как окончательный показатель качества:
  в нём были ложноположительные основания общего контекста.
- Финальный backend послеv1.3:446/446, exit0;
  .runtime/content-evaluation-backend-v13-20261009.log. Frontend29/29.

## Новый полный контроль — 2026-10-09

- Код40a56ba опубликован в текущей feature-ветке. Прежний dirty start.ps1
  не включён в коммиты. Live backend обновлён доv1.3 после проверки0UIjobs;
  wrapper19424, actual15376. CLI-runner независим от этого процесса.
- Запущен .runtime/system-20-localcontent-v13-20261009.json, count20,
  case-offset0, variantA, frozen manifest прежний, prioritise,
  --stop-on-failure, timeout900. Runner22364, created_at1791524813.454;
  провереныPID/CreationDate, не только существование файла.
- На первой проверке:10251 internalpassed,244credits,hard0, local-content-1.3;
 0profile_mismatch,3needs_review,1duplicate_group. Это НЕ содержательная
  приёмка20. Серия продолжает работать; версия кода во время серии не меняется.
- Пара517/734 имеет одинаковый текст описания, но названия
  «Профессионально-ориентированный иностранный язык» и
  «Профессиональный казахский (русский) язык» различают назначение/языки.
  Не признавать их эквивалентными и не удалять. При content review проверить
  ложные warnings копированных descriptions и роль supporting; общий
  культурный словарь не должен ошибочно подтверждать профессиональное ядро.
- Автоматизация curriculum-kag-20-40 создана ACTIVE, каждые30мин.
  Старой curriculum-kag в приложении уже нет, дубликат не создан.
- Идёт согласованный pg_dump перед пилотом: .runtime/backup-content-catalogue-20261009.py,
  docker curriculum-kag-postgres-shadow, target .runtime/content-catalogue-80267ad-20261009.dump.
  Пока нет host metadata/exit0, backup НЕ подтверждён; restore НЕ проверен.
  Snapshot относится к каталогу до новой серии, версия code сохраняется отдельно.
- Backup завершился exit0:2356558525bytes,404.96с;
  .runtime/content-catalogue-80267ad-20261009.dump и .json.
  SHA2566269d88764e109572d6c9705b44852f568dde58cd9c9d6c5212d37c868f74aef.
  Restore всё ещё не проверен. Повторно pg_dump не запускать.

## Отказ20373 и clinical boundary — 2026-10-09

- Первый v1.3 повтор завершён failed:4passed/1failed,5completed из20;
  runner22364 отсутствует. Старый отчёт сохранён без изменений.
- Обе попытки20373: MILP optimal, hard0, verifier quality rejection
  semester_appropriateness. Полная трасса:
  .runtime/trace-joint-20373-localcontent-v13-20261009-verification.json.
  Курс7849 «Основы сестринского дела и практика первой доврачебной помощи»
  размещался в6/7 семестре при проверяемом медицинском deadline4.
- Первопричина: foundation_max_semester использовал substring «врачебн»
  внутри «доврачебной», в отличие от boundary-aware verifier. Изменена
  проверка клинического термина на has_domain_term; verifier не ослаблен.
  Не менялись кредиты, входы, LO, prerequisite edges или catalog.
- RED: test_preclinical_first_aid_foundation_is_not_advanced_physician_practice,
  actual8 vs expected3; GREEN:66 curriculum/frontier tests.
  Полный backend447/447 exit0: .runtime/clinical-boundary-backend-20261009.log.
  Первый full-suite command имел ошибку PYTHONPATH при collection; повтор
  с repo+backend в PYTHONPATH прошёл. Dependency deprecations сохраняются.
- Исходный20373 отдельно PASSED244credits hard0 qualitytrue wrong_semester0,
  31.92с. Report .runtime/diag-20373-clinicalboundary-20261009-20260926.json
  (старый helper добавляет дату20260926 к новому label; это не старый результат).
- Следующий шаг: новый полный повтор тех же20 offset0A prioritise,
  .runtime/system-20-localcontent-clinicalboundary-20261009.json.
  После internal20/20 обязательны independent structural/hash/identity audit
  и content review, включая517/734 и supporting/culture ложные основания.
  До этих проверок40 не запускать. Live backend не перезапускался.

## Новый отказ2124 — 2026-10-09,11:48–11:54

- Новый clinicalboundary20 завершён failed:8passed/1failed,9completed;
  runner14560 отсутствует. Отчёт и обе попытки сохранены.
  20373 в этой серии прошёл, прежний semester bug не повторился.
- 2124 обе попытки infeasible_with_complete_frontier:276 candidates,
  ON2 scored8/scoped8/admitted0. Отдельный read-only повтор воспроизвёл
  отказ; отчёт .runtime/diag-2124-localcontent-20261009.json.
- Полная ON2 цепочка в .runtime/diag-2124-localcontent-chains-20261009.json;
  missing-parent audit в .runtime/diag-2124-missing-parents-20261009.json.
  517→5029→3542+3667;734/742 наследуют эту цепочку. Курсы3542/3667
  «Иностранный язык (английский В1/B1)» имеют одинаковый уровень и почти
  одинаковое описание. Их EPVO scope не содержитB074/6B073, domain=it;
  уровень bachelor допустим, но нет MatchScore evidence в данном проекте.
  Прочие ON2 roots также имеют недопустимые родители. Это не timeout.
- Read-only сравнение с прежним prerequisite snapshot подтвердило:
  четыре ранее reviewed edges отсутствуют по-прежнему. В старом snapshot
  у517/5029 были только эти четыре связи; теперь присутствуют517→5029,
  5029→3542/3667. Точный момент записи новых edges не установлен;
  _assign_epvo_prerequisites может назначать двум ранним курсам связи
  по пересечению title tokens, без explicit EPVO подтверждения.
- Ruling: не удалять новые связи и не подменять их GOSO foreign-language
  эквивалентом. У GOSO нет подтверждения EnglishB1; языковые prerequisites
  могут быть содержательно оправданы, но AND двух одноуровневых копий
  требует предметного review. Из одного диагноза нельзя заключать,
  что оба требования ложные. Нужен согласованный review этих новых
  inferred edges/контракт эквивалентных prerequisite альтернатив с evidence.
  Product code в этой проверке не менялся. Новый массовый прогон не запускать
  до решения причины. Статус первых20 НЕ20/20;40 не разрешены.

## Футуристичная панель — 2026-10-10

- Согласованный ограниченный redesign BuildMapPanel: графитовый фон,
  статичное бирюзово-фиолетовое освещение, название программы, реальные
  счётчики. Существующая страница плана и источники событий сохранены.
- Переливы включаются отдельной галочкой, по умолчанию выключены.
  CSS transform/opacity действует только при running, видимой вкладке
  и панели в viewport. На mobile/reduced motion остаётся текстовый режим.
  Не изображаются несуществующие кандидаты или полный перебор комбинаций.
- TDD: тест статичного режима RED -> GREEN; тест остановки эффекта вне
  viewport и после completion RED -> GREEN. Frontend 31/31, build exit0.
- Авторизованная страница /projects/1603/plan проверена в браузере:
  desktop1440x900 и mobile390x844, document overflow=false, mobile motion
  disabled=true, Escape восстанавливает обычный режим. Mobile заголовок
  вынесен на полную строку после screenshot review.
- У старого плана1603 нет recorded job: показано честное пустое состояние.
  Живая анимация на реальном новом job и её overhead ещё не проверены;
  unit checks не заменяют эту приёмку. Новый массовый прогон не запущен:
  prerequisite review2124 по-прежнему не согласован, прежний report8/1
  сохранён. Для20→40 требуется сначала устранить эту причину.

## Реальный UI job и snapshot оценки — 2026-10-10

- Создан отдельный проект1632 из frozen10251, canonical input SHA256
  9ce08917f85642f258b9e9e23c5db4c1ad02538a40b36b3069e82fbf481f6a7d.
  Это UI контроль, НЕ замена и НЕ продолжение остановленной серии20.
  Старые проекты и prerequisite edges не изменялись этим контролем.
- Первый настоящий UI job завершён за109.8с. Повторы с кешем завершались
  за6.2–7.5с; это измерения этого проекта, не обещание общего ускорения.
- Выявлена гонка первого GET idle с POST build: polling прекращался до
  принятия команды. RED->GREEN regression usePlanBuildPolling: idle не
  завершает опрос, после202 статус принят и опрос восстановлен. Синхронный
  или ошибочный запрос останавливает polling в finally.
- Event stream state используется для переливов: событие running приходит
  раз в2с, резервный status poll раз в30с мог оставаться queued всю короткую
  генерацию. RED->GREEN component regression. В настоящем job наблюдались
  has-motion, animation=build-map-light-flow, opacity0.700673 и ненулевой
  transform; после complete animation=none. Карта показала120 кандидатов.
- Snapshot v1.4 канонизирует только course/bridge ID, semester, credits и
  prerequisites, а не служебные поля и порядок строк. RED->GREEN тест
  публикации; редактирование кредитов меняет hash. Старые оценки1.3
  остаются legitimately stale после обновления оценщика, не переименованы.
- API и persistent daemon обновлены только после проверки active jobs=0.
  Backend wrapper10152 actual17012 loopback8000; worker wrapper15872.
  Дефект первого открытия оценки был при обращении к заменённому plan_id
  до обновления variants резервным polling; повтор после обновления успешен.
  Оптимизация этого короткого окна и отдельный graph-overhead эксперимент
  ещё открыты, не заявлять полной пилотной приёмки.
- Последний plan4437 job build-8448be9ab7ec8ef4195cb13bc793384d: complete7.5с,
  244кредита, нагрузки33/31/33/28/30/30/31/28, independent issues[].
  Оценщик1.4 сохранён при публикации, stale=false, saved/current hash
  f072edb48678aacd02b79127d237cc247226c12a15c996c98583aa27fb43928e.
  Evidence .runtime/ui-lightflow-evidence-20261010.json.
- Содержание:50курсов,17needs_review,16supported professional,1possible
  duplicate group; core_definition_missing=true. Нулевой core_gaps при
  незаданном ядре НЕ доказывает его полноту. Известные ограничения
  supporting-role/culture generic terms/517vs734 остаются на review.
- Frontend33/33+build exit0, backend448/448 exit0 (14 content/API target),
  .runtime/content-v14-backend-20261010.log. Самопроверка, не внешний review.
  2124 всё ещё требует согласованного prerequisite review;40 не запускались.

## Содержательная точность v1.5 — 2026-10-10

- Реальные записи показали: language=ru означает язык преподавания, а не
  изучаемый язык. Копированное описание не доказывает одинаковое назначение
  курсов. Exact-content и embedding warnings теперь сохраняют различие
  распознанных изучаемых языков/категорий, уровней и языка преподавания.
  Это advisory фильтр, НЕ подтверждение эквивалентности и НЕ миграция связей.
- Языковые курсы, включая профессиональный казахский/русский и язык страны
  специализации, относятся к supporting вне языковой программы. «Язык
  искусства» не попадает в эту категорию. Неизвестные названия и назначения
  требуют предметной проверки; универсальная семантическая таксономия
  этим ограниченным исправлением не заявляется.
- Для культурологии общий семисимвольный stem «культур» в экологическом
  или антикоррупционном описании больше не даёт профильный бонус. Предметные
  культурологические основания учитывают конкретные фрагменты; профильное
  название вместе с содержательным описанием сохраняет положительную оценку.
- Пять новых регрессий: RED на языковых дублях, supporting role, общей
  «культуре», затем RED на «Языке искусства» и «Культуре Ренессанса» после
  проверки риска ложных отрицаний. Итог полный backend suite:453passed,
  exit0, имеющиеся dependency deprecation warnings сохранены.
- Read-only shadow comparison plan4437:50курсов; possible duplicate groups
  1→0; supported professional16→12; needs_review17→20. Изменились ecology,
  anti-corruption (три курса), «Модернизация общественного сознания» (review)
  и «Язык страны специализации» (supporting). Профильные «Культура Ренессанса»,
  «Массовая культура», «Медиакультура» сохранили положительную оценку.
  Старый persisted report1.4 и сам план не переписаны, подбор не повторялся.
- Код1.5 проверен локально; API/worker пока остаются1.4. Следующий шаг —
  расширить размеченный контроль содержания перед развёртыванием и новым
  сравнением подбора. Это не подтверждение качества всех программ.
- Серия20 по-прежнему остановлена на2124 (8passed/1failed/9completed);
  новые prerequisite edges без согласованного review не изменены.40 не
  запускались. Статья/start.ps1 не затрагивались.

## Расширенный контроль и развёртывание1.6 — 2026-10-10

- Read-only аудит11 сохранённых программ выявил ложный supporting у30200:
  `_language_purpose` распознавал «казах» внутри «Казахстана» и не отличал
  заметку о языке преподавания от языкового предмета. Четыре RED→GREEN
  регрессии закрывают этот случай, географическое упоминание, западные языки
  и кириллические CEFR уровни. Нормализуются только отдельные уровневые токены.
- Добавлены13 замороженных реальных course records с отдельной разметкой
  по исходным фрагментам, не по результату оценщика; это разметка ассистента,
  не независимая университетская экспертиза.15 acceptance checks офлайн.
- Итог backend472/472 exit0, dependency warnings остаются;
  `.runtime/content-v16-backend-20261010.log`. Self-review, subagent tool нет.
- Read-only11/11 в2.891с: `.runtime/local-content-shadow-v16-20261010-eleven.json`,
  canonical SHA2562cc37cb9abc94c75c2a19c583dde47682816175bfc5b2cb5a4f65999cb86618b,
  file SHA256cc8b60ad3977684e307a6aa03bb5897eb18681c0e82a2f1d3f2811a67f83ed5e.
  Fixture file SHA2563504afaeb00bace2e11f8bcdd35b7ff8d56b33b7067c1858a8b54b7fcb3e8b75.
  Подробности и реальные оставшиеся риски: docs/CONTENT_REVIEW_V16_20261010_RU.md.
- В1603 сохраняются5 металлургических mismatch. В1606/1607/1610 остаются
  возможные повторы; они требуют review, не автоматического удаления.
  В1602/1605/1607/1608 текущий граф даёт по2missing prerequisites для5029;
  это не доказывает момент записи и не переписывает результаты старого gate.
- Перед локальным обновлением подтверждено activejobs=0 и identities старых
  API/worker. Новый API wrapper408 actual2216 loopback8000, workerwrapper1892
  actual20816. Startup complete и реальный GET planner1632content-evaluation
  HTTP200; браузер показывает local-content-1.6,50courses20review12supported
  0duplicates, core_definition_missing. Старый report1.4 честно stale по версии,
  не сохранён поверх прежнего evidence. Сам план4437 не изменён.
- Screenshot `.runtime/content-ui-v16-20261010.jpg`. Frontend исходники
  в этом шаге не менялись. Генерации не запускались, потому что prerequisite
  review2124 остаётся несогласованным; не дублировать заведомо failing20.
- Следующий безопасный этап: UI окно старогоplan_id после publication и
  reconnect/overhead pilot; требования20→40 и предметного ядра ещё не приняты.

### 2026-10-10 — обновление UI после публикации результата

- RED→GREEN регрессии: завершение ждёт загрузки новых вариантов; поздний
  ответ остановленного опроса игнорируется; прежний complete job не завершает
  новую отправку; запоздавшие варианты не заменяют свежие. Оценка и выбор
  режима недоступны во время построения/применения изменений.
- Открытая карта после реального complete текущего job запускает немедленное
  обновление статуса. Проверяются version/job identity и одно уведомление на
  job. При закрытой карте прежний резервный опрос сохранён.
- Frontend: 39/39 tests, Vite build exit0; dist развёрнут в .runtime/dist.
  Backend в этом шаге не изменялся; его полный suite повторно не запускался.
- Один реальный UI контроль проекта1632, shadow, исходный frozen10251:
  job build-b9ab5d06d35f352595cd5fc46c9f46a5 complete за7.2с; новый plan4438.
  Во время работы оценка disabled с объяснением; после публикации GET оценки
  plan4438 HTTP200, local-content-1.6, stale=false. Старый plan_id4437 не
  использован для запроса оценки нового результата.
- 244 кредита; нагрузки33/31/33/28/30/30/31/28; independent structural issues[].
  50 дисциплин,12 supported,20 needs_review,0 duplicate_groups. При этом
  core_definition_missing=true: это НЕ подтверждение полноты ядра или
  академической пригодности. Один UI контроль НЕ заменяет серию20.
- Новое evidence: .runtime/ui-publication-refresh-evidence-20261010.json;
  сохранённый/current snapshot SHA256 одинаков:
  604d5150339006c67bd3f76bcec0c399c383d459bb7822933ed9effc0ec2ce2b.
  Screenshot: .runtime/ui-publication-refresh-20261010.jpg. Прежний UI evidence
  сохранён. Пререквизиты не менялись, failing20 не перезапускался.
- Открыто: предметный review2124, затем frozen20→40; измерение overhead карты,
  reconnect/cancel/retry/parallel/restart и isolated backup restore pilot.

### 2026-10-10 — восстановление карты и контракт опроса

- Добавлены8 characterization tests реального useBuildEvents с подменой только
  HTTP транспорта: все страницы terminal job дочитываются; reopening не
  дублирует события; поздний ответ другого job игнорируется; после transient
  error сохранён cursor и сброшена ошибка при восстановлении; hidden вкладка
  приостанавливает запросы; cancelled/failed/superseded прекращают опрос.
  Тесты сразу GREEN: это покрытие существующего поведения, НЕ новое исправление
  и НЕ заявленный RED→GREEN. Продуктовый код в этом шаге не менялся.
- Полный frontend47/47,13files; Vite build exit0. Backend не менялся.
- Реальный UI: закрыта и повторно открыта карта project1632 того же job
  build-b9ab5d06d35f352595cd5fc46c9f46a5; восстановлены этапы подбора, проверки и
  сохранения, без новой генерации. Screenshot .runtime/ui-map-reopen-20261010.jpg.
- Это подтверждает reopening завершённого job, но НЕ реальный offline retry,
  отмену работающего задания, parallel/restart или измерение overhead. Эти
  проверки и предметный prerequisite review2124 остаются открытыми.

### 2026-10-10 — isolated restore pilot запущен

- Проверено: Docker shadow healthy,896GB свободно; существующий dump2.3GB.
  SHA256 host и container совпадает с metadata:
  6269d88764e109572d6c9705b44852f568dde58cd9c9d6c5212d37c868f74aef.
- Единственный runner .runtime/restore-content-pilot-20261010.py, actualPID21472,
  StartTime2026-10-10 01:01:41 local; exec session75015. Ledger
  .runtime/restore-content-pilot-20261010.json state=restoring при запуске.
  Цель только curriculum_kag_restore_pilot_20261010, создана template0;
  createdb откажет при существующей цели, overwrite/drop не предусмотрены.
- pg_restore --exit-on-error --no-owner восстанавливает существующий снимок,
  рабочая curriculum_kag_shadow НЕ цель восстановления. После завершения
  runner проверяет courses/plans/items/prerequisites, orphan relations,
  invalid indexes/unvalidated constraints и migration. Пока завершение и
  проверки НЕ подтверждены. Не дублировать runner и не объявлять restore ready.
- Тестовую БД оставляем для проверки; никакие рабочие edges/планы не меняются.

### 2026-10-10 — restore завершён и стоимость чтения событий

- Exec75015 exit0, ledger state=passed, pg_restore exit0/stderr empty,
  elapsed439.05с. В isolated curriculum_kag_restore_pilot_20261010 восстановлены
  courses51047, plans111, plan_items4897, prerequisite_edges73662.
  Orphan plan items/prerequisites0, invalid indexes0, unvalidated constraints0;
  migration20260914_planner_build_drafts. Рабочая БД не была целью restore.
  Это восстановление содержимого снимка9октября, не сверка с изменившейся liveБД
  и не подтверждение содержательного качества восстановленных программ.
  TestDB сохранена, старые metadata dump не переписаны; evidence отдельный
  .runtime/restore-content-pilot-20261010.json. Не повторять restore.
- Read-only30 samples каждого сценария read_events+JSON на реальном job1632:
  reopening median5.329ms p956.507ms payload32149bytes9events;
  caught-up median2.434ms p953.057ms payload126bytes0events.
  Evidence .runtime/build-event-service-cost-20261010.json. Во время измерения
  шёл restore; это warm local service cost, НЕ HTTP/render latency и НЕ
  open-vs-closed generation overhead acceptance. Генерации не запускались.
- HTTP test fixtures уточнены по реальному schema sequence/job_id/timestamp;
  frontend47/47 повторно passed. Продуктовый код не менялся.
- Остаются real open/closed overhead и cancel/retry/parallel/restart проверки,
  предметный review2124 и содержательная frozen20→40 приемка.

### 2026-10-10 — три реальных контроля карты

- Созданы отдельные проекты1633/1634/1635 из одного неизменённого frozen10251.
  Input canonical SHA2569ce08917f85642f258b9e9e23c5db4c1ad02538a40b36b3069e82fbf481f6a7d.
  Shadow mode, A, последовательные реальные UI build; код не менялся.
  Это bounded pilot, не серия20, не статистический overhead experiment и не
  доказательство зафиксированного снимка всего каталога.
- Закрытая карта1633: jobbuild-bab265a7d77d7a9da3a5953602f62fa0,
  plan4439, complete63.2с. Статичная карта1634:
  jobbuild-f25ce5be90695784ad05c26dfd58072f, plan4440, complete44.3с.
  Переливы1635: jobbuild-7bb50a56c3c20c0b265f13993be03b9b,
  plan4441, complete39.8с. Каждая244credits и independent structural issues[].
- Открытые графы действительно были видимы: graph rect106–566 при viewport672.
  Static panel безhas-motion. Motion panel во время работыhas-motion,
  checkbox checked, hidden=false/reducedMotion=false. После complete класс
  has-motion снят автоматически, checkbox остался включённым. Screenshot
  .runtime/ui-map-overhead-motion-20261010.jpg показывает завершённый реальный
  граф120кандидатов и статусГотово, не анимированный placeholder.
- Content1.6 всех трёх stale=false, одинаковые saved/current snapshot hashes:
  57dc03bb5959d46cba57a3409a283f887001d98ac84b9ea7cce8ee8a349d4826.
  Каждый51courses10supported24needs_review0duplicates;
  core_definition_missing=true. Это НЕ предметная пригодность/полнота ядра.
- Evidence .runtime/map-overhead-pilot-results-20261010.json и
  .runtime/map-pilot-content-20261010.json. По1 наблюдению на режим, порядок и
  прогрев не сбалансированы: нельзя приписывать разницу скорости карте или
  объявлять количественный overhead доказанным. Повторять этиjobs не нужно.
- Открыто: строгий matched/repeated overhead experiment, реальные
  cancel/retry/parallel/restart, review2124 и содержательная frozen20→40 приемка.

### 2026-10-10 — реальная отмена и повтор из UI

- Только isolated1633, локальный cancel handler после require_version_access
  для владельца1; это НЕ HTTP middleware/кнопка отмены. Первый запрос пропустил
  короткое окно: job успел complete, отмена не выполнена. Старое evidence
  .runtime/cancel-pilot-20261010.json сохранено, этот запуск не назван cancelled.
- Во втором bounded pilot обработчик подготовлен ДО отправки job, ожидает
  новыйrunning/queued максимум45с, без повторной отмены. Job
  build-d559ea2f75ee9edbf9ab6c05ae35abef cancelled; plan4442 всё ещё active1
  и тот же SHA2561693dad16f96895247746e73135bb610097d2fbc865c4184c3884f01074ca1f3.
  Evidence .runtime/cancel-pilot-v2-20261010.json; ничего не удалялось вручную.
- Найдено: UI послеcancelled скрывал progress и не объяснял результат.
  Две RED regression→GREEN: отмена показывается как status без progressbar/
  обещания ожидания; RU/KK/EN label/detail. Frontend49/49, Vite build exit0,
  развёрнут .runtime/dist. Browser показывает «Построение отменено» и
  «Новый результат не опубликован. Можно повторить построение».
  Screenshot .runtime/ui-cancel-message-20261010.jpg. Backend не менялся.
- Повтор отправлен через обычную UIкнопку, НЕ endpointbuild-retry:
  новыйjobbuild-9faa4a0378dcb922088c386dbaaa0397 complete5.5с plan4443.
  244credits loads33/30/28/33/29/32/31/28; structuralissues[];
  content1.6stalefalse,51courses10supported24reviewcoreundefined.
  Evidence .runtime/cancel-retry-evidence-20261010.json. Durable job history
  сохранила cancelled/complete отдельно, у новогоcancel_requested0,
  program_spec_hash обоих совпал. .runtime/cancel-history-evidence-20261010.json.
- Отмена/повтор реального worker подтверждены в указанном scope. Отдельная
  UIкнопка отмены/HTTP cancel transport, parallel/restart, matched overhead,
  review2124 и frozen20→40 ещё НЕ завершены.

### 2026-10-10 — актуальность оценки после изменения кредита

- Owner-scoped _report на реальном isolated version1634/plan4440/item163897.
  До изменения5credits stalefalse. В транзакции5→4: staletrue, новый snapshot
  474a75553772d7300feef5cb529a4ba0db6d93521d98b5204eca0f6bff3cdcfd.
  Saved report и metrics не заменены. Обязательный rollback восстановил5 и
  hash57dc03bb5959d46cba57a3409a283f887001d98ac84b9ea7cce8ee8a349d4826;
  после rollback stalefalse. Никаких committed изменений плана/каталога.
- Evidence .runtime/content-manual-staleness-20261010.json; проверены реальные
  DB adapter и evaluator, НЕ HTTP/UI ручное редактирование. Прямого редактора
  кредитов на текущей странице не обнаружено. Не считать эту проверку выпуском
  редактора. Продуктовый код не менялся; suites в этом шаге не перезапускались.
- Общая приёмка остаётся открытой: новый review prerequisites2124, frozen20→40
  со structural/hash/content проверкой, matched repeated overhead и parallel/
  restart pilot; сетевой доступ с weak admin запрещён. Не называть advisory
  оценку предметной экспертной оценкой или готовностью к внедрению.

### 2026-10-10 — ownership/RBAC/auth границы ASGI

- Реальный составной planner.router, real live DB, TestClient без lifespan
  запуска нового сервера/worker. Только authenticated actor dependency
  заменена фикстурой: methodist ownerID1 против чужого methodistID987654321;
  записи пользователей/ролей не создавались, права не выдавались.
- GET status/events/content evaluation и POST cancel: owner200, foreign404
  во всех4 случаях. Foreign404 намеренно не раскрывает существование объекта.
  Owner cancel проверял terminal no-op, не отмену livejob. Status row/payload
  до/после одинаковы. Wrong job из project1635 при запросе project1634 вернул
  0events. Evidence .runtime/planner-access-pilot-20261010.json.
- Отдельный real auth dependency БЕЗ override и БЕЗ credentials: теже4маршрута
  вернули401. .runtime/planner-anonymous-pilot-20261010.json.
- Это ASGI route/dependency integration, НЕ входpassword/JWT, не сетевой
  transport и не UIкнопка отмены. Starlette/httpx deprecation warning отмечен;
  приложение/test dependencies в этом шаге не менялись. Новых генераций и
  изменений DB не выполнялось, продуктовый код не менялся.

### 2026-10-10 — два задания и свежий исполнитель в restored DB

- Только curriculum_kag_restore_pilot_20261010; проверен current_database().
  Из неизменённого frozen10251 созданы isolated test versions1612/1613;
  source canonical hash9ce08917f85642f258b9e9e23c5db4c1ad02538a40b36b3069e82fbf481f6a7d.
  Обаqueued202 до старта исполнителя. Producer13400 завершился;
  новый runner2880 StartTime10окт01:32:23 local, exec55348, прочёл durable jobs.
  Штатный _build_one и build_plan, но явно только эти2job: archived queued
  записи восстановленной БД не подбирались, live server/worker не остановлены.
- Первый запуск скрипта отказал ДО записи: конфигурация cwdroot выключала
  ASYNC. Scratch launcher исправлен на cwdbackend/.env; это ошибка запуска
  теста, не продуктовый regression/fix. Credentials/URL не выводились.
- exec55348exit0, ledger .runtime/isolated-queue-pilot-20261010.json passed:
  jobbuild-1e147768e57f9ba0c4c3c5835227d364 version1612plan4418 complete68.7с;
  jobbuild-893d9beb816e29f30bc88cee2a69934a version1613plan4419 complete41.2с.
  Оба244credits и independent structuralissues[]. Всего110.17с.
  First100 events каждого содержат только свойjob_id, запрос foreignjob
  в своейversion вернул0events. Это проверка указанных порций, не всех страниц.
- При свободных5.3GB использовано последовательное исполнение двух pending
  команд. Это НЕ два одновременно считающих worker/daemon SKIP_LOCKED stress,
  НЕ crash recovery mid-build и НЕ содержательная приёмка20. Новые rows/plans
  записаны только в восстановленную тестовую БД; продуктовый код не менялся.
- Далее: crash/lease recovery и реальная конкурентная обработка в изоляции,
  balanced repeated overhead; review2124 остаётся обязательным перед20→40.

### 2026-10-10 — аварийное завершение и lease recovery в restored DB

- Только curriculum_kag_restore_pilot_20261010, version1612; прежние live
  API/worker не перезапускались. Операционный lease20с задан только отдельным
  тестовым процессам, без изменения production policy или требований плана.
- Job build-2f8f412d2c50964f99d1106c45018c3a реально прерван os._exit(73)
  на variant_A_start, PID344. Прежний plan4418 и его snapshot сохранены
  при аварии и перед повторным захватом. Свежий daemon PID16328 восстановил
  ТОТ ЖЕ job после lease; exit0, final complete, recovery20.92с.
- Два distinct owner/attempt: ordinal1 по-прежнему записан running,
  ordinal2 complete. Успешный recovery НЕ означает, что историческая
  попытка корректно помечена abandoned: это отдельно открытая проверка
  представления истории. Evidence .runtime/crash-recovery-pilot-20261010.json.
- Read-only независимая проверка persisted plan4421:244credits,
  loads33/31/33/28/30/30/31/28,11prerequisite pairs, structuralissues[],
  exit0; SHA256 совпал с recovery ledger:
  02a9a7670986a89b0eb3c0b2b29bcf7386071b14017aa41f355d9789d16578e8.
  Evidence .runtime/crash-recovery-structural-20261010.json. Это не предметная
  экспертная пригодность и не новый successful frozen20.
- Продуктовый код не менялся, full suites повторно не запускались.
  Открыто: concurrent execution, balanced repeated overhead, history attempt
  presentation и предметный review2124 перед новым полным20→40.

### 2026-10-10 — закрытие аварийной attempt при повторном захвате

- Причина historical running: _record_job_transition создавал новую attempt,
  но не закрывал предыдущую после истечения lease. Терминальное завершение
  обновляло только текущего owner, поэтому старая attempt оставалась running.
- Regression на real SQLAlchemy SQLite: действующий lease не перехватывается
  чужим owner; после expiry тот же job получает нового owner и ordinal2;
  ordinal1 timed_out/failure_code lease_expired/finished_at/lease null;
  финальное завершение сохраняет историю [timed_out,complete]. Первоначально
  исправлена test fixture: same-owner reentry разрешён и не моделирует чужой
  процесс. Затем правильный RED: expected timed_out, actual running.
- Минимальный fix в planner_state._record_job_transition внутри существующего
  atomic claim; новые executions закрывают прежние running attempts того же
  job, сам job не становится timed_out и не теряет identity. Gates, кредиты,
  пререквизиты и publication не изменены, новых DB migrations нет.
- Target2/2 GREEN; full backend/tests exit0 (exec60919), без cacheprovider,
  fresh unique TEMP/TMP/basetemp. Deprecation warnings зависимостей сохранены.
  Старое crash evidence не переписано: оно относится к прежнему коду.
- Live API2216/worker20816 не перезапускались, поэтому live rollout и новый
  PostgreSQL crash recovery с исправлением ещё не подтверждены. Не исправлять
  старые исторические rows задним числом без отдельной migration policy.

### 2026-10-11 — независимая проверка нового recovery и граница нагрузки

- Предыдущее замечание о непроверенном PostgreSQL recovery выше относится к
  моменту записи, а не текущему результату. Новый isolated ledger
  `.runtime/crash-recovery-attemptfix-20261010.json` уже terminal passed.
- Read-only проверка `.runtime/check-crash-recovery-20261010.py` с
  `CRASH_PILOT_NAME=crash-recovery-attemptfix-20261010` завершилась exit0.
  Только БД `curriculum_kag_restore_pilot_20261010`, persisted plan4423:
  244 кредита, фактические нагрузки33/31/33/28/30/30/31/28;
  11 prerequisite pairs, structural_issues[].
  SHA256 f933a4f04128dd75315a65b6fdee7438f582f130b328d6f86ffc8cab4900d8e4
  совпал с recovery ledger. Попытки [timed_out,complete], первая
  failure_code=lease_expired; обе имеют finished_at и очищенный lease.
  Evidence `.runtime/crash-recovery-attemptfix-20261010-structural.json`.
  Старое evidence не переписано, live планы/история не менялись.
- На текущем ноутбуке свободно1551904KiB (~1.48GiB) физической памяти;
  python20348 занимает WorkingSet1655MiB. Это разовый снимок, НЕ измерение
  пика генерации и НЕ доказательство требуемой конфигурации сервера.
  Два новых тяжёлых worker сейчас не запущены: сначала требуется ресурсный
  бюджет/изолированный стенд, чтобы нагрузочная проверка не мешала live.
- Подтверждён источник риска: `_assign_epvo_prerequisites` выбирает до двух
  более ранних курсов по совпадению >=2 токенов названия в глобальном domain.
  Это не подтверждение реального AND-требования подготовки. Точное происхождение
  трёх конкретных новых edges пока не установлено; для изменения сохранённых
  языковых chains нужен предметный review, не молчаливое удаление.
- Frozen20 всё ещё не принят; 40 не запускались. Recovery-проверка не заменяет
  содержательную приёмку, throughput benchmark или проверку графа в браузере.

### 2026-10-11 — конкурентный захват одного задания без загрузки моделей

- В isolated restored DB четыре отдельных процесса одновременно вызвали
  штатный claim_build_status для одного нового scratch job версии1613.
  Ровно один admitted, остальные три получили отказ; одна execution attempt.
  После проверки job/attempt cancelled, прежний активный plan4419 сохранён.
- Evidence `.runtime/concurrent-claim-20261011-3efca0fc.json`, exit0.
  Время четырёх claim вызовов45.7–53.5мс, всего probe2.96с, без стоимости
  загрузки моделей/подбора. Это НЕ четыре одновременные генерации, НЕ
  пропускная способность генератора и НЕ проверка нескольких владельцев.
- Первый scratch запуск остановился на защитной проверке URL в дочерних
  процессах: они наследуют уже переключённый isolated DATABASE_URL.
  Исправлен только launcher, разрешены ровно live source и named isolated
  destination на5433; current_database по-прежнему обязан быть isolated.
  Созданный до отказа scratch queued job явно закрыт как cancelled при
  повторе, actual jobs/планы live DB не затронуты. Это не продуктовый defect.
- Код worker сейчас ограничивает число выбранных строк --max-jobs, но
  исполняет их последовательно в процессе. Значение2 само по себе не даёт
  двух параллельных генераций и не задаёт глобальный лимит исполнителей.

### 2026-10-11 — клавиатурный просмотр данных узлов карты

- Подтверждён пробел: Cytoscape tap показывал detail результата обучения,
  но text alternative содержала лишь названия курсов, без просмотра РО.
  Новый тест на реальном component/hook/graph builder воспроизвёл RED:
  отсутствует кнопка ON1. Axios замещает только HTTP источник событий.
- Text alternative теперь содержит нативные кнопки РО и курсов, Enter/Space
  открывают тот же inspected detail; результат объявляется через role=status.
  На desktop текстовый просмотр доступен в details вместе с графом. Палитра,
  реальный источник событий и существующие guards анимации сохранены.
- Полный frontend suite50/50 и Vite build exit0. Это component keyboard check,
  НЕ screen-reader/browser accessibility certificate. Fresh browser context
  направлен на login/session_expired; auth не обходили.
- Сборка создана в frontend/dist; live .runtime/dist НЕ обновлён этим шагом.
  Desktop/mobile visual pass нового состояния пока не выполнен.

### 2026-10-11 — расширенный read-only review цепочек2124

- Замыкание восьми ON2 кандидатов содержит44 курса; linked normalized
  EpvoPrerequisite provenance записей0. Найдены явно разнопредметные цепочки:
  английский→регулирование ЕАЭС/биотехнология растений, образовательные
  ресурсы→ремонт машин/1С/финансовое моделирование. Это требует review,
  не позволяет объявить все44 курса или все edges ошибочными.
- Описания двух B1 НЕ полностью идентичны, topics/learning_outcomes совпадают;
  эквивалентность не утверждена. Текущий title-token алгоритм не объясняет
  происхождение всех разнопредметных исторических связей.
- Evidence `.runtime/language-prerequisite-review-20261011.json`, read-only
  launcher exit0 после исправления печати detached ORM objects в scratch.
  Полный review/границы миграции `docs/PREREQUISITE_REVIEW_2124_20261011_RU.md`.
  Никаких edges/gates/курсов/планов не изменено. Data review ожидает согласования.

### 2026-10-11 — разрешённый review, ограниченный карантин и новый контроль2124

- Пользователь явно разрешил предметный review/обратимый карантин только
  доказанно ошибочных связей. По текстам734/742 не требуется517 как
  обязательная подготовка другого языка; скопированное описание не доказательство.
  Только (734,517),(742,517) перенесены в карантин:74162→74160 edges.
  Snapshot всех рёбер `.runtime/prerequisite-quarantine-language-20261011.json`,
  exact rollback `.runtime/quarantine-reviewed-language-20261011.py --restore`.
  Сохранены517→5029→3542/3667 и все остальные связи. Нет active queued/running
  build во время миграции; explicit EPVO relations0. Статья/чужойstart.ps1 не менялись.
- Предотвращение повторения: import compatibility hook больше не создаёт
  hard prerequisite по title-token overlap и не удаляет существующие связи
  через replace_existing. Никаких новых advisory proposals в нём не сохраняется;
  это прекращение недоказанной обязательности, НЕ готовый workflow предложений.
  Два RED теста: guessed edge1 вместо0; existing relationship удалена.
  После fix полный backend suite exit0 из repo root; dependency warnings остаются.
  Первая попытка suite из backend cwd ошиблась на import backend; это исправлено
  запуском из root, не правкой продуктовых импортов.
- Новый неизменённый frozen2124 prioritise контроль:
  `.runtime/diag-2124-reviewed-language-20261011.json`, terminal failed exit1,
 55.13с, infeasible_with_complete_frontier. ON2 теперь admitted2 (было0).
  Новый конкретный blocker ON13:scored1,scoped0,admitted0,max_scored0.5.
  Это частичное исправление, НЕ успешный2124; полный20 ещё не запущен.
- В контрольном процессе были CUDA OOM warnings, но он продолжил scoring и
  завершился штатным PlanningFailure, не native crash. Параллельный необязательный
  collect-only получил MemoryError в test_auth_transport.py; не повторять suite
  одновременно с загрузкой модели. Ранее полный suite уже завершился exit0.
- Пользователь уточнил новый внешний вид: полностью иная научная визуализация
  процесса, а не текущая карта с фоновыми переливами. До реализации требуется
  короткое согласование конкретной композиции; уже выполненные keyboard fixes
  не объявляются выполнением нового визуального требования.

### 2026-10-11 — подтверждённые EPVO aliases и аварийный контроль2124

- ON13 источника2124 связан с normalized1247; normalized1247 и162857
  подтверждённо указывают на локальный курс31302 (EPVO-162857).
  Старый scoring читал только запись из EPVO-кода, теряя исходную связь.
- TDD: SQLite регрессия вернула [] вместо кандидата31302 (RED). Исправлен
  единый bounded prefetch normalized aliases через canonical linked_course_id:
  канонический EPVO-код имеет приоритет при конфликте approved_course_id.
  Не используются fuzzy titles; курсы/описания/пороги не менялись. Сохраняется
  лимит32 links на normalized запись, кеш сигнала сбрасывается при prefetch,
  evidence содержит source_discipline_id. Второй тест защищает от переноса
  связи на чужой канонический курс. Target10/10, полный backend477passed,
  16dependency warnings,23.48с,exit0. Suite выполнялся отдельно от модели.
- Read-only live проверка `.runtime/check-approved-lo-alias-20261011.py`
  exit0: aliases[1247,162857], исходная ON13-связь1247/2124 даёт score1.0,
  кандидат31302 восстановлен. Evidence
  `.runtime/approved-lo-alias-live-20261011.json`. Это НЕ full generation
  acceptance, structural audit или содержательная экспертная оценка.
- Единственный новый frozen2124 prioritise контроль exec94585 создал
  temporaryproject/version1637, repositorycreated0/linked500, затем исчез
  после scoring1/20; report `.runtime/diag-2124-approved-lo-alias-20261011.json`
  отсутствует, exec terminalexit1. Windows Application event1000 в20:17:13
  (локальное время) зафиксировал python process0x2624, torch_cpu.dll,
  accessviolation0xc0000005; event1001 report
  cf12a5bf-37e8-4a5b-a03d-f389be2f0fb2. Точное внутреннее основание native
  crash пока не установлено; нельзя приписывать его MILP/gate или уверенно OOM.
  Процесс контроля отсутствует; автоматический дубль не запущен.
  Cleanup finally при native crash мог не исполниться: temporary1637 требует
  отдельной проверки. Старые планы и live API/worker не изменялись.
- Далее bounded диагностика PyTorch/runtime/ресурсных лимитов с фиксацией
  returncode/child identity; затем2124 и лишь при успехе все frozen20 заново.
  Массовые20/40 ещё НЕ разрешены результатом этого контроля. Новый дизайн
  «Лаборатория построения плана» предложен пользователю; композиция пока
  не согласована, редизайн продуктового UI в этом шаге не реализован.

### 2026-10-11 — bounded2124 прошёл; новая серия20

- Выявлено отличие от штатного cohort runner: прямой CLI контроль не задавал
  OMP/MKL/OPENBLAS/TORCH_NUM_THREADS=1 и TOKENIZERS_PARALLELISM=false.
  Повтор выполнен через существующий audit_quality_cohort.py, count1offset8A,
  unchanged frozen manifest и CONTENT_EVALUATION_MODE=prioritise; модели,
  их веса и gate не менялись. Это проверка гипотезы, не доказательство точной
  внутренней причины access violation и не полноценная защита от crash.
- `.runtime/diag-2124-threadbounded-20261011.json` statuspassed1/1exit0,
  одна child попытка,64.49с child/75.05с runner; credits244,hard0,ГОСОtrue,
  wrong_semester0/wrong_level0. Independent check_variant target240/8,
  load27–33:issues[]. Live процесс контроля завершён, не дублировать.
- Advisory evaluator из отчёта local-content-1.6:17supportedprofessional,
  profilemismatch0,coregaps0,needsreview24,duplicate_groups2. Предполагаемые
  пары734/742 и31308/31310 требуют отдельного content review; одинаковое
  описание НЕ подтверждает эквивалентность. Не объявлять качество окончательным.
- Запущена новая полная неизменённая серия первых20offset0A prioritise:
  `.runtime/system-20-approvedaliases-20261011.json`, timeout900,
  stop-on-failure. Штатный runner сохраняет identity/attempts/logs и ограничивает
  native потоки. Продуктовый код во время серии не менять. После internal20/20
  нужны independent identity/file+canonicalSHA/credits/load/prerequisites/required
  и честный content review; только затем разрешены40offset20.
  Concurrent users/throughput/cost и новый визуальный дизайн ещё не завершены.
- Новый runner identity PID17084/created_at1791732145.426 подтверждён живым
  процессом; exec87211. Попытка создать штатный heartbeat каждые30мин через
  automation_update завершилась MCP -32000; создание расписания не подтверждено.
  Не заявлять мониторинг включённым и не создавать дубли вслепую.

### 2026-10-11 — прерывание серии20 перезагрузкой Windows

- `.runtime/system-20-approvedaliases-20261011.json` успел завершить10251:
  passed,71.3с успешный child; две попытки, первая returncode3221225727
  (0xC00000FF), втораяexit0. Ограничение потоков НЕ доказано как достаточная
  защита от всех native отказов. Первый stderr содержит60с faulthandler
  snapshot, сам по себе не доказывает причину ошибки. Content indicators
  первого успешного плана:duplicates0,coregaps0,needsreview9.
- На следующем продолжении exec87211 стал недоступен. Проверены процессы:
  старый runner17084 и его child отсутствуют; иных cohort/audit генераций нет.
  OS LastBootUpTime11окт20:32:45, System6005 в20:33:12. Подтверждена
  перезагрузка, её причина не установлена. Не выдавать исчезновение runner
  за terminal PlanningFailure и не повторять живой процесс по stale-файлу.
- Штатным reconcile_running_report состояние устаревшего отчёта переведено
  изrunning вstale, completed1/reports1 сохранены. Повторную серию автоматически
  не запустили: после загрузки свободно426604KiB RAM, API/worker/frontend
  уже перезапущены автозапуском (actual23440/25196/24972 на момент проверки).
  Существующий API отвечает на8000, DBport5433 доступен. Это доступность,
  не подтверждение сохранности каждого пользовательского плана.
- Подготовлен `docs/CONTENT_PAIR_REVIEW_2124_20261011_RU.md`:734/742 возможные
  каталоговые версии,31308/31310 различное назначение с копированным описанием
  на трёх языках. Hard equivalence не утверждалась; каталог/план не менялись.
- Следующий шаг: восстановить достаточный измеренный ресурсный запас, проверить
  отсутствие активного job, затем новый полный20 с начала в новом отчёте.
  Не запускать heavy multiuser stress на0.4GiB freeRAM; чужие приложения
  автоматически не завершать.20→40/content acceptance/нагрузка/новый UI открыты.

### 2026-10-11 — четыре различных durable claims, без моделей

- При freeRAM766028KiB тяжёлая серия20 не возобновлялась. Выполнен bounded
  лёгкий PostgreSQL probe в curriculum_kag_restore_pilot_20261010, НЕliveDB:
  четыре разные версии одновременно queued→running через штатный claim.
  Evidence `.runtime/distinct-job-claims-20261011-a13daab4.json`, exit0:
  simultaneous_running_observed4, все scratchjobscancelled, все прежние
  planid/is_active сохранены. Это проверка admission, НЕ генерация нескольких
  пользователей, модельная нагрузка, throughput или cost benchmark.
- Практическая граница масштабирования: per-version ownership предотвращает
  дубли одного задания, но не ограничивает глобальное число разных running
  задач. --max-jobs ограничивает выборку отдельного worker, не все workers
  вместе. На текущем малом запасе RAM четыре heavy worker небезопасны;
  нужна отдельная подтверждённая политика общей ёмкости/ресурсного допуска.
- Две ранние попытки самого scratchprobe не засчитываются: coordinating
  thread cleanup не совпадал с owner context (stale updates были корректно
  отклонены), затем JSON writer получил SQLAlchemyRow вместо serializablelist.
  Исправлен только тестовый probe; чужие/пользовательские jobs не трогались.
  Наши оставшиеся scratchjobs с точным prefix/hash в isolatedDB завершены,
  успешная попытка проверилаterminalstates и сохранность всех планов.
  Частично написанный JSON предыдущей попытки не является evidence успеха.
- После probe freeRAM620016KiB. Автоматически завершать браузеры/чужие
  приложения или начинать memory stress нельзя. Ресурсный blocker остаётся;
  серия20stale, restart только с начала в новом report после восстановления
  измеренного запаса. Новый UI также ждёт согласования композиции.

### 2026-10-11 — продолжение: графический макет перед кодом

- Пользователь подтвердил продолжение. Предложенная «Лаборатория построения
  плана» и направление общего лимита одной тяжёлой генерации приняты для
  дальнейшей работы. Лимит пока не реализован: он должен охватывать scoring
  и planning, а не только отдельный worker claim.
- В отдельном ответе пользователь выбрал «Сначала графический макет».
  Подготавливаются три композиции одной панели; действующий интерфейс не
  изменён в этом шаге. PRODUCT.md фиксирует подтверждённые продуктовые
  ограничения, docs/BUILD_LAB_DIRECTION_20261011_RU.md — порядок реализации.
- Свежая проверка: FreePhysicalMemory3049344KiB, тяжёлых cohort/audit
  процессов нет. Это улучшение запаса, не измерение безопасной ёмкости
  модельной генерации. system-20-approvedaliases остаётся stale/completed1.
- Подготовительные две RED регрессии семестровой раскладки подтвердили,
  что нового представления ещё нет; после выбора макета вместо кода они
  отложены. Существующий тестовый файл возвращён к предыдущему состоянию,
  повторный тест BuildMapPanel:8/8 passed, exit0. Прочие пользовательские
  изменения сохранены. Приёмка новой панели и 20→40 остаются открытыми.

### 2026-10-12 — новый Build Laboratory и проверка всей цели

- Comp1 перенесён в живой UI: Exo2 self-hosted, граф actual nodes/edges,
  пунктирный gold selected path/cold neon, optional actual-edge trails,
  pending/verified check circles, published green nodes. Motion paused
  terminal/hidden/offscreen/reduced-motion/mobile, no fake MILPiterations.
- RED/GREEN и fullfrontend59passed+buildexit0; полный backend suiteexit0
  после правильного PYTHONPATH, opt-in2skipped. Fresh UI review: сначала4fixes,
  после batch все4resolved SHIP atfixscope. Desktop1586/mobile390/user871
  evidence `.impeccable/review/`. Не industrial acceptance.
- Actual project1603 A/B/C jobscomplete~8.11/7.42/8.15с, warmed same-input
  controls неthroughput/costbenchmark. Running scoring виден, но candidates
  появились с complete между polling2с: визуальное движение заполненных
  realpaths пока не засвидетельствовано. Не имитировать события.
- После контролей freeRAM5245616KiB, нет active recent userjobs/другого
  cohort. Новый full20offset0A prioritise с начала:
  `.runtime/system-20-labreview-20261012.json`, runner11744
  created_at1791755598.479, wrapper7820. Первый10251passed244hard0,
  completed1/20, второй в работе на момент проверки. Во время серии код
  не менять.20→40 только independent identities/hashes/credits/load/prereq/
  required и честный content review. Старый stale1/completed сохранён.
- Heartbeat `curriculum-kag-20-40` ACTIVE30мин подтверждён приложением.
  Остатки цели и source fingerprint: `docs/GOAL_VERIFICATION_20261012_RU.md`.
  Global capacity интегрирована частично со scoringAPI, не всеentrances;
  heavyconcurrent/RSS/throughput/cost/overhead остаются открытыми.
# 2026-10-12 — полный20 нового прогона

system-20-labreview-20261012.json terminalpassed20/20, runner11744 завершён. Независимый structural/identity/hash audit CLI exit0,acceptedtrue,findings[],distinct20/structural20. Не дублировать20. Содержательная приёмка ещё не завершена: см.CONTENT_REVIEW_LABRUN_20261012_RU.md. Не переходитьк40 по одному internal/structuralpassing. Globalheavycapacity/concurrency/стоимость и livefilledmotion остаются открытыми; цель не закрыта.
# 2026-10-13: резервный encoder — проверка честности

Три RED регрессии в test_embedding_device.py подтвердили: ошибка encode оставляла
маркировку SBERT, hash-вектор попадал в semantic cache, а batch смешивал старые
semantic и новые hash-векторы. Исправлено переключение actual model в fallback,
cache key после отказа и пересчёт всего batch. Все8 embedding tests GREEN;
полный backend pytest завершён exit0 (2 skipped, dependency deprecation warnings).
Затем RED→GREEN проверен LO-вектор, рассчитанный до отказа candidate batch:
scoring теперь кодирует обе стороны сравнения одним batch, включая одиночное
сравнение текстов. Все20 embedding/scoring frontier tests GREEN; полный backend
повторно exit0 (2 skipped). Изменение пока не развёрнуто в live; это не завершение
честного semantic/lexical coverage, description cache или содержательной приёмки.
