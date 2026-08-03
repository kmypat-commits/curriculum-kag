# Legacy-каталог переводов

## Текущее решение

Основным источником переводов Curriculum-KAG является PostgreSQL-репозиторий EPVO. Backend по умолчанию использует `LEGACY_TRANSLATIONS_FALLBACK=false`, поэтому большой JSON-каталог переводов не загружается при построении планов и не расходует память.

Файл `backend/data/course_translations.json` оставлен как пустой совместимый placeholder (`{}`). Это сделано намеренно: он не является источником данных для рабочего PostgreSQL-контура.

## Восстановление старого режима

Если потребуется временно запустить старый SQLite/JSON-контур:

1. восстановить LFS-объект старого файла `course_translations.json` из хранилища Git LFS;
2. проверить SHA-256 объекта: `7141f80ee1df57f4c9721f0b28d5a6bccd5ff3e2b0b0b502bff8282f145956f6`;
3. установить `LEGACY_TRANSLATIONS_FALLBACK=true` только для этого режима;
4. выполнить smoke-тесты и проверить RU/KK/EN до публикации.

Пустой placeholder не должен считаться повреждением базы: актуальные переводы хранятся в PostgreSQL и проверяются тестом `test_localization_fallback.py`.
