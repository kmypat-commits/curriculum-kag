# Security audit — Curriculum-KAG

Дата: 3 сентября 2026 года
Область: FastAPI backend, React frontend, Docker/production configuration.
Режим: активный code/config review по текущему рабочему дереву; внешняя WAF/CDN-инфраструктура не считалась доказанной.

## Краткий вывод

Критического дефекта, позволяющего обойти уже инвентаризированную ownership/RBAC-защиту, в проверенных маршрутах не найдено. Cookie-auth и CSRF-механизм присутствуют, production startup validation усилена, а production rate-limit уже вынесен в PostgreSQL. Система уже заметно выше «навайбкоденного» прототипа, но staging нельзя объявлять полностью security-готовым до фактического CI/browser evidence и runtime-проверки edge headers.

## Исправлено в ходе аудита

### SEC-FIX-01 — production мог стартовать с локальными defaults

- Severity: High
- Location: `backend/app/config.py`, `validate_production_settings`
- Evidence: до исправления пустой `DOMAIN` и локальные `ALLOWED_HOSTS/CORS_ORIGINS` формально проходили validation.
- Fix: production теперь требует непустой `DOMAIN`, его присутствие в `ALLOWED_HOSTS`, HTTPS CORS origins без localhost и `DOCS_ENABLED=false`.
- Verification: `backend/tests/test_access_layer.py` содержит positive и negative tests.

## Исправленные и оставшиеся задачи

### SEC-001 — login одновременно возвращал JWT в JSON и устанавливал HttpOnly cookie — закрыто

Browser `/auth/login` теперь возвращает `204` и только cookies; JWT не попадает в тело ответа. Для CLI и automation добавлен явный `/auth/token`, а OAuth2 metadata и smoke-скрипты переключены на этот endpoint. Поведенческий тест проверяет отсутствие JSON-токена и наличие `HttpOnly` cookie. После штатного restart это подтверждено runtime-smoke: login `204`, тело `0` байт, `/auth/me` `200`, `/auth/token` выдаёт bearer, `/health` — `healthy`.

- Evidence after fix: browser login returns `204` with cookies only; bearer is available only through the explicit `/auth/token` endpoint.

### SEC-002 — rate limit хранится в памяти процесса — закрыто для production

- Severity: Medium → closed for production staging
- Location: `backend/app/main.py`, `RequestGuardMiddleware`; `backend/app/models/rate_limit.py`; Alembic `20260903_rate_limit_buckets`.
- Evidence: production Compose задаёт `RATE_LIMIT_BACKEND=postgres`; bucket использует атомарный PostgreSQL `ON CONFLICT ... RETURNING event_count`; local/test остаётся memory-only.
- Impact before fix: при нескольких backend workers или рестарте лимит был не общий.
- Fix: добавлен общий PostgreSQL bucket с fail-closed `503` при недоступной таблице/БД; memory fallback разрешён только при явном `RATE_LIMIT_BACKEND=memory`.
- Verification: backend regression **173 passed**; production Compose config включает PostgreSQL backend; миграция и clean SQLite smoke проверяют `rate_limit_buckets`; сохранённый smoke подтверждает ожидаемое отклонение превышения лимита.

### SEC-003 — authenticated browser/a11y acceptance ещё не является доказанным

- Severity: Medium
- Location: `.github/workflows/quality.yml`, frontend Playwright job.
- Evidence: workflow запускает production frontend preview и исключает сценарий `backend health`; authenticated PostgreSQL browser flow отдельно не подтверждён.
- Impact: UI может быть зелёным как shell, но cookie/CSRF/RBAC/ownership поведение в реальном браузере останется непроверенным.
- Fix: добавить seeded PostgreSQL service, login fixture и owner/other/admin Playwright tests плюс axe scan.

### SEC-004 — security headers frontend зависят от edge configuration

- Severity: Low/Medium
- Location: `frontend/nginx.conf`, `ops/Caddyfile`, `backend/app/main.py`.
- Evidence: backend и Caddy задают базовые headers, но отдельная frontend nginx-конфигурация не содержит полного CSP/Referrer/Permissions набора.
- Impact: при публикации frontend без Caddy часть browser protections может отсутствовать.
- Fix: определить единый owner headers (edge), добавить runtime smoke, что публичный app shell получает CSP, nosniff, frame-ancestors/X-Frame-Options и Referrer-Policy.

### SEC-005 — Python dependency reproducibility не доказана на уровне hashes/SBOM

- Severity: Low/Medium
- Location: `backend/requirements.lock`, release workflow/scripts.
- Evidence: версии зафиксированы, но release acceptance ещё не публикует обязательный hash-locked install и SBOM/digest set для всех образов.
- Impact: supply-chain provenance release candidate нельзя проверить только по Git tree.
- Fix: добавить `pip --require-hashes`-совместимый lock, SBOM, image digests и CI gate.

## Уже подтверждено отдельными проверками

- API inventory: 90 routes, 46 object-scoped, 46/46 access markers.
- Backend regression: 173 tests passed.
- Docker engine 29.7.2, PostgreSQL health 200, frontend 200.
- Cookie-authenticated writes защищены double-submit CSRF token.
- Production Docker image запускается non-root.
- Frontend имеет lockfile и CI использует `npm ci`; dependency audit присутствует.

## Приоритетный план

1. SEC-001: разделить browser cookie login и CLI bearer token — выполнено.
2. SEC-002: распределённый limiter/lease в PostgreSQL или Redis — PostgreSQL-вариант реализован и проверен межпроцессным smoke.
3. SEC-003: authenticated Playwright + axe + ownership matrix.
4. SEC-004/005: edge header smoke, SBOM, hashes и image digests.

## Дополнительные исправления после первоначального отчёта

- Исправлен безопасный отказ RBAC: роль без загруженной коллекции `permissions` теперь трактуется как отсутствие дополнительных прав и возвращает `403`, а не вызывает `AttributeError`/`500`; тот же safe fallback добавлен в `get_user_permissions`, чтобы `/auth/me` не падал при неполной ORM-загрузке роли. Покрыто HTTP и unit regression-тестами.
- Planner performance monitor теперь предпочитает `CURRICULUM_PLANNER_MONITOR_TOKEN` из окружения процесса; аргумент `-BearerToken` оставлен только для совместимости и не рекомендуется, поскольку аргументы процесса могут быть видны другим пользователям.

- `WEB_CONCURRENCY>1` теперь fail-closed в production до появления общего limiter backend.
- Добавлен явный `build-retry`, разрешённый только после `failed/timed_out/cancelled`; активная попытка не прерывается.
- Профили объёма сопоставляются точными парами `(кредиты, семестры)`; admin-only ML smoke inputs получили строгую schema validation и вычислительные лимиты.

- Planner state-changing routes дополнительно требуют `planner:write`, поэтому одного ownership/read-доступа недостаточно для запуска, отмены, повтора или публикации плана.
- Verification: **173 backend tests passed**, strict inventory **90/46/0**.

- CI дополнен отдельным real-browser job с изолированным backend seed; mocked UI smoke больше не является единственным authenticated evidence. До фактического CI run этот пункт имеет статус **implemented, runtime pending**.

- Caddy edge теперь задаёт тот же CSP и `Permissions-Policy`, что и frontend nginx/backend; header ownership согласован на обоих уровнях.
