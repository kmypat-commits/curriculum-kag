# Аудит Curriculum-KAG перед чисткой и публикацией

Дата: 11 октября 2026, Asia/Qyzylorda. Проверенный commit: `81f10d7`.
Продуктовый код, данные, пароли и пререквизиты в рамках аудита не изменялись.
Удаление, публикация и новый массовый прогон не выполнялись.

## Вердикт

**Публичный production-выпуск пока не принимать.** Система пригодна для
ограниченного локального пилота с методистом и явно показанными предупреждениями.
Это не подтверждение профессиональной полноты всех программ и не обещание
100% успешной генерации. Объективно несовместимые требования должны приводить
к объяснимому отказу, а не к фиктивному успешному плану.

Главные приоритеты: происхождение/подтверждение пререквизитов, содержательная
приёмка на неизменных входах, безопасная release-конфигурация. Освобождение диска
не должно предшествовать сохранению доказательств и определению активных файлов.

## Свежие проверки

| Проверка | Фактический результат | Граница доказательства |
|---|---|---|
| Полный backend suite | exit0, 473 теста; collection отдельно подтвердила473 | Не заменяет реальный Docker/сетевой пилот |
| Frontend Vitest | 49/49,13 файлов | Не подтверждает полный browser workflow |
| Vite production build | exit0 | Собрано локально, не опубликовано |
| `pip check` | No broken requirements found | Текущий venv, не fresh Docker image |
| `npm audit --omit=dev --json` | 0 известных уязвимостей | Production npm dependencies; не полный pentest и не аудит Python CVE |
| Docker daemon | version29.7.2 доступна | Production stack не запускался |
| Локальный backend/frontend | HTTP health и страница доступны, процессы сменились с10октября | Версию Python-кода живого worker не выводить только из PID |
| Индекс сборки | SHA256 frontend/dist/index.html = .runtime/dist/index.html | Не сравнение всех assets, не proof backend release identity |
| Реальный crash recovery после fix | Ledger passed, попытки timed_out/complete, тот жеjob, старыйplan сохранён | Существующая изолированная PostgreSQL-проверка, не запуск во время аудита |
| Новая оценочная серия20 | terminalfailed:8passed/1failed/9completed,11не выполнены | Не20/20; предыдущие серии не заменяют её |

Backend проверялся с новым отдельным TEMP/TMP/basetemp и без pytest cacheprovider.
Остались deprecation warnings Starlette/httpx, anyio, utcnow и reportlab,
не скрытые test failures. Никаких автоматических dependency upgrades не было.

## Приоритетные замечания

### R01 — P0: новая серия20 не прошла, к40 переходить нельзя

Evidence: `.runtime/system-20-localcontent-clinicalboundary-20261009.json`.
Программа2124 отказала: восемь сильных кандидатов ON2 не допущены из-за
обязательных родителей. В цепочке517→5029→3542/3667 два EnglishB1 из другого
scope. Предметный review этих новых связей не согласован; даты их появления
по имеющимся материалам точно не установлены.

Действие: отдельная проверяемая таблица происхождения/содержательных оснований,
согласованное решение по связям, регрессия против их ошибочного восстановления.
Не удалять все языковые пререквизиты и не подменять подготовку курсом ГОСО
без доказательств. Затем2124 отдельно, все теже20 заново, independent
identity/file+canonical SHA256/credits/load/prerequisites/required и content
review; только после этого следующие40offset20.

### R02 — P0 для сетевого выпуска: слабая учётная запись администратора

Read-only проверка хеша подтвердила известный слабый локальный пароль.
Сам пароль/хеш/SECRET_KEY не сохранены в отчёте. Источник проверки:
`.runtime/release-state-audit-20261011.json`, auth.verify_password.
backend/.env настроен как local, cookieSecurefalse; это допустимо для локального
HTTP, но не конфигурация публичного HTTPS-приложения.

Действие: заменить пароль перед сетью, проверить пользователей/роли,
применить production validate_settings, HTTPS и cookie secure. Проверить реальный
вход и logout на домене. Во время аудита пароль не менялся.

### R03 — P1: эвристические связи становятся обязательными без достаточного provenance

`backend/app/services/epvo_repository.py:332`–`387`: подбор родителей по двум
общим токенам названия, прежнему семестру и глобальному domain, до двух родителей.
Это не обязательно подтверждённая зависимость содержания; рекомендательные
семестры/общие языковые слова сами по себе не доказывают prerequisite.
Вызов есть при repository approval (`backend/app/api/repository.py:417`).

Действие: разделить suggested и confirmed связи, фиксировать источник и review,
не допускать повторного auto-import reviewed/quarantined ошибки. Политику
миграции существующих связей утвердить отдельно. Исходный write-time конкретной
проблемной связи аудит не установил.

### R04 — P1: содержательная приёмка остаётся ограниченной

`backend/app/planner/content_evaluation.py:14,107–151,263–272`:
local-content1.6, положительные основания во многом лексические; отрицательная
проверка профиля ограничена известными случаями. `core_definition_missing`
честно сообщает отсутствие подтверждённых блоков, но не решает этот пробел.
`docs/CONTENT_REVIEW_V16_20261010_RU.md`: деревообработка1603 содержит пять
металлургических курсов в сохранённом плане; есть потенциальные повторы и
дисциплины с недостаточными описаниями.

Действие: предметная разметка на нескольких профилях и проверяемое ядро,
одинаковые входы/каталог для baseline-vs-prioritise. Не трактовать supported,
hard0 или отсутствие core_gaps как профессиональную пригодность. Сохранённые
старые планы не переписывать и сомнительные дубли не сливать автоматически.

### R05 — P1: release переключатели не переданы контейнерам

`backend/app/config.py:28–29` содержит CONTENT_EVALUATION_MODE и
BUILD_TELEMETRY_ENABLED; production Compose ни backend, ни worker их не передаёт.
Следовательно, значение в host .env.production само по себе не задаст режим
в контейнере; defaultshadow остаётся действующим. Это безопасный default,
но не доказательство выпуска согласованного prioritise режима.

Действие: единый явный контракт флагов API/worker, одинаковая модель и snapshot;
release manifest с commit/model/evaluator/config. Сначалаshadow staging,
проверка результата и только затем разрешённый prioritise. Не включать автоматически.

### R06 — P1: ещё не выполнен полноценный production rehearsal

`.env.production` отсутствует; имеется template. Есть Caddy, PostgreSQL,
отдельный worker, nginx unprivileged, hashed requirements lock и production
validators — хорошая база. Но этот аудит не собирал fresh Docker images,
не проходил миграции на fresh staging и не проверял настоящий HTTPS domain.
Последний runtime start отличается от записанных в старом ledger PID.

Действие: staging с отдельными данными, image build, migrations, authenticated
build/cancel/retry, concurrency/resource budget и restore. Публичный frontend
без доступного backend/worker/модели не считать готовой системой.

### R07 — P0 перед чисткой: старый manifest считает активный сайт удаляемым

`backend/scripts/build_disk_cleanup_manifest.py:37–40` помечает `.runtime/dist`
как delete_rebuildable. `frontend_server.py:13` обслуживает именно `.runtime/dist`.
Сам генератор manifest не удаляет, но слепое выполнение предложений сломает сайт.

Действие: проверка runtime consumers перед любой чисткой; защитить активную
сборку и worker heartbeat/PID. После переключения сервера можно удалить
предыдущие неподключённые сборки. Manifest — список предложений, не команда удаления.

### R08 — P1: нет безопасного единого правила хранения моделей/доказательств

`model-retention-policy.json` и `scripts/audit-model-retention.ps1` допускают
архивирование базовой модели; `build_disk_cleanup_manifest.py:12–16` считает
все три текущие модели нужными. Политики относятся к разным сценариям и не
должны исполняться как взаимозаменяемые. Рабочая модель и frozen research model
могут отличаться; выбор должен учитывать embeddings/model compatibility.

Действие: live/production/reproducibility/archive категории, SHA256 manifest,
проверка загрузки выбранной модели; на удаление только после проверенного
внешнего архива. Нельзя освобождать все12.2GiB моделей как будто это cache.

### R09 — P2: рост каталога требует отдельной атрибуции

Текущая read-only БД:51769courses,115plans,5100plan_items,143durablejobs.
Это на722курса больше51047 в прежнем restore snapshot. Снимки разных дат:
разница сама по себе НЕ доказывает, что каждая генерация создаёт курсы, и не
доказывает линейное замедление. Новых queued/running в status rows нет.

Действие: provenance/course_id/source breakdown и замер count до/после одного
контрольного запроса; дедупликация реальной идентичности, а не названий/описаний
вслепую. Не удалять ГОСО/варианты языков и уровней ради уменьшения счётчика.

### R10 — P2: свежая полная UI-проверка ограничена авторизацией

В отдельной browser-сессии /projects/1634/plan перенаправил на
/login?reason=session_expired. Auth не обходился. На login1280×900 и390×844
document.scrollWidth равен viewport, labels присутствуют; language buttons
наmobile32–33×36px, submit44px высотой. Это не нарушение правила24px само
по себе, но размер меньше удобного44px целевого размера.

BuildMapPanel.jsx:31,43: инспекция узла через tap в canvasroleimg; имеется
отключаемый граф и текстовый список. Эквивалентность подробного inspection для
клавиатуры ещё нужно проверить. Expanded Escape реализован, полный keyboard/
focus pass и свежий authenticated axe/contrast pass здесь не подтверждены.

Действие: одна bounded desktop/mobile/keyboard/reduced-motion проверка после
входа, текстовый эквивалент значимых подробностей; не тратить время на бесконечную
полировку. Команды Impeccable: harden/adapt, затем polish после исправлений.

## UI-аудит Impeccable

Оценки предварительные, code-level + свежий login pass, **не WCAG-сертификат**
и не процент готовности продукта. Authenticated plan визуально не проверялся заново.

| Измерение | Предварительно /4 | Основание/ограничение |
|---|---:|---|
| Accessibility |2|Labels/text fallback/reducedmotion есть; node inspection/focus требует проверки|
| Performance |3|Lazy Cytoscape,nodecap150, pause hidden; matched repeated overhead не закрыт|
| Responsive |3|Mobile text fallback в коде, login безoverflow; свежий plan pass отсутствует|
| Theming |2|Map локальные tokens + много hardcoded цветов; полный theme audit отсутствует|
| Integrity |3|Реальные job events и честная публикация; новые content gates ещё не приняты|
| Всего |13/20|Ограниченный аудит реализации, не оценка содержания программ|

Detector проверен на BuildMapPanel.jsx/.css, ContentEvaluationPanel.jsx,
useBuildEvents.js. Единственное замечание — advisory grid-line background,
BuildMapPanel.css:23. В данном случае это настоящая карта/canvas и согласованный
футуристичный стиль; **не подтверждённый дефект**, удалять фон из-за detector не нужно.
У detector был exit1; JSON не содержит blocking finding. Не приписывать ему
WCAG/контраст/безопасность, которых он здесь не измерял.

## Инвентаризация и безопасная чистка

Evidence: `.runtime/file-inventory-audit-20261011.json`. Рекурсивный read-only
scan указанных папок; это не весь диск. 14 ошибок чтения в.runtime и2вtmp,
поэтому размеры нижняя граница. Права не обходились и не изменялись.

| Папка | Файлов | GiB | Решение |
|---|---:|---:|---|
|.runtime|32798|18.408|Разделить active/evidence/backups/cache; не удалять целиком|
|backend/models|97|12.211|Сохранить выбранные и воспроизводимые модели; остальные только поmanifest|
|docs|178|0.035|Сохранить актуальные отчёты/дизайн; исторические сгруппировать, не массово удалять|
|output|35|0.003|Проверить назначения; ещё не разрешено удаление|
|tmp|18|0.002|Кандидаты после проверки handles и непрочитанных папок|
|frontend/dist|23|0.001|Пересобираемо, но проверить deployment consumer|
|visualizations|259|<0.001|Сохранить QA evidence, временные pytest cases — кандидаты|

Главные большие файлы: SQLite acceptance snapshot12,298,555,392bytes;
course_lo_pairs.jsonl3,633,925,660bytes; PostgreSQL backup2,356,558,525bytes.
**Это не список мусора.** Snapshot/backup/experiment file архивировать с hash,
проверкой восстановления/чтения, затем отдельно разрешать удаление локальной копии.

Защитить: `.git`, start.ps1 с чужими изменениями, `.env`, текущую PostgreSQL,
uploads, активный.runtime/dist, frozen manifest и JSON inputs вне repo
(`D:\curriculum-kag\output\tem-revision-20260922\real-cohort-inputs-v2`),
review/quarantine snapshots, backup dump+metadata, обязательные model files,
оригиналы статей и Figures. Git содержит707trackedfiles; поиск отслеживаемых
env/dump/db/log не показал заполненные.env, дампы или БД (env templates и
скрипты миграций не являются утечками сами по себе).

## Следующие этапы — с проверкой после каждого

1. Зафиксировать защищённые пути и новый dry-run cleanup manifest; отдельно
   согласовать review2124 и список необходимых data corrections.
2. Исправить приоритетные системные причины, пройти неизменные20→40 и
   содержательную проверку. Сохранить всю историю прежних неудачных прогонов.
3. Архивировать тяжёлые эксперименты/снимки, проверить hash+restore; удалить
   только согласованные rebuildable/архивированные файлы, не активные consumers.
4. Production config/model/feature flags/credentials; fresh staging build и
   миграции, UI/access/worker/backup rehearsal. Выбрать домен/сервер/бюджет.
5. Только после этой приёмки выкладывать pilot на HTTPS-сайт. Отдельно
   различать техническую доступность, хороший draft и одобрение методиста.

Новые навыки скачивать не потребовалось. Skill Router + Impeccable audit
использованы; технические результаты проверены текущими файлами и командами.
Это аудит готовности и эксплуатационных настроек, не полный pentest.
