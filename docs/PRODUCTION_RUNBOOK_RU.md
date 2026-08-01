# Production runbook

Продакшен-шаблон использует PostgreSQL/pgvector на `5433` и backend без `--reload`.

1. Создайте отдельный `.env.production` (секреты не коммитить): `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `SECRET_KEY`.
2. Запустите `docker compose --env-file .env.production -f docker-compose.production.yml up -d --build`.
3. Проверьте `http://127.0.0.1:8000/health` и статус `docker compose ... ps`.
4. Делайте резервную копию: `powershell -File .\scripts\backup-postgres-production.ps1`.
5. Храните копии вне хоста и периодически проверяйте восстановление на отдельной shadow-базе.

Локальная проверка маршрутов: `powershell -File .\scripts\ui-smoke.ps1`. Она проверяет основные страницы, UTF-8 HTML и наличие RU/KK/EN подписей. Интерактивная проверка кликов и смены языка всё равно выполняется человеком в браузере.

Проверка доступности для планировщика: `powershell -File .\scripts\monitor-health.ps1`. При сбое команда возвращает код `1`, поэтому её можно подключить к Task Scheduler, cron или внешнему мониторингу.

Ограничение: внешний домен, TLS, WAF и мониторинг (Sentry/Prometheus) зависят от выбранного сервера и пока не включены автоматически. Перед публикацией добавьте reverse proxy с HTTPS и секретное хранилище.
