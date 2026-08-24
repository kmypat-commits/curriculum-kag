# Production runbook

Продакшен-шаблон использует PostgreSQL/pgvector на `5433` и backend без `--reload`.

1. Скопируйте `.env.production.example` в `.env.production` и замените все тестовые значения. Заполненный файл не коммитить.
2. Запустите `docker compose --env-file .env.production -f docker-compose.production.yml up -d --build`.
3. Caddy автоматически получает HTTPS-сертификат для `DOMAIN`, если DNS уже указывает на сервер. Проверьте `https://DOMAIN/health` и статус `docker compose ... ps`.
4. Делайте резервную копию: `powershell -File .\scripts\backup-postgres-production.ps1`.
5. Храните копии вне хоста и периодически проверяйте восстановление на отдельной shadow-базе.

Локальная проверка маршрутов: `powershell -File .\scripts\ui-smoke.ps1`. Она проверяет основные страницы, включая `/projects/13/graph`, UTF-8 HTML и наличие RU/KK/EN подписей. После запуска frontend выполните браузерный smoke-чек-лист: открыть план → граф, переключить RU/KK/EN, проверить названия дисциплин/циклов/доменов и нажать «Повторить загрузку графа» при ошибке. Если `localhost:3001` не отвечает, это инфраструктурный блокер smoke, а не доказательство дефекта графа.

Проверка доступности для планировщика: `powershell -File .\scripts\monitor-health.ps1`. При сбое команда возвращает код `1`, поэтому её можно подключить к Task Scheduler, cron или внешнему мониторингу.

Ограничение: внешний домен, TLS, WAF и мониторинг (Sentry/Prometheus) зависят от выбранного сервера и пока не включены автоматически. Перед публикацией добавьте reverse proxy с HTTPS и секретное хранилище.
