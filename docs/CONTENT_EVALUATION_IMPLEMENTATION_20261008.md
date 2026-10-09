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
