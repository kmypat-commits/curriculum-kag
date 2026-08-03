# Аудит Curriculum-KAG и задание для реализации (handoff в Codex)

### Проверка core API после стабилизации (2026-08-03)

- Добавлен read-only smoke-тест `backend/scripts/smoke_core_api.py`. Без указания версии он получает список проектов и безопасно разрешает `latest_version` через detail API, поэтому не зависит от облегчённого ответа списка.
- Проверены критические endpoints на рабочем PostgreSQL backend: `variants` — HTTP 200, `graph` — HTTP 200, `lo-achievability` — HTTP 200. Пустых ответов нет.
- Регрессия backend: **38/38 PASS**, UTF-8 gate чист.
- SHA-256 шаблона в проекте совпадает с переданным DOCX-шаблоном TEM Journal: `0DBA4319D7022C0057B3995ACE894EA55AE40C1D2F4515D5954E936A606DE3B2`.
- Контрольный API-аудит трёх уровней (проекты 15/14/19: бакалавриат/магистратура/докторантура) прошёл: 9 вариантов A/B/C, без дублей, жёстких нарушений, неподходящего уровня и пропусков реальных LO-источников. Подробно: `docs/CONTROL_AUDIT_2026_08_03_RU.md`.

- Дата анализа: 2026-08-01
- Автор анализа: opencode (только чтение, код не изменялся)
- Репозиторий: `D:\curriculum-kag\curriculum-kag`, ветка `master`, рабочее дерево чистое
- Цель: передать Codex точный список дефектов, решений и проверок, чтобы ничего «не поплыло»

---

## 1. Что уже проверено и работает (green gate)

### Дополнение 2026-08-02

- В PostgreSQL восстановлены RU/KK/EN локализации дисциплин из нормализованного и сырого слоя ЕПВО; 26\,696 дисциплин имеют все три языка, повреждённых значений — 0.
- Повторный repair-проход 2026-08-02 обработал 1\,339 нормализованных строк: обновил 926 полей normalized и 119 локализаций из raw EPVO; verified-тексты не перезаписывались.
- Translation quality score: 1,0000; для 6 карточек, где raw EPVO содержал только RU-описание, добавлены машинные KK/EN-черновики со статусом `needs_review` — они не считаются экспертно подтверждёнными.
- Проверены и включены в единый аудит 125 направлений и 483 групп ОП: пропусков и повреждённых переводов нет.
- API `/api/epvo/directions` возвращает локализованные названия для `ru`, `kk` и `en`; пример `6B011`: «Педагогика и психология», «Педагогика және психология», «Pedagogy and Psychology».
- Acceptance после восстановления: backend 33/33, PostgreSQL smoke, контрольные A/B/C 6/6 и frontend production build — успешно.
- Повторяемые инструменты: `backend/scripts/repair_epvo_localizations.py` и расширенный `backend/scripts/audit_course_localizations.py`.

| Проверка | Результат |
|---|---|
| Юнит-тесты `run_tests.py` | 33/33 PASS (плюс 2 файла: `test_curriculum_kag.py`, `test_goso_components.py`) |
| Проверка кодировки `check_text_encoding.py` | UTF-8 чист, exit 0 |
| Компиляция всего Python (`py_compile`, 130 файлов) | 0 ошибок |
| Git | `master`, чисто, последний коммит `b056e47` |
| Frontend production-сборка | готова, 1452 файла в `.runtime/dist` |
| Бэкап PostgreSQL | дамп 2.26 GB (2026-07-29), SHA-256 `dd759571…`, restore-verification `passed=true`, счётчики 14 таблиц совпали |
| Сверка SQLite↔PostgreSQL (19 таблиц) | `passed=true` (2026-07-25) |
| Генерация A/B/C свежих программ | бакалавр/магистр/доктор/ICT+medicine — все варианты 240/120/180 кредитов, hard_violations 0, international_score 100 (после фиксов 30.07) |
| Продакшн-модель | `epvo-sbert-finetuned-40k` (ROC-AUC 0.7666, PR-AUC 0.7681, F1 0.7188), порог `0.344931` согласован config + .env |

---

## 2. КРИТИЧЕСКИЕ проблемы (решать в первую очередь)

### 2.1 Единый локальный PostgreSQL-режим зафиксирован
- Оба локальных `.env` теперь указывают на заполненную и проверенную базу `localhost:5433/curriculum_kag_shadow`.
- `start.ps1` для `-Database postgres` и `postgres-shadow` также использует 5433 (`start.ps1:269-277`).
- Пустая база на 5432 не используется приложением; данные не удалялись и не перезаписывались.
- Для запуска с актуальным EPVO: `.\start.ps1 -Database postgres`.

### 2.2 PostgreSQL/Docker сейчас выключен; auto-режим тихо падает в SQLite
- Порты 5432/5433 не слушают, docker daemon не запущен (`docker version` → connection error).
- `start.ps1 -Database auto` (по умолчанию): пытается поднять shadow, не может → проверяет 5433 → нет → берёт `.env` (5432) → проверяет 5432 → нет → **молча ставит** `DATABASE_URL=sqlite:///backend/curriculum_kag.db` (`start.ps1:300-313`).
- SQLite-база `backend/curriculum_kag.db` (11.45 GB, последняя запись **2026-07-26**) **старше PostgreSQL на 3 дня**: проектов 5→6, дисциплин 20782→21525, локализаций 62346→64575, план-итемов 864→709.
- С `ENABLE_SBERT=true` и `EPVO_AI_ENABLED=true` SBERT будет работать против SQLite через numpy-cosine fallback (`app/kag/retrieval.py:46-146`) — работает, но медленно.

**Решение:** на период работы с актуальными данными поднять Docker и использовать `start.ps1 -Database postgres` (5433 shadow). Если нужен лёгкий режим — осознанно использовать SQLite и помнить об устаревании.

### 2.3 NSGA-II фактически отключён для всех реальных программ (расхождение с тезисом)
- `backend/app/planner/scheduler.py:4881`:
  ```python
  if interdisciplinary or epvo_professional_scope:
      db.info[optimizer_cache_key] = {}
  ```
- `epvo_professional_scope` истинно для **любой** ОП с заданной группой/направлением ЕПВО (`scheduler.py:4083-4087`) — т.е. для всех реальных программ NSGA-II не запускается, используется детерминированный путь.
- Метрики честно сообщают это: `calculate_plan_metrics` (`scheduler.py:6380-6385`) → `optimizer.name = "Deterministic bridge heuristic"`.
- **Расхождение с тезисом:** `THESIS_ALIGNMENT_CURRENT_RU.md` заявляет «NSGA-II: популяция 100, 200 поколений» как применяемый оптимизатор. Конфиг теперь `NSGA2_POPULATION=36`, `NSGA2_GENERATIONS=50` (`app/config.py:45-46`).
- Примечание: `plan-dry-run-v13-abc-nsga2-36x50` профилировал настройки NSGA-II, но контрольная программа EPVO-scoped идёт через детерминированный путь — то есть профилирование измеряло практически неиспользуемую ветку.

**Решение/выбор:**
- (A) Обновить тезис: «детерминированный эвристический планировщик + NSGA-II как экспериментальная ветка для каталогов без явного EPVO-скоупа»; либо
- (B) Вернуть NSGA-II в рабочий контур для scoped-программ и доказать улучшение метрик (потребует регрессии на 4 контрольных проектах).

### 2.4 Приёмочный шлюз сейчас RED (последние прогоны)
- `full-acceptance` 2026-07-29 22:46: `status=failed`, ошибка «Fresh interdisciplinary ICT + medicine A/B/C generation failed with exit code 1».
- Последующие отдельные прогоны (30.07 00:23–00:32) прошли (ICT+medicine passed=true).
- Финальный `standard-final-acceptance` 30.07 00:37: все генерации прошли, но `status=failed` из-за **vite build**:
  > The CJS build of Vite's Node API is deprecated … (воспринимается как exit 1).

**Решение:** исправить frontend build, чтобы warning не ронял exit-код (обновить `vite.config`/Vite-версию или не трактовать warning как error), затем прогнать полную приёмку: `.\acceptance-test.ps1` (и с `-IncludeFreshGeneration`).

### 2.5 Схема БД не мигрируется (нет Alembic-версий)
- `backend/migrations/` содержит только `env.py` и `script.py.mako` — **папки `versions/` нет**.
- Схема создаётся при старте: `Base.metadata.create_all` (`app/main.py:28`) — не идемпотентна для изменения колонок, опасна при совместной работе.
- Alembic установлен в `requirements.txt`, но не используется.

**Решение:** начать Alembic с первого коммита-слепка текущей схемы (`alembic revision --autogenerate` против SQLite), затем все изменения схемы — через миграции. Для одно-пользовательской НИР это допустимо отложить, но задокументировать.

### 2.6 `requirements.txt` (Docker) устарел и расходится с `requirements-local.txt`
| Пакет | `requirements.txt` | `requirements-local.txt` (реально используется) |
|---|---|---|
| sentence-transformers | 2.3.1 | 5.6.0 |
| torch | 2.1.2 | 2.12.1 |
| transformers | 4.37.0 | 5.12.1 |
| numpy | 1.26.3 | 1.26.4 |
| scipy | — | 1.12.0 |
| faiss-cpu | 1.7.4 | нет |
| alembic/pytest/reportlab | есть | нет |

`backend/Dockerfile` ставит именно `requirements.txt` → docker-образ соберётся со старыми версиями и может не соответствовать локальным результатам.

**Решение:** синхронизировать два файла (единый источник или явно пометить `requirements.txt` как неактуальный), проверить docker-сборку.

### 2.7 Разброс версий Python
- `backend/Dockerfile` → `python:3.11-slim`
- `backend/venv` → Python 3.12.0
- codex-runtime (тест/запуск в `test.ps1`) → Python 3.14 (в `migrations/__pycache__/env.cpython-314.pyc`)
- `app/main.py:7-19` содержит monkeypatch bcrypt «для Python 3.14»

**Решение:** зафиксировать одну целевую версию (рекомендуется 3.12) и обновить `Dockerfile`, `test.ps1`, документацию.

---

## 3. Средние проблемы

### 3.1 DEBUG-вывод в авторизации
`backend/app/api/auth.py:36,40,48` — `print(f"DEBUG: Login attempt for: {form_data.username}")` и др. Логирует имена пользователей при каждом входе.
**Решение:** удалить 3 строки.

### 3.2 Frontend: код языка `'kz'` вместо `'kk'`
`LanguageContext.jsx:8` хранит `'kk'`. Проверки `language === 'kz'` в:
- `frontend/src/pages/Dashboard.jsx:47`
- `frontend/src/pages/ProjectWizard.jsx:12`
- `frontend/src/pages/LOCoverageDashboard.jsx:394,398,401`

Казахские ветки никогда не выполняются (в LOCoverageDashboard другие ветки файла уже корректно используют `'kk'`, см. 246/250/335).
**Решение:** заменить `'kz'` → `'kk'`.

### 3.3 Frontend: мёртвая ветка ошибки логина
`Login.jsx:26` сравнивает сообщение с `'Incorrect email or password'`, а бэкенд возвращает русское «Неверный адрес электронной почты или пароль» (`api/auth.py:43,53`).
**Решение:** проверять по `status === 401` или `String(message).includes('Неверный')`.

### 3.4 Frontend: баннер «Прогноз ИИ» почти невидим
`LOCoverageDashboard.jsx:390` — условие `prediction.source === 'epvo_sbert_ai'`, но при существующем плане `api/kag.py:123` отдаёт `"source": "stored_plan_metrics"`.
**Решение:** расширить условие на `stored_plan_metrics` (со значением в payload) или убрать баннер.

### 3.5 Frontend: непереведённые `alert()` и хардкод
- `LOCoverageDashboard.jsx:188` — `alert(t('Bridge module ID not found. Please regenerate.'))`: английская строка передана как ключ, такого ключа нет.
- `LOCoverageDashboard.jsx:109` — `alert('Error saving weights')`.
- `Repository.jsx:101,106,142,210,212,227,231` — `alert()` английскими строками.
- `PlanBuilder.jsx:340` — критические ошибки построения через браузерный `alert`.
- `Dashboard.jsx:59` — «Версии» хардкод (рядом «Репозиторий» через `t()`).
- `GitVersions.jsx` — весь UI хардкод RU, `useLanguage` не используется.
- `PrerequisiteGraph.jsx:249,252` — для `kk` возвращается русский текст.

### 3.6 Frontend: JWT в `localStorage`
`AuthContext.jsx:12` — токен в `localStorage` (риск XSS). **Решение:** рассмотреть `sessionStorage` или HttpOnly cookie.

### 3.7 Кэш стадий планировщика не замечает in-place update/delete
`backend/app/services/planner_stage_cache.py:53-56` — `_table_stamp` = `max(id)` таблицы. Если сырые EPVO-данные **обновляются на месте или удаляются** (без новых id), сигнатура не меняется → устаревший кэш `cache_epvo_repository`/`cache_course_lo_matches` будет отдаваться.
**Решение:** добавить в подпись `count(*)` + `max(updated_at)` для мутируемых таблиц, или версионировать кэш вручную после repair-скриптов.

### 3.8 Переезд локализаций на PostgreSQL неполный
`backend/app/services/content_localization.py`:
- `course_translations()` читает `backend/data/course_translations.json` (58 MB) через `lru_cache` — грузится в память.
- `course_localization_payload()`/`course_localization_map()` предпочитают таблицу `course_localizations`, но при нехватке строк падают на JSON.
- В `scoring.py` `_course_match_text` и `_lightweight_candidate_courses` JSON используется как fallback.
**Решение:** после полного переезда на PG переключить `course_translations()` на чтение из БД и удалить legacy-JSON (или явно задокументировать fallback).

### 3.9 0-byte `curriculum_kag.db` в корне проекта
Пустой файл `D:\curriculum-kag\curriculum-kag\curriculum_kag.db` (0 байт, 17.07). Если uvicorn запустить из корня (а не из `backend/`, как делает `start.ps1:331` с `-WorkingDirectory $backendDir`), `sqlite:///./curriculum_kag.db` откроет пустую БД.
**Решение:** удалить файл.

### 3.10 Устаревшие seed-скрипты
`backend/seed_db.py`, `seed_investigator.py`, `seed_massive_210.py`, `seed_massive_210_en.py`, `init_db_data.py` — ранние артефакты; вызываются только из `backend/scripts/create_restore_backup.py` (резервирование, не запуск). Риск: случайный запуск создаст старые/мусорные проекты.
**Решение:** либо удалить, либо вынести в `backend/scripts/legacy/` и пометить «не запускать».

---

## 4. Мелкие находки
- `last-build-check.json` (07-06) содержит `selection_method=nsga2` — устаревший артефакт до отключения NSGA-II; сейчас новые планы идут через детерминированный путь. Очистить/не использовать для метрик.
- Frontend: `.bak*`-копии `PlanBuilder.jsx.bak2/.bak4/.bak5/.bak_final` в `pages/` — удалить из репозитория.
- Документы с датами 01–06.07 (`THESIS_ALIGNMENT_RU.md`) устарели относительно `THESIS_ALIGNMENT_CURRENT_RU.md` (19.07). Обновить/объединить.
- Git remote не настроен (`git remote -v` пуст) — передача Codex идёт через локальную файловую систему, а не push/pull.

---

## 5. Порядок работ для Codex (по приоритету)

1. **БД и запуск**: решить 5432 vs 5433 (§2.1), поднять Docker + shadow, зафиксировать рабочий `start.ps1 -Database postgres`. Проверить `/health` → `database: postgresql`.
2. **Приёмочный шлюз**: исправить vite build (exit 1 на warning) → `.\acceptance-test.ps1 -IncludeFreshGeneration` → зелёный (§2.4).
3. **Тезис ↔ код по NSGA-II**: зафиксировать решение (§2.3) и обновить `THESIS_ALIGNMENT_CURRENT_RU.md`.
4. **Чистка кода**: убрать debug-print в `auth.py`, удалить 0-byte `curriculum_kag.db`, починить `'kz'→'kk'`, `Login.jsx:26`, alert-ы, JWT-хранение (§3.1–3.6).
5. **Зависимости**: синхронизировать `requirements*.txt`, зафиксировать версию Python (§2.6, §2.7).
6. **Инфраструктура схемы**: начать Alembic (или явно отложить с заметкой) (§2.5).
7. **Кэш и локализации**: укрепить сигнатуру кэша, завершить переезд локализаций на PG (§3.7, §3.8).
8. **Гигиена репозитория**: удалить seed-артефакты, `.bak*`, обновить устаревшие доки (§3.10, §4).

Каждый шаг завершать: `.\test.ps1` (33/33) + `.\check_text_encoding.py` + компиляция. После любого изменения схемы — сверка счётчиков SQLite↔PG.

---

## 6. Чек-лист приёмки (read-only, воспроизводимо)
- [ ] `.\test.ps1` → 33/33 PASS, кодировка чистая
- [ ] `.\start.ps1 -Database postgres` с Docker → `http://127.0.0.1:8000/health` → `database: postgresql`
- [ ] `.\acceptance-test.ps1 -RequireVerifiedBackup` → зелёный
- [ ] `.\acceptance-test.ps1 -RequireVerifiedBackup -IncludeFreshGeneration` → зелёный (бакалавр/магистр/доктор/ICT+medicine)
- [ ] `python backend\scripts\prepare_postgres_cutover.py --output .runtime\postgres-cutover-readiness.json` → `ready_for_cutover: true`
- [ ] `.\backup-postgres.ps1` + `.\verify-postgres-restore.ps1` → `restore_verified: true`
- [ ] Сверка `sqlite-postgres-counts-valid.json` после любых миграций данных

---

## 7. Приложение: подтверждённые факты окружения
- Настоящая SQLite-база: `backend/curriculum_kag.db` (11.45 GB, WAL, обновлена 26.07).
- Резервные SQLite-базы: `backups/baseline-*` (377 MB … 11.7 GB) с манифестами.
- Postgres-дамп: `backups/postgres/curriculum_kag_postgres_2026-07-29_16-55-40.dump` (2.26 GB), SHA-256 `dd7595714f29921029adf068d0101d4deedb41721446a5bb150042a62cf305a4`, restore verified 2026-07-29T12:36:34Z.
- SBERT-модели и датасеты (`backend/models/`, `backend/experiment-results/`) в gitignore — не в git.
- `.env` файлы (корень и `backend/`) не в git (в gitignore), содержат реальный `DATABASE_URL`, `ENABLE_SBERT=true`, `EPVO_AI_ENABLED=true`, `EPVO_AI_THRESHOLD=0.3449310730397701`.
- 2026-08-01: граф пререквизитов получил резервную раскладку Cytoscape `breadthfirst`: если необязательный chunk `cytoscape-dagre` не загрузился, граф всё равно отображается.
- 2026-08-01: мастер создания программы использует `POST /projects/suggestions` для локализованных заготовок цели и LO. Это детерминированный API-шаблон (`ai_generated=false`), поэтому отсутствие внешней LLM не блокирует мастер; позже его можно заменить проверенным провайдером.
- 2026-08-01: частичная генерация вариантов A/B/C сохраняет уже существующие варианты; в Plan Builder доступна кнопка построения только отсутствующих вариантов.
- 2026-08-01: циклы дисциплин локализуются централизованно (БД — базовые дисциплины, ПД — профильные, ООД — общеобразовательные, КВ/ВК — компоненты выбора и вуза).
- 2026-08-01: репозиторий поддерживает ручное редактирование title/description на RU, KK и EN через CourseLocalization. Записи без подтверждённого перевода получают статус `needs_translation`.
- 2026-08-01: свежий acceptance ICT+Medicine: A/B/C по 240 кредитов, hard violations 0, ГОСО true, international score 100%, итоговый аудит `passed=true`.
- 2026-08-01: API карточки дисциплины теперь передаёт `title_translations` также для пререквизитов и постреквизитов; переключение языка не возвращается к русскому только из-за структуры связи.
- 2026-08-01: замер локального runtime показал `/projects` около 0.1 с, `/repository/stats` около 0.64 с и `/repository/courses?limit=100` около 0.65 с; подтверждённого backend-зависания на этих страницах нет.
- Acceptance evidence (2026-08-01): `test.ps1` completed with 33/33 tests passed and a clean UTF-8 gate.
- 2026-08-02: финальный credit-gap repair после поздних prerequisite/domain swaps переведён с одного bridge-модуля на минимальный пакет 3--7-кредитных модулей; повторная проверка ОП 135 дала 240/240 вместо 207/240 и снизила hard violations с 6 до 2. Кэшированный повторный запуск занял 10,2 с.
- 2026-08-02: четыре свежие регрессионные ОП 138--141 (ИТ, информационная безопасность, агрономия, промышленная робототехника) успешно прошли A/B/C: 12/12 вариантов по 240/240 кредитов, hard violations 0, международный чек-лист 100%; bridge-модули 0/0/3/1 соответственно.
- 2026-08-02: после восстановления названий ОП 135--137 выполнена полная пересборка A/B/C; все 6 вариантов получили 240/240 кредитов и hard violations 0, bridge-модули 3 на вариант. Семестровые нагрузки контрольных ОП находятся в пределах 27--33 кредитов.
- Atlas stress-test (2026-08-02): persistent projects 135--137 were created from Atlas-inspired sectors (smart farming, industrial digital twins/robots, critical-infrastructure cyber defence). A/B/C were generated for each. The verifier correctly rejected them as production-ready: 151/240, 120/240, and 131/240 credits; five bridges and eight hard violations per variant, international score 66.7%. These are negative quality controls, not approved curricula.
- Production acceptance (2026-08-01): backend 33/33, PostgreSQL smoke connected, control programmes 6/6, localization 24,679/24,679 in RU/KK/EN with 0 missing and 0 corrupt values, frontend build passed, verified backup found.
- Fresh production acceptance (2026-08-01): bachelor 240/240, master 120/120, doctorate 180/180; all A/B/C variants passed with hard violations 0, ГОСО compliant, international score 100%, and frontend build passed.
- 2026-08-02: PostgreSQL shadow localization audit: 26,696 courses have RU/KK/EN rows; missing translations 0/0/0, corrupt values 0, 125 directions and 483 groups complete, translation quality score 1.0000. Six cards with Russian-only raw descriptions now have explicit machine-generated KK/EN drafts marked `needs_review`; they are not counted as expert-verified evidence. The audit also detects UTF-8/CP1251 mojibake rather than relying only on the replacement character.
- 2026-08-02: scheduler now maps local `Course.id` to stable EPVO `approved_course_id`, prioritizes the selected EPVO group/direction semester median over global recommendations, filters values outside `[1, total_semesters]`, and applies a conservative load/prerequisite-safe repair. A fresh transactional set of six quality-eligible A-variants produced EPVO provenance 0.9964 and strict scoped-semester alignment 0.810 (any-source 0.810); a separate negative control remained ineligible. The historical quality-eligible set remains 0.200 on the strict scoped metric (0.229 when any valid source is allowed), because it was saved before the key correction. These are structural comparisons with the EPVO repository, not blinded expert evaluation.
- 2026-08-02: the scoped-semester priority change passed all 33 regression tests and the fresh control set without new hard violations; it is retained as a production-safe repair, not as a claim of pedagogical validity.
- 2026-08-02: PydanticAI adapter remains optional and disabled in production. `pydantic-ai-slim[openai]==2.22.0` was verified in an isolated runtime; backend/venv was not upgraded.
- 2026-08-02: статья `docs/scientific_article/Curriculum_KAG_EPVO_RU.tex` обновлена по аудиту: production planner отделён от экспериментального NSGA-II, добавлены свежие внешние EPVO-метрики, таблица готовности, ограничения по blinded-оценке, Top-10 улучшений и два абзаца о PydanticAI. В статье явно зафиксировано, что сохранённые A/B/C проектов 136 и 137 имеют одинаковые fingerprints и не выдаются за решённую диверсификацию.
- 2026-08-02: API `GET /planner/{version}/variants` теперь возвращает `schedule_fingerprint`, `variant_distinct` и `duplicate_variants`; Plan Builder показывает локализованное предупреждение для старых совпадающих A/B/C. Новая генерация уже отклоняет дубли до commit, старые планы не удаляются автоматически.
- 2026-08-02: scheduler получил самый поздний diversity-pass после credit/domain/LO repair. Он выполняется только для B/C, сохраняет одинаковые кредиты, профессиональное LO-покрытие, core-компетенции и prerequisite safety; финальный verifier остаётся обязательным.
- 2026-08-02: `validate_fresh_generated_against_epvo.py` расширен полями `schedule_fingerprint`, `variants_are_distinct` и `duplicate_variants`; внешний read-only аудит теперь проверяет не только feasibility/provenance, но и фактическую различимость A/B/C.
- 2026-08-02: v2 fresh audit `.runtime/fresh-136-137-abc-final-diversity-v2.json` завершён: 6/6 вариантов quality-eligible, hard violations 0, `variants_are_distinct=true` для обоих проектов. Сохранённые старые дубли не изменялись автоматически.
- 2026-08-02: PydanticAI adapter проверен в изолированном окружении версии 2.22.0: disabled fallback возвращает штатный deterministic/OpenAI путь, enabled typed mock проходит валидацию целей/LO и передаёт `retries=0`. В production зависимость и внешний вызов остаются выключенными.
- 2026-08-02: повторный frozen-split эксперимент expert-memory поверх `epvo-sbert-finetuned-40k` завершён: Recall@10 0.6688→0.6796, MRR 0.7918→0.7992, nDCG@10 0.6642→0.6751 при весе 0.25. Split отличается от production benchmark (Recall@10 0.7071), поэтому эксперимент не внедрён и production-модель не изменена.
- 2026-08-02: `_repair_semester_appropriateness` теперь сужает только scoped-EPVO курсы до окна `recommended±1`; нормативные, bridge и нес scoped-курсы не изменяются. Свежий проект 136/A: overall semester alignment 0.8889, scoped median 1.0, hard violations 0. Результат одной программы не обобщается на весь набор.
- 2026-08-02: fallback SQLite также приведён в проверяемое состояние: оптимизирован `repair_corrupt_localizations.py` (выборка только по normalized `source_keys`, без полного сканирования raw EPVO), восстановлено 118 записей, 114 необратимых строк оставлены `needs_review`; итоговый аудит SQLite: RU/KK/EN без пропусков, corrupt_values=0, направления 125/125, группы 483/483.
- 2026-08-02: load balancers now avoid using scoped EPVO courses as generic shuttles when that would move them outside their evidence-backed `recommended±1` window. Project 137/A remains at 0.5 scoped alignment because the remaining valid source case is constrained by the generated prerequisite/load graph; it is not relabeled as a success.
- 2026-08-02: дополнительно защищены scoped-курсы во всех основных load-rebalance ветках. Контрольный 137/A-прогон сохранил 0.5 scoped alignment: причина не в свободном переносе курса, а в невозможности одновременно удовлетворить текущую кредитную ёмкость и граф; дальнейшее улучшение требует отдельной swap/flow-оптимизации и экспертной проверки.
- 2026-08-02: исправлен sampler в evaluation-only `benchmark_epvo_hybrid_ranking.py` для совпадения с heap-based frozen split; добавлен mixed word/character-3gram режим. Лучший корректный результат при weight=0.50: Recall@10 0.6700→0.6732, MRR 0.7906→0.7979, nDCG@10 0.6654→0.6714; production model unchanged.
### 2026-08-03: локализованный экспорт

Исправлен `backend/app/api/export_api.py`: XLSX-экспорт принимает параметр `language` (RU/KK/EN, также понимает legacy-алиас `kz`) и выбирает название дисциплины в языке интерфейса. При неполной строке используется последовательный fallback RU → KK → EN → исходное название. Проверка: `py_compile`, `git diff --check`, `test.ps1` — 33/33.

Добавлена отдельная метрика внешнего аудита `semester_alignment_prereq_adjusted_pm1`. Она учитывает самый ранний семестр после фактических пререквизитов, но сохраняет исходные raw-метрики отдельно. На свежей программе 136: raw 0,8889, scoped median 1,0000; на программе 137: raw 0,5000, prerequisite-adjusted 0,7857. Это диагностическая метрика, а не замена исходному EPVO-сравнению.

В evaluation-only ranking benchmark добавлены seed 42, `model.eval()` и детерминированные CUDA-настройки. Эксперимент с добавлением цели/направления программы к тексту LO не внедрён: его абсолютный baseline оказался несопоставим с предыдущим frozen отчётом, поэтому результат признан диагностическим, а не улучшением модели.

Контрольный API-аудит с уровнями bachelor/master/doctorate (`.runtime/quality-control-stable-levels.json`) прошёл: 5/5 контрольных проектов, все варианты A/B/C, один активный вариант и отсутствие пропусков уровней. В расширенном списке проекты 136 и 137 остаются историческими контрольными записями с устаревшими сохранёнными fingerprint; свежая транзакционная проверка этих проектов проходит, поэтому их нельзя смешивать со стабильным baseline без регенерации.
### 2026-08-03 — контроль полного EPVO-слоя

- Для активного PostgreSQL-каталога подтверждено 26 696 курсов с RU/KK/EN, без пропусков и `�`; направления 125/125, группы 483/483.
- Для полного нормализованного слоя (191 292 карточки) покрытие источником: заголовки RU 100%, KK 99,994%, EN 99,874%; описания RU 99,887%, KK 99,923%, EN 99,363%.
- 930 полей восстановлены из raw EPVO; 134 локализации получили подтверждённые исходные значения. Оставшиеся пустые поля отсутствуют в raw-карточках и не заполняются копированием русского текста.
- Добавлен локальный NLLB-процесс для машинных черновиков отсутствующих переводов; результат всегда маркируется `machine_nllb_draft/needs_review` и не считается экспертным.
### 2026-08-03: production acceptance gate rechecked

`acceptance-test.ps1` завершился успешно: backend 35/35 тестов, PostgreSQL smoke connected, 6 контрольных программ A/B/C, локализация PostgreSQL 26,696/26,696 для RU/KK/EN с `corrupt_values=0`, frontend production build. Предупреждение Vite CJS остаётся информационным и больше не роняет exit-код; предыдущая запись о RED-шлюзе устарела.
### 2026-08-03: disk usage audit

Удаление не выполнялось. Зафиксированы размеры `backend/models` 49.57 GB и `.runtime` 9.10 GB; добавлен безопасный порядок manifest → verification → archive → optional deletion в `docs/DISK_USAGE_AUDIT_2026_08_03_RU.md`.
### 2026-08-03: единая нормализация языков

Добавлен `backend/app/services/language.py`: единый mapping RU/KK/EN и legacy-алиасов `kz/kaz`, а также EPVO suffix mapping. Подключено в export API и EPVO API, добавлены два регрессионных теста. После изменения `test.ps1` и полный `acceptance-test.ps1` прошли: 37/37, PostgreSQL smoke, контрольные программы, локализация и frontend build.
### 2026-08-03: language aliases in AI suggestions

Маршрут предложения целей/РО в `projects.py` теперь использует общий `normalize_language`, поэтому `kz/kaz/kazakh` корректно дают казахский ответ (`kk`). После изменения `test.ps1` и `acceptance-test.ps1` прошли без регрессий.
### 2026-08-03: единая нормализация языка в LO-анализе

Маршруты анализа достижимости и покрытия LO теперь используют общий `normalize_language`. Алиасы `kz`, `kaz` и `kazakh` корректно приводятся к казахскому `kk`, поэтому ответы AI и локальные fallback-ответы не переключаются ошибочно на русский. После изменения регрессионный набор: 37/37 тестов.
### 2026-08-03: нормализация языка в утверждении EPVO-кандидатов

Сервис утверждения дисциплин из EPVO теперь нормализует язык инструкции перед созданием локализованного описания. Это устраняет расхождение, при котором алиасы `kz/kaz/kazakh` могли приводить к русскому fallback-тексту. Регрессия: 37/37 тестов.
### 2026-08-03: единые языковые алиасы во frontend

`LanguageContext` теперь нормализует `ru/rus/russian`, `kk/kz/kaz/kazakh` и `en/eng/english` одинаково с backend. Это устраняет рассинхронизацию интерфейса при сохранённом языке `kaz` или `kz`. Vite build и backend-регрессия пройдены: 37/37.
### 2026-08-03: полный acceptance после языкового прохода

Полный production acceptance успешно завершён: 37/37 backend-тестов, PostgreSQL smoke, 6 контрольных программ, RU/KK/EN локализация 26 696/26 696 курсов без пропусков и повреждённых значений, frontend production build. Статус: `Full production acceptance passed`.
### 2026-08-03: канонический язык передаётся всем UI-компонентам

LanguageContext теперь возвращает наружу нормализованный код языка, а не исходный alias из localStorage. Компоненты графа, планировщика и анализа LO одинаково обрабатывают `kz/kaz/kazakh` как `kk`. Production build после изменения успешен.
### 2026-08-03: структурированные backend-логи

Убраны диагностические `print` из авторизации, bridge-генератора и обработчика сборки плана. Ошибки теперь идут через стандартный logging: fallback LLM остаётся видимым как warning, а ошибка сборки плана получает traceback в серверном логе без дублирования в stdout. Тесты 37/37 и PostgreSQL smoke пройдены.
### 2026-08-03: отключена ненужная загрузка legacy JSON при scoring

При полном PostgreSQL-репозитории scoring больше не читает 58-МБ `course_translations.json`: JSON вызывается только при явном `LEGACY_TRANSLATIONS_FALLBACK=true`. Проверка `_course_match_text` оставила cache пустым (`misses=0`), регрессия 37/37, данные не менялись. Это уменьшает стартовую память и задержку генерации на чистом PostgreSQL.
### 2026-08-03: регрессионный тест для memory guard

Добавлен тест `test_localization_fallback.py`: при стандартном PostgreSQL-режиме scoring не должен загружать legacy JSON-каталог. Проверка подтверждает `cache misses=0`; общий набор теперь **38/38**.
### 2026-08-03: таймауты Docker в launcher

`start.ps1` теперь задаёт безопасные значения `DOCKER_CLIENT_TIMEOUT=10` и `COMPOSE_HTTP_TIMEOUT=30`, если пользователь их не указал. При недоступном Docker Desktop launcher больше не должен зависать бесконечно на клиентском вызове; существующая логика SQLite/PostgreSQL не менялась. Регрессия: 38/38 тестов.
### 2026-08-03: CI приведён к production Python

GitHub Actions использовал Python 3.11, тогда как `backend/Dockerfile` и production requirements фиксируют Python 3.12. CI переведён на 3.12, чтобы тестовая среда совпадала с production. Локальная регрессия: 38/38.
### 2026-08-03: проверен Alembic baseline на PostgreSQL shadow

На `127.0.0.1:5433/curriculum_kag_shadow` выполнены `alembic upgrade head` и `alembic current`. Схема находится на `20260802_baseline (head)`, миграций к применению нет. Production startup пока не переключался с `create_all`; это оставлено отдельным безопасным этапом после подготовки следующей forward-миграции.
### 2026-08-03: очищены дублирующиеся импорты auth

В `app/services/auth.py` удалены повторные импорты `bcrypt` и `OAuth2PasswordBearer`, оставлен один compatibility-патч для Passlib/Bcrypt. Поведение проверки паролей и JWT не менялось; тесты 38/38.
### 2026-08-03: казахское форматирование дат

Research Dashboard теперь использует `kk-KZ` для дат в казахском интерфейсе вместо русского `ru-RU`. Production build успешен.
### 2026-08-03: читаемые ошибки API во frontend

Добавлен общий `frontend/src/utils/errors.js`, который корректно отображает строковые, объектные и массивные FastAPI-ошибки вместо `[object Object]`. Подключён к графу, LO-анализу, bridge-операциям и загрузке покрытия. Production build успешен.
### 2026-08-03: единый форматтер ошибок на страницах

Форматтер API-ошибок подключён также к Course Syllabus, EPVO Comparison, Project Details, Repository и Research Dashboard. Объектные ответы FastAPI теперь отображаются читаемо, а не как `[object Object]`. Frontend build успешен.
### 2026-08-03: завершена обработка объектных API-ошибок

Форматтер `formatApiError` подключён к Git Versions, Login и Project Details; теперь основные страницы конструктора, аналитики, репозитория и Git не выводят сырые объекты API. Frontend build и static quality gate пройдены.
### 2026-08-03: локализация Git-ошибок и дат

Git Versions теперь форматирует даты по выбранному языку (`ru-RU`, `kk-KZ`, `en-US`) и использует локализованные fallback-сообщения для ошибок Git, diff и создания ветки. Frontend build успешен.
### 2026-08-03: локализованы статусы Git-файлов

Метки `Modified/Added/Deleted/Renamed/Conflict/New` в Git Versions теперь отображаются на русском, казахском или английском в зависимости от языка интерфейса. Production build успешен.
### 2026-08-03: read-only smoke-тест критических UI API

Добавлен `backend/scripts/smoke_core_api.py`: авторизация, `variants`, граф пререквизитов и `lo-achievability`. На рабочем проекте version 14 все три endpoint вернули HTTP 200: варианты 518 KB, граф 316 KB, LO-анализ 544 bytes. Скрипт не изменяет БД.
