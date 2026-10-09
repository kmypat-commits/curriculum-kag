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
