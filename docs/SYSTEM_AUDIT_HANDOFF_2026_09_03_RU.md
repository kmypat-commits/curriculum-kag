# Аудит системы Curriculum-KAG и план закрытия — 03.09.2026

## Итог

Текущая система — сильный staging-кандидат, не готовый release candidate. Это не «вайбкод»: есть typed API, ownership/RBAC, транзакционное сохранение, асинхронные jobs с lease/heartbeat/retry/cancel, формальная проверка учебных планов, evidence/bridge объяснения, RU/KK/EN UI, PostgreSQL/backup и автоматические тесты.

Главные риски внедрения — эксплуатационные доказательства, а не отсутствие базовой архитектуры:

1. Docker Desktop периодически не поднимает Linux daemon из-за stale runtime socket (`sailor-ingest.sock` / `engine.sock`). Оба entry подтверждены как Windows `ReparsePoint` с `Error 1920`; VHDX остаётся на `D:`; пути `C:\Users\User\AppData\Local\Docker\run\...` — это ephemeral runtime namespace Desktop, а не возврат data disk на `C:`. Repair-скрипт, основной `start.ps1` и `start.bat` дополнительно исправлены: Windows `del`, targeted `fsutil reparsepoint delete`, WSL shutdown, service stop, quarantine move и Docker CLI path теперь bounded/явно определены и не должны повесить one-command launcher. Регрессия закреплена `scripts/check-launcher-hardening.ps1` и добавлена в CI; текущая система всё ещё удерживает эти entries, поэтому reboot/UAC остаётся fallback.
2. Legacy SQLite содержит 205222 orphan FK. Автоматический cutover правильно блокируется; embeddings и match_scores требуют regeneration/discard policy, bridge_modules и match_feedback — repair/review.
3. 30/30 frozen breadth cohort пройден. Свежий stability runtime evidence после исправления fingerprint ещё не получен: исторический 5/5 нельзя смешивать с pre-fix артефактом 1/5. Нужен повтор внутри чистого production Docker runtime.
4. Нет независимой blind-приёмки двумя предметными экспертами и доказательства inter-rater agreement.
5. Нет факта успешного GitHub CI/release run после последних изменений; telemetry сохраняется, но p95/5xx/DB/backup alerts ещё не подключены.

## Подтверждённые результаты

| Область | Факт | Статус |
|---|---|---|
| Backend | regression suite; strict inventory 90 routes, 46 object-scoped, 0 без access-marker | подтверждено локально |
| Планировщик | breadth 30/30; исторический stability 5/5; контрольный ict-medicine без hard violations | breadth подтверждён; stability после последнего fingerprint fix требует повторного runtime-прогона |
| Frontend | Vitest 8/8, build, graph gate, i18n gate 0 | подтверждено локально |
| Browser | authenticated real smoke 1/1, axe critical/serious 0 | подтверждено локально |
| Security | HttpOnly access cookie, CSRF, secure production settings, RBAC/ownership, request limits, pinned Actions, чистые pip/npm audits | static/local; CI run нужен |
| Backup | checksum, Alembic head, counts и FK проверены в изолированном restore | подтверждено для имеющегося dump |
| Docker | VHDX на D:, но текущий daemon/5433 недоступны; stale sockets недоступны без UAC | не закрыто |

## Задачи до внедрения

### P0 — блокирует RC

- **DEP-01 Docker runtime:** один ручной UAC-запуск repair после полного выхода Desktop; затем проверить daemon, `localhost:5433`, Compose health, Alembic и один generation smoke. Не удалять VHDX и не нажимать `Reset to factory defaults`.
- **DATA-01 migration:** утвердить discard/regeneration для `embeddings`/`match_scores`; вручную repair/review `bridge_modules`/`match_feedback`; повторить FK scan, counts, checksums и restore. Cutover запрещён при repair/review остатках.
- **QA-01 acceptance:** 30–50 новых уникальных программ в чистом production image; сохранить manifest с model/ruleset/image/database checksums и временем каждого этапа.
- **QA-02 expert review:** два независимых эксперта, blind IDs, rubric по кредитам, ГОСО, prerequisites, семестрам, релевантности и bridge modules; рассчитать agreement.

### P1 — блокирует качественный RC

- **CI-01:** выполнить GitHub workflow на текущем commit; приложить run URL, coverage XML, SBOM, browser/axe и security artifacts; после baseline поднять coverage threshold.
- **OBS-01:** aggregate planner observability endpoint и единый bounded monitor реализованы для build states, stale/active leases, generation p95, health/Docker и backup age/checksum; полноценные dashboard/alerts для 5xx, DB saturation и restore failure остаются deployment-level задачей.
- **OBS-02:** проверка живости PID, stale timeout, admin-only безопасная отмена и защита от второго тяжёлого процесса реализованы; осталось приложить runtime evidence.
- **OPS-03:** timeout production `pg_dump`, сохранение stderr и явная ошибка реализованы; осталось проверить на реальном большом dump после восстановления Docker runtime.
- **SEC-02:** PostgreSQL-backed rate limiter реализован и проверен; остаётся приложить фактический CI/runtime evidence перед scale-out.
- **REL-01:** автоматически запретить staging tag без P0/P1 artifacts, image digest, manifest/checksum и отдельного model/database inventory.
- **DEV-01:** Git UI теперь явно выключается в production через `GIT_UI_ENABLED=false` и startup validation; продолжить декомпозицию крупных planner/API/page файлов по одному модулю с regression после каждого шага.

### P2 — после RC

- **I18N/UI:** локальные language helpers устранены (gate 0/0); остаётся перенести ветвления из `planBuilderPresentation.js` в каталог и проверить длинные KK-строки, keyboard/ARIA для графа и сложных панелей.
- **UI-08:** сократить повторяющиеся декоративные borders и заменить `transition: width` на устойчивую анимацию; пройти desktop/mobile visual smoke.
- **MODEL-01:** версионировать model artifact отдельно от базы и добавить reproducibility check.

## Как работает система

Пользователь создаёт проект и версию программы, задаёт уровень, профиль, домены, язык, кредиты и семестры. Backend проверяет права и входные ограничения, получает EPVO/evidence, строит варианты и сохраняет результат транзакционно. Planner выполняет admission/repair: кредиты, ГОСО, семестровую нагрузку, prerequisites, дубли, уровень дисциплин, LO coverage и bridge-модули. Job-control показывает прогресс и поддерживает lease, heartbeat, retry, cancel и idempotency. UI показывает варианты, качество, объяснения, граф prerequisites, замены, семестры и экспорт. Audit trail хранит изменения и telemetry.

## Оценка уровня

Для одного разработчика это высокий уровень: ближе к зрелому прикладному staging-продукту, чем к прототипу. Сильные стороны — доменная глубина, формальные инварианты, explainability, защита object ownership и воспроизводимые проверки. До уровня промышленного продукта не хватает не «переписать всё», а закрыть четыре доказательства: чистый runtime, безопасный migration cutover, независимая предметная приёмка и эксплуатационные CI/alerts/release artifacts.

## Go / No-Go

- Локальная демонстрация: **GO**.
- Закрытый пилот с ручным экспертным review: **GO с ограничениями**.
- Реальное внедрение и публичный production: **NO-GO до P0 и подтверждённого CI/release evidence**.
