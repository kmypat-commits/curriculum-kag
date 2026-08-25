# Полный programme-level dataset EPVO — 25.08.2026

Полный экспорт выполнен из PostgreSQL shadow-базы без ограничения числа
программ. Артефакт находится вне Git в
`backend/.runtime/epvo-ranking-postgres-full/` и содержит `programs.jsonl`,
`course_lo_pairs.jsonl` и `manifest.json`.

Команда воспроизведения:

```powershell
$env:DATABASE_URL = "postgresql://curriculum_user:curriculum_pass@localhost:5433/curriculum_kag_shadow"
python backend/scripts/export_epvo_ranking_dataset_postgres.py `
  --database-url $env:DATABASE_URL `
  --output backend/.runtime/epvo-ranking-postgres-full `
  --max-programmes 0 `
  --min-labelled-links 1
```

Результат manifest:

| Показатель | Значение |
|---|---:|
| Программы | 11 017 |
| Train / validation / test | 7 706 / 1 650 / 1 661 |
| Строк course–LO | 833 022 |
| Положительные связи | 615 414 |
| Без экспертной оценки | 89 284 |
| Сильная экспертная оценка 1,0 | 468 852 |
| Средняя оценка 0,5 | 244 975 |
| Промежуточные оценки 0,25–0,8333 | 20 094 |

Оценки экспертов сохранены как непрерывная шкала, а не бинаризованы:
`0`, `0,5`, `1` и исторические промежуточные значения. Split назначается на
уровне программы, поэтому связи одной программы не попадают одновременно в
train и test.

Важно: прежние числа Recall@10 (например, 0,6099) относятся к отдельному
быстрому benchmark-срезу из 1 822 программ. Полный export теперь готов;
потоковый reranking benchmark выполнен без удержания 1,2 ГБ JSONL в памяти.
На 67 пригодных validation-программах/564 запросах streaming HashingTF-IDF с
train-only anchor дал Recall@10=0,5832; на 67 test-программах/562 запросах —
0,6098 (лучший anchor weight 0,35). MRR test составил 0,6380. Результат близок
к прежнему baseline и не даёт основания менять production reranker.
