# Статус стабилизации Curriculum-KAG — 02.08.2026

## Проверено

| Область | Реализация | Проверка |
|---|---|---|
| Python и зависимости | Python 3.12 зафиксирован в `.python-version`, Docker и requirements | production build и backend acceptance проходят |
| Alembic | Добавлена ревизия `20260802_baseline` для существующей PostgreSQL-схемы | `alembic upgrade head` выполнен; `alembic current` показывает `20260802_baseline (head)` |
| Кэш планировщика | Отпечаток учитывает число строк, максимальный ID и `updated_at` | изменения, добавления и удаления инвалидируют кэш |
| Локализации | PostgreSQL `CourseLocalization` и EPVO — источник по умолчанию | JSON fallback выключен (`LEGACY_TRANSLATIONS_FALLBACK=false`) |
| JWT и уведомления | токен хранится в `sessionStorage`; сообщения Repository локализованы | frontend production build успешен |
| Архив | старые seed-скрипты вынесены в `backend/scripts/legacy/`, UI backup — в `frontend/src/pages/archive/` | runtime-пути не запускают архивные файлы |

## Runtime-проверка

- PostgreSQL на `localhost:5433` подключён.
- `/api/health`: `database=postgresql`, `database_status=connected`.
- Backend tests: `33/33 passed`.
- Frontend: `npm run build` завершён успешно.
- Граф проекта 13: 49 узлов и 20 связей через авторизованный API.

## Важное ограничение

Baseline-ревизия не перестраивает таблицы: она только фиксирует уже проверенную схему мигрированной базы. Все будущие изменения схемы должны оформляться отдельными обратимыми Alembic-ревизиями.
