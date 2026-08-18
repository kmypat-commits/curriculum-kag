# Baseline качества Curriculum-KAG — 17.08.2026

Этот документ фиксирует исходное состояние перед дальнейшей стабилизацией
генератора. Он не подменяет проверку качества конкретной новой программы.

## Неизменяемый снимок

- SQLite backup: `backups/baseline-2026-08-17/curriculum_kag.db`;
- SHA-256: `8ef438fccf82cca18efddc0850534ffe55f04c03ad90951fcb9b8dad730c29a4`;
- статус SHA-256: `ok`;
- глубокий `PRAGMA quick_check`: намеренно `skipped`, так как файл 11.45 GB
  и его запуск создаёт длительную нагрузку на рабочий компьютер.

## Контрольный аудит планов

Скрипт: `backend/scripts/capture_baseline.py`.

| Проверка | Результат |
| --- | ---: |
| Контрольных проектов | 5 |
| Проектов с неразличимыми A/B/C | 0 |
| Планов с дубликатами | 0 |
| Планов с нарушением пререквизитов | 0 |
| Планов с нарушением доменной квоты | 0 |
| Планов без достаточного admission evidence | 9 |

Последняя строка — не успешный результат: старые варианты с отсутствующим
`course_admission` должны быть пересобраны. Новое финальное правило
планировщика не позволяет сохранить вариант с hard violation или с LO без
подтверждения реальной дисциплиной вместо старого плана.

## Локализация репозитория дисциплин

Скрипт: `backend/scripts/audit_course_localizations.py`.

| Проверка | Результат |
| --- | ---: |
| Карточек дисциплин | 20 782 |
| Полные RU/KK/EN-карточки | 20 782 |
| Повреждённые текстовые значения | 0 |
| Неустранимые fallback описаний | 0 |
| Направлений ЕПВО с переводами | 125/125 |
| Групп ОП ЕПВО с переводами | 483/483 |

Статусы переводов: 62 065 `verified`, 167 `draft`, 114 `needs_review`.
`draft` и `needs_review` не должны маркироваться в интерфейсе как
экспертно подтверждённый перевод.

## Воспроизведение

```powershell
python backend/scripts/capture_baseline.py --reuse-backup --skip-quick-check `
  --output backups/baseline-2026-08-17

python backend/scripts/audit_course_localizations.py `
  --database-url sqlite:///D:/curriculum-kag/curriculum-kag/backend/curriculum_kag.db `
  --output .runtime/course-localization-baseline-2026-08-17.json
```

Для запуска на этом компьютере используется Python из `start.ps1` или
поставляемого runtime; системная команда `python` может отсутствовать.
