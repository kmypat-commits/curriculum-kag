# План нормализации переводов в SQLite

Дата аудита: 2026-07-25.

## Обновление PostgreSQL 29 июля 2026 года

- Основным runtime-источником стала таблица PostgreSQL `course_localizations`.
- Для всех 21 525 дисциплин присутствуют строки `ru`, `kk`, `en`; пропусков 0.
- После миграции дозаполнено 2 212 строк: 2 185 проверенных источником
  ЕПВО/legacy и 27 явно помеченных `draft`.
- Новые переводы, полученные при одобрении дисциплин ЕПВО, записываются
  транзакционно в PostgreSQL и больше не переписывают 58-МБ JSON.
- Batch API и scoring сначала читают PostgreSQL. Legacy JSON загружается только
  при фактическом отсутствии строки в БД.
- Полная пакетная выборка 21 525 дисциплин заняла 3,582 секунды и не прочитала
  JSON ни разу (`cache misses = 0`).
- Аудитор `backend/scripts/audit_course_localizations.py` теперь работает и с
  SQLite, и с PostgreSQL и возвращает ненулевой exit-code при любом пропуске.
- Скрипт `backend/scripts/sync_course_localizations.py` безопасно добавляет
  только недостающие локализации, не перезаписывая существующие записи.
- Восстановлены 240 значений с повреждённым символом `�`: 239 — из чистых
  дублей raw/normalized EPVO по source key, названию или `subjectid`; одна
  строка «объектілі-бағытталған» реконструирована по RU/EN-контексту и оставлена
  со статусом `draft`. Непроверенных `needs_review` после восстановления нет.
- Аудитор теперь проверяет одновременно полноту языков и отсутствие mojibake.

## Выполнено 2026-07-25

- Добавлена ORM-модель `CourseLocalization`.
- Создана таблица `course_localizations`.
- Перед изменением создан rollback-файл SQLite:
  `backups/translation-migration/curriculum_kag_before_course_localizations_2026-07-25_15-55-30.db`.
- Перенесены переводы из ЕПВО и старого `backend/data/course_translations.json`.
- В таблице `course_localizations`: 62180 записей.
- API репозитория дисциплин и API планов читают `title_translations`, `description_translations`, `translation_status` из SQLite-таблицы `course_localizations` с fallback на старый JSON.
- При переиндексации ЕПВО новые утверждённые дисциплины дополнительно сохраняют локализации в SQLite.
- Во фронте сохранён переключатель показа описаний дисциплин в плане; блок описания в репозитории показывает RU/KK/EN.
- Добавлен аудит пропущенных локализаций: `backend/scripts/audit_course_localizations.py`.
- Добавлено заполнение безопасных draft-заглушек для не-ЕПВО дисциплин: `backend/scripts/fill_missing_course_localization_drafts.py`.
- После заполнения draft-заглушек все 20782 дисциплины имеют строки `ru`, `kk`, `en`.
- Добавлено улучшение draft-переводов для ГОСО, bridge, AI-confirmed и части ЕПВО без английского названия:
  `backend/scripts/improve_draft_course_localizations.py`.
- Все 166 draft-строк обновлены источником `rule_based_draft`. Статус оставлен `draft`, потому что это не экспертная верификация.
- Syllabus API теперь отдаёт `title_translations` и `description_translations` для дисциплин, а также локализованные названия пререквизитов и постреквизитов.
- Экран `Сравнить с ЕПВО` теперь получает `title_translations`/`description_translations` для типовых и приоритетных дисциплин.
- Добавление приоритетных дисциплин из ЕПВО сохраняет локализации в SQLite.
- Excel-экспорт плана использует локализованное название дисциплины из `course_localizations`.

Распределение:

| Язык | Записей |
| --- | ---: |
| `ru` | 20733 |
| `kk` | 20733 |
| `en` | 20714 |

Финальное состояние после draft-дозаполнения:

| Статус | Записей |
| --- | ---: |
| `verified` | 62180 |
| `draft` | 166 |

Пропущенные локализации:

| Язык | Пропущено |
| --- | ---: |
| `ru` | 0 |
| `kk` | 0 |
| `en` | 0 |

Все перенесённые записи имеют статус `verified`, так как они пришли из ЕПВО/проверенного legacy-слоя.

## Что найдено

- Активная база: `backend/curriculum_kag.db`.
- Тип базы: SQLite.
- Размер базы: около 12.2 GB.
- Таблиц всего: 29.
- Таблиц с явными полями переводов: 4.

## Состояние переводов ЕПВО

| Таблица | Записей | Состояние |
| --- | ---: | --- |
| `epvo_directions` | 125 | `title_ru/title_kk/title_en` заполнены полностью |
| `epvo_groups` | 483 | `title_ru/title_kk/title_en` заполнены полностью |
| `epvo_disciplines_normalized` | 191292 | `title_ru` заполнен полностью, `title_kk` пусто у 18, `title_en` пусто у 695 |
| `syllabus_drafts` | 1 | хранит JSON, не является основным каталогом переводов |

Полный машинный паспорт сохранён:

- `backend/experiment-results/translation-audit/translation_passport.json`
- `backend/experiment-results/translation-audit/translation_passport_summary.json`

## Главная проблема

Основная таблица `courses` хранит только:

- `title`
- `description`
- `language`

Отдельных полей `title_ru/title_kk/title_en` и `description_ru/description_kk/description_en` в `courses` нет.

Сейчас часть переводов хранится во внешнем файле:

- `backend/data/course_translations.json`

Это удобно для быстрого старта, но плохо для большой системы: планировщик, репозиторий, экспорт, анализ LO и граф могут брать разные источники названий.

## Целевая схема

Добавить отдельную таблицу переводов дисциплин:

```sql
course_localizations (
  id INTEGER PRIMARY KEY,
  course_id INTEGER NOT NULL,
  language TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  source TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at DATETIME,
  updated_at DATETIME,
  UNIQUE(course_id, language)
)
```

Рекомендуемые значения:

- `language`: `ru`, `kk`, `en`
- `source`: `epvo`, `machine`, `manual`, `goso`
- `status`: `verified`, `draft`, `needs_review`

## Порядок работ

1. Сделать backup SQLite. Выполнено.
2. Добавить миграцию `course_localizations`. Выполнено.
3. Перенести проверенные переводы из `course_translations.json`. Выполнено.
4. Связать `courses` с `epvo_disciplines_normalized` по `course_id = EPVO-{id}` и перенести `title_ru/title_kk/title_en`. Выполнено.
5. Для пустых переводов создать `draft`, не перезаписывая `verified`. Выполнено.
6. Переделать API репозитория и планов: отдавать `title_translations` и `description_translations` из одной таблицы. Выполнено.
7. Во фронте добавить переключение/просмотр описания на 3 языках. Выполнено для планов, репозитория, силлабуса, сравнения с ЕПВО и XLSX-экспорта.
8. После стабилизации решить вопрос PostgreSQL: переносить уже очищенную структуру, а не текущий смешанный слой.

## Правило качества

Проверенный перевод из ЕПВО имеет приоритет выше машинного. Машинный перевод можно показывать пользователю, но он должен быть явно помечен как `draft`.
