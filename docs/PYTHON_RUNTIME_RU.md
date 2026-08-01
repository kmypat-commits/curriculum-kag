# Единая версия Python и зависимостей

Рабочий runtime проекта — Python 3.12.

- Docker: `python:3.12-slim`.
- Основной список зависимостей: `backend/requirements.txt`.
- Локальный облегчённый список: `backend/requirements-local.txt`; его версии синхронизированы с production baseline, но ML-пакеты остаются опциональными по конфигурации.
- Версия Python закреплена в `.python-version`.

После изменения зависимостей необходимо выполнить `test.ps1`, production-сборку frontend и smoke-проверку PostgreSQL.

## Alembic

`backend/migrations/versions/20260802_0001_baseline.py` фиксирует уже
существующую проверенную PostgreSQL-схему без повторного создания таблиц.
Новые изменения схемы добавляются только отдельными Alembic-ревизиями:

```powershell
cd backend
alembic upgrade head
```

Baseline нельзя использовать для удаления или пересоздания рабочей базы.
