# Production runbook

Продакшен-шаблон использует PostgreSQL/pgvector на `5433` и backend без `--reload`.

1. Создайте отдельный `.env.production` (секреты не коммитить): `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `SECRET_KEY`.
2. Запустите `docker compose --env-file .env.production -f docker-compose.production.yml up -d --build`.
3. Проверьте `http://127.0.0.1:8000/health` и статус `docker compose ... ps`.
4. Делайте резервную копию: `powershell -File .\scripts\backup-postgres-production.ps1`.
5. Храните копии вне хоста и периодически проверяйте восстановление на отдельной shadow-базе.

Ограничение: внешний домен, TLS, WAF и мониторинг (Sentry/Prometheus) зависят от выбранного сервера и пока не включены автоматически. Перед публикацией добавьте reverse proxy с HTTPS и секретное хранилище.
