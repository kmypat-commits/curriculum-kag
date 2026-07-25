# Контур GNN/LSTM-эксперимента

Каталог не содержит фиктивных весов или результатов. Эксперимент запускается только после появления проверенного датасета.

JSONL содержит одну программу на строку. Обязательны: program_id, university_id, courses, prerequisite_edges, program_learning_outcomes, source, snapshot_date, license_or_permission. Каждая дисциплина содержит code, title, semester, credits и learning_outcomes.

Разделение train/validation/test выполняется целиком по program_id. Одна программа и её версии не должны попадать в разные части.

План сравнения:

- базовые методы: частоты, BM25/SBERT, топологический планировщик;
- GNN: прогноз пререквизитных рёбер и связей LO–дисциплина;
- LSTM/Transformer: прогноз следующей дисциплины.

Обязательные артефакты: датасет, split manifest, конфигурация, seed, код, веса, журнал обучения и метрики.

Запуск подготовки:

    .\venv\Scripts\python.exe scripts\prepare_ml_dataset.py --input path\programs.jsonl

Результат появится в experiment-results/ml-dataset.
