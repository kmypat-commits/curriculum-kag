# Blind rubric для экспертной проверки планов

Эксперты получают одинаковые обезличенные plan IDs и не видят оценки друг
друга, модельный score, источник candidate и итог другого эксперта.

Для каждого обезличенного плана (варианты A/B/C видны внутри одного пакета)
выставляются независимые оценки 1–5:

- `relevance` — соответствие заявленной области, направлению и РО;
- `semester` — обоснованность семестра с учётом пререквизитов и сложности;
- `bridge` — оправданность bridge-модуля и отсутствие подмены реальной дисциплины.

Дополнительно каждый эксперт независимо отмечает:

- `software_validity`: соблюдены ли формальные кредиты, пререквизиты, дубли и семестровые ограничения;
- `content_validity`: соответствует ли содержание дисциплины заявленным компетенциям.

Минимальный формат входа для `backend/scripts/score_expert_rubric.py`:

```json
{
  "items": [
    {
      "anonymous_plan_id": "P-001",
      "expert_a": {"relevance": 4, "semester": 5, "bridge": 4},
      "expert_b": {"relevance": 5, "semester": 4, "bridge": 4},
      "software_validity": {"expert_a": true, "expert_b": true},
      "content_validity": {"expert_a": true, "expert_b": false}
    }
  ]
}
```

Скрипт рассчитывает средние оценки, exact agreement и Cohen’s kappa по каждой
числовой оси, а для `software_validity` и `content_validity` дополнительно
считает exact agreement и Cohen’s kappa по бинарным решениям. Pass-rate и
agreement остаются отдельными показателями; этот отчёт не является
аккредитационным заключением.

## Контролируемая слепая выдача

После успешной acceptance-когорты контролёр готовит два отдельных пакета:

```powershell
python backend/scripts/prepare_expert_rubric_packets.py `
  .runtime/quality-cohort-30.json `
  --output-dir .runtime/expert-review `
  --salt '<секрет только контролёра>'
```

Файлы `expert-a.packet.json` и `expert-b.packet.json` выдаются разным
экспертам. В них нет project/version ID, названия профиля, диагностик поиска,
model score и оценок второго эксперта. Файл
`controller-mapping.private.json` остаётся только у контролёра и не загружается
в общий Git-репозиторий.

После того как оба эксперта независимо заполнят поле `assessment`, контролёр
собирает ввод для расчёта agreement:

```powershell
python backend/scripts/merge_expert_rubric_reviews.py `
  .runtime/expert-a.completed.json .runtime/expert-b.completed.json `
  --output .runtime/expert-review.merged.json
python backend/scripts/score_expert_rubric.py .runtime/expert-review.merged.json `
  --output .runtime/expert-review.score.json
```

Реальные экспертные оценки не подменяются тестовыми данными: до их получения
QA-02 считается подготовленной, но не завершённой.
