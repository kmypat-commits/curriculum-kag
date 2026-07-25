# Curriculum-KAG Generator

> Выгрузка открытых программ ЕПВО: [EPVO_DATASET_RU.md](EPVO_DATASET_RU.md).
> План перехода на PostgreSQL/pgvector: [docs/POSTGRESQL_MIGRATION_RU.md](docs/POSTGRESQL_MIGRATION_RU.md).
> Нормативные практики, НИР и итоговая аттестация ГОСО РК: [docs/GOSO_RK_COMPONENTS_RU.md](docs/GOSO_RK_COMPONENTS_RU.md).

Информационная система для автоматизированного проектирования учебных планов с использованием Knowledge-Augmented Generation (KAG).

## Возможности

- 🎓 Автоматический подбор дисциплин по результатам обучения (Learning Outcomes)
- 🔗 Интеграция дисциплин из разных предметных областей
- 🌉 Генерация междисциплинарных курсов (bridge modules)
- 📊 Анализ покрытия результатов обучения
- 📅 Построение учебного плана по семестрам с учетом пререквизитов
- 📝 Доказательства и объяснения для каждого решения
- 🔄 Версионирование и сравнение планов

## Технологический стек

- **Backend**: Python 3.11+, FastAPI
- **Database**: PostgreSQL 16 с pgvector
- **Frontend**: React 18
- **Embeddings**: Sentence Transformers (multilingual)
- **LLM**: OpenAI GPT-4 / Anthropic Claude / Local models
- **Containerization**: Docker Compose

## Быстрый старт

Для обычной работы Docker и ручной запуск двух терминалов больше не нужны.

1. Дважды щёлкните `start.bat`.
2. Дождитесь сообщения `Curriculum-KAG is ready`.
3. Браузер откроет [http://localhost:3001/](http://localhost:3001/) автоматически.

Вход:

- Email: `admin@curriculum-kag.local`
- Пароль: `admin123`

Чтобы остановить приложение, запустите `stop.bat`.

Сценарий запуска сам:

- использует рабочее Python-окружение проекта;
- пересобирает frontend только после изменения исходников;
- запускает backend и frontend в фоне;
- ждёт успешного health check перед открытием браузера;
- пишет диагностические логи в `.runtime`.

### Первый запуск на новом компьютере

Нужны Python 3.11+ и Node.js 18+. Остальное `start.bat` подготовит автоматически. На первом запуске потребуется интернет для установки зависимостей.

Создайте `backend\.env` на основе корневого `.env.example` и для локальной SQLite-базы укажите:

```env
DATABASE_URL=sqlite:///./curriculum_kag.db
SECRET_KEY=replace-with-at-least-32-characters
LLM_API_KEY=
```

После этого используйте только `start.bat` и `stop.bat`.

Простая инструкция по работе: [USER_GUIDE_RU.md](USER_GUIDE_RU.md).

Проверка соответствия диссертации: [THESIS_ALIGNMENT_RU.md](THESIS_ALIGNMENT_RU.md).

## Структура проекта

```
curriculum-kag/
├── backend/              # FastAPI backend
│   ├── app/
│   │   ├── api/         # API endpoints
│   │   ├── kag/         # KAG engine
│   │   ├── models/      # SQLAlchemy models
│   │   ├── services/    # Business logic
│   │   ├── planner/     # Curriculum planner
│   │   └── export/      # Export services
│   ├── migrations/      # Alembic migrations
│   └── tests/           # Backend tests
├── frontend/            # React frontend
│   ├── src/
│   │   ├── components/  # React components
│   │   ├── pages/       # Page components
│   │   ├── contexts/    # React contexts
│   │   └── utils/       # Utilities
│   └── public/          # Static assets
├── demo/                # Demo data
└── docker-compose.yml   # Docker configuration
```

## Разработка

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm start
```

### Тестирование

```bash
# Backend tests
cd backend
pytest

# Frontend tests
cd frontend
npm test
```

## Основные сценарии использования

### 1. Импорт дисциплин

1. Перейдите в раздел "Репозиторий"
2. Нажмите "Импорт"
3. Загрузите файл XLSX/CSV/JSON
4. Проверьте результаты импорта

### 2. Создание образовательной программы

1. Перейдите в "Новый проект"
2. Заполните мастер создания:
   - Название и домены
   - Результаты обучения (LO)
   - Ограничения (семестры, кредиты)
3. Запустите анализ покрытия

### 3. Построение учебного плана

1. Просмотрите покрытие LO
2. Примите/отклоните предложения по интеграции
3. Сгенерируйте bridge modules при необходимости
4. Постройте план (3 варианта)
5. Выберите оптимальный вариант
6. Экспортируйте в XLSX

## API Documentation

Полная документация API доступна по адресу: http://localhost:8000/docs

Основные endpoints:
- `POST /auth/login` - Аутентификация
- `POST /projects` - Создание проекта
- `POST /repository/courses/import` - Импорт дисциплин
- `POST /kag/{project_id}/match` - Подбор дисциплин
- `POST /planner/{project_id}/build` - Построение плана

## Роли и права доступа

- **Администратор**: полный доступ ко всем функциям
- **Методист/Эксперт**: создание и редактирование программ
- **Аналитик**: просмотр метрик и отчетов
- **Гость**: только просмотр

## Лицензия

[Укажите лицензию]

## Контакты

[Укажите контакты для поддержки]
