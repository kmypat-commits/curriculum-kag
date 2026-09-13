# Review gate для orphan-данных SQLite

Последняя read-only проверка выполнена для `backend/curriculum_kag.db`.

- SHA-256 источника: `30af16f8525dc7795522d149e841a9b288efa34486e6b3ef4e8ead3dff1316bb`
- Всего FK-нарушений: `205222`
- `embeddings`: `197343` — вычисляемый слой, допустимо discard + regeneration
- `match_scores`: `7760` — вычисляемый слой, допустимо discard + regeneration
- `bridge_modules`: `115` — строки без `project_versions`; недоступные orphan-артефакты, допустимо discard + regeneration после создания нового плана
- `match_feedback`: `4` — строки без `project_versions`; недоступные orphan-артефакты, допустимо discard + regeneration после создания нового плана

## Решение

Источник нельзя мигрировать без source-specific manifest: мигратор
останавливается до записи в PostgreSQL. Read-only review подтвердил, что из
222 bridge-модулей 107 имеют живые parent-version и мигрируются как обычно;
115 нарушающих FK-строк привязаны к удалённым версиям. Они не могут быть
доступны через UI и не являются самостоятельными пользовательскими планами.
Их, как и orphan `match_feedback`, manifest явно классифицирует как
`discard_and_regenerate`; никакие живые parent-строки не удаляются.

Артефакт полного read-only отчёта создаётся командой:

```powershell
python backend\scripts\build_sqlite_fk_discard_manifest.py `
  --db backend\curriculum_kag.db `
  --output .runtime\sqlite-fk-discard-manifest-current.json
```

После создания manifest с актуальным SHA-256 можно запускать clean-target
migration acceptance. Сравнение таблиц, FK и хешей остаётся обязательным.

Для сохранения полного review evidence до принятия решения используйте
read-only экспорт:

```powershell
python backend\scripts\export_sqlite_orphan_review.py `
  --db backend\curriculum_kag.db `
  --output .runtime\sqlite-orphan-review-archive.json
```

Экспорт не изменяет SQLite и фиксирует SHA-256 источника. Он сохраняет audit
evidence для orphan-строк, исключённых из clean target, но не заменяет итоговую
проверку table/FK/hash после миграции.
