# Локальный запуск

## Обычный запуск

Дважды щёлкните `start.bat` в корне проекта. Скрипт поднимет backend и frontend, проверит их готовность и откроет:

[http://localhost:3001/](http://localhost:3001/)

Вход:

- Email: `admin@curriculum-kag.local`
- Пароль: `admin123`

Остановка: `stop.bat`.

Повторный запуск безопасен: уже работающие сервисы не дублируются. Frontend пересобирается только при изменении его исходников. Для принудительной пересборки:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Rebuild
```

## Первый запуск на новом компьютере

Требования: Python 3.11+ и Node.js 18+. Виртуальное окружение и зависимости `start.bat` создаёт автоматически. На первом запуске потребуется интернет.

Затем создайте `backend\.env`:

```env
DATABASE_URL=sqlite:///./curriculum_kag.db
SECRET_KEY=replace-with-at-least-32-characters
LLM_PROVIDER=openai
LLM_API_KEY=
LLM_MODEL_NAME=gpt-4o
```

Для базовой локальной работы ключ LLM можно оставить пустым. После этого запускайте `start.bat`.

## Если запуск не удался

Логи находятся в:

- `.runtime\backend.err.log`
- `.runtime\frontend.err.log`

Проверки вручную:

- backend: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- frontend: [http://127.0.0.1:3001/api/health](http://127.0.0.1:3001/api/health)

Docker Compose остаётся отдельным вариантом для окружения с PostgreSQL, но для обычной локальной демонстрации он не требуется.
# Автоматический выбор базы данных

Обычный запуск через `start.bat` сначала проверяет PostgreSQL. Если служба на
порту 5432 недоступна, система автоматически запускается с локальной базой
`backend/curriculum_kag.db`. Это позволяет создавать и генерировать программы
без ручного запуска PostgreSQL. При следующем запуске с доступным PostgreSQL
будет использована PostgreSQL-база из `.env`.
