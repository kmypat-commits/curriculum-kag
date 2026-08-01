# Инвентаризация моделей

Проверено 2026-08-01. Ничего не удалялось.

## Используется приложением

- `backend/models/paraphrase-multilingual-mpnet-base-v2` — базовая embedding-модель KAG (`EMBEDDING_MODEL_NAME`).
- `backend/models/epvo-sbert-mined-triplets-6k` — текущий ranker по умолчанию (`EPVO_RANKER_MODEL_NAME`).
- `backend/models/epvo-sbert-finetuned-40k` — benchmark/экспериментальная модель, используется отдельными скриптами и может быть размещена во внешнем model storage.

## Экспериментальные артефакты

`*-checkpoints` и остальные каталоги `epvo-sbert-*` — промежуточные результаты обучения. Они не подключаются runtime-конфигурацией. Их безопасно сначала переместить в архив после проверки метрик и контрольных сумм.

Размеры на момент аудита: базовая модель около 10.1 GB; большинство checkpoint-каталогов около 2.7 GB каждый. Удалять их автоматически нельзя: сначала сохранить manifest, SHA-256 и лучший benchmark.

## Правило публикации

GitHub содержит код и LFS-датасет переводов. Большие модели публикуются отдельно (object storage/model registry), а в `.env.production` задаётся путь или URL после ручной проверки checksum. Развёртывание без модели должно явно переходить на базовый multilingual fallback.
