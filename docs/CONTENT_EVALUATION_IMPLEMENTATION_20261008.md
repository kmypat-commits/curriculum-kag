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
