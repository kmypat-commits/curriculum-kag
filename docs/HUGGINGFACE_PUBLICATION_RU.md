# Публикация Curriculum-KAG на Hugging Face

## Рекомендуемые репозитории

1. `curriculum-kag-ceer-sbert-40k` — тип **Model**.
2. `curriculum-expert-evidence-repository` — тип **Dataset**.
3. `curriculum-kag-demo` — тип **Docker Space**.

Их лучше создать от имени отдельной Hugging Face Organization, чтобы будущие соавторы и университетские администраторы получали роли без передачи личного токена владельца.

## Model repository

Публикуется только подтверждённый production checkpoint, а не каталог `backend/models` целиком:

```text
README.md             <- MODEL_CARD.md
config.json
config_sentence_transformers.json
modules.json
sentence_bert_config.json
special_tokens_map.json
tokenizer.json
tokenizer_config.json
vocab / sentencepiece assets
model.safetensors
checksums.sha256
benchmark.json
```

До загрузки сверить, что модель открывается локально через `SentenceTransformer`, а frozen benchmark совпадает с Model Card.

## Dataset repository

Полный PostgreSQL dump не является основным публичным форматом. Для научного использования экспортируются версионированные Parquet-таблицы и `dataset_passport.json`. PostgreSQL dump может прилагаться отдельно только для разрешённой demo/research-версии.

Пока юридический статус распространения не зафиксирован, Dataset repository должен быть private/gated либо содержать только демонстрационный набор без персональных и ограниченных данных.

## Docker Space

Space использует обезличенную demo-базу. Production-пароли, пользовательские проекты и полный институциональный PostgreSQL туда не загружаются. Секреты задаются в Settings → Variables and secrets.

Минимальная карточка Space должна сообщать:

- это исследовательская демонстрация;
- внешняя AI API необязательна;
- план требует экспертного утверждения;
- ресурсоёмкая генерация может занимать несколько минут;
- ссылки на GitHub, Model Card, Dataset Card и статью.

## Версионирование

Один научный релиз должен фиксировать совместимую тройку:

```text
app_version + dataset_version + model_version
```

Для всех файлов публикуются SHA-256. Тег GitHub и revisions Hugging Face указываются в статье, чтобы рецензент мог воспроизвести именно использованный эксперимент.
