# Acceptance-чеклист оптимизации Curriculum-KAG

Снимок: 25.08.2026, после текущего рефакторинга. Статусы отражают проверяемое состояние,
а не намерение.

| № | Требование | Статус | Доказательство / остаток |
|---:|---|---|---|
| 1 | Retrieval, ranking и assembly вынесены из planner-фасада | Улучшено, частично закрыто | `candidate_retrieval.py`, `variant_scope.py`, `variant_ranking.py`, `variant_assembly.py` (real-EPVO top-up и атомарные сборки), `variant_quota.py`, `variant_coverage.py`, `variant_prerequisites.py`, `variant_admission.py`, `variant_diversification.py`, `variant_policy.py`, `variant_replacements.py`, `variant_repairs.py`, `variant_lo_repair.py`, `variant_domain_repair.py`, `admission.py`; scope retrieval, admission, quota safety, LO-coverage, prerequisite, credit-repair, professional LO-gap, domain-quota и bridge-логика вынесены, `variant_strategy.py` остаётся оркестратором финальной сборки |
| 2 | Semester repair разделён по ответственности | Закрыто | `semester_load_repair.py` (кредиты), `semester_domain_repair.py` (области), `semester_appropriateness.py` (уместность), `semester_admission_repair.py` (финальный допуск/пререквизиты), `course_scheduling.py`; regression 91/91 |
| 3 | Fail-fast EPVO/LO evidence | Закрыто | `evidence_preflight.py`; дефицит возвращается до долгого scheduler и не маскируется bridge |
| 4 | Project 135 пересобирается только после восстановления evidence | Защищено | Сборка блокируется при дефиците профессиональных LO-связей; пересборка намеренно не запускалась |
| 5 | Browser smoke graph + RU/KK/EN | Улучшено, частично закрыто | UI smoke 10 маршрутов, RU/KK/EN markers, optional OpenAPI-проверка и безопасный `scripts/authenticated-api-smoke.ps1`; интерактивная проверка отображения графа и переключения языков требует ручного входа |
| 6 | Progress генерации в PostgreSQL | Закрыто | `plan_build_status` и `planner_state`; Alembic head на PostgreSQL |
| 7 | Checksum-кэш EPVO/LO | Закрыто | stage cache инвалидируется при in-place checksum/fingerprint изменении; тесты проходят |
| 8 | Узкие исключения | Закрыто | В production-коде осталось 2 `except Exception`, оба только на transaction rollback boundaries |
| 9 | Lock-файлы | Закрыто | `backend/requirements.lock`, `frontend/package-lock.json`; dependency profile gate проходит |
| 10 | Programme-level dataset и Recall@10 ≥ 0,80 | В работе | полный export: 11 017 программ, 833 022 edge (train/validation/test=7 706/1 650/1 661); streaming full validation=0,5832 (67 программ/564 запроса), test=0,6098 (67/562, MRR=0,6380); SBERT 40k all-language validation=0,5829, test=0,6137; RU-only validation=0,5914, test=0,6172; graded-anchor validation=0,5814; exact course–LO overlap между train/held-out=0% — кандидаты ниже целевого порога, production не менялся. На чистом PostgreSQL-срезе scope-aware title blend дал Recall@10=0,5040 против 0,4953 title-aware (+0,0087), но также ниже порога. Benchmark переведён на held-out streaming, float32, адресное чтение выбранных JSONL offsets и атомарный status-file; полный batch остаётся отдельной длительной задачей. |
| 11 | PostgreSQL restore + Alembic в CI | Закрыто | CI service `pgvector/pgvector:pg16`, endpoint contracts, isolated restore gate; локально сохранён verified backup manifest |
| 12 | Staging backup/manifest/tag/runbook | Частично закрыто | backup manifest, `staging-manifest.json`, runbook и guarded tag script готовы; tag ждёт ручной browser smoke |

## Release gate

Текущие проверки: backend **91/91**, static gate, dependency profile, release
hygiene, frontend production build, PostgreSQL health и Alembic head проходят.
Без ручной авторизации в браузере тег не создаётся намеренно.

### Последний безопасный ranking-проход

Проверены два leakage-safe варианта. Scope-anchor использует только train-данные
того же направления/группы ОП и получил Recall@10=0,5683 на validation;
scope-membership получил 0,4778. Малый supervised pair-ranker (300 train-программ,
37 700 пар) получил 0,5485. Все варианты ниже выбранного fuzzy baseline 0,5848,
поэтому в production ничего не заменялось. Это отрицательный, но воспроизводимый
результат: для следующего улучшения нужны более качественные programme-level
признаки/кросс-энкодер, а не ручное повышение веса эвристики.
Раздельный RU/KK/EN multilingual-max pilot на 19 validation-программах дал
Recall@10=0,5877 против 0,6648 у fuzzy-варианта на той же подвыборке; он также
отклонён.

### 2026-08-25: clean-v3 supervised reranking audit

Добавлен воспроизводимый train-only контрольный эксперимент
`backend/scripts/benchmark_epvo_supervised.py` на полном PostgreSQL clean-v3
с programme-disjoint split. На validation (80 программ, 632 LO-запроса,
300 train-программ, 53 869 пар) получено Recall@10=0,5566, MRR=0,4719,
nDCG@10=0,4284. На независимом test (80 программ, 646 запросов) —
Recall@10=0,5007, MRR=0,4506, nDCG@10=0,3919. Результат устойчиво ниже
ranking-loss кандидата 0,7071 и не продвигается в production. Эксперимент
подтверждает, что простого pair-classifier с TF-IDF-признаками недостаточно;
следующий кандидат должен улучшать programme-level hard-negative/listwise
ранжирование и проверяться на том же полном пуле, а не на оптимистичной
выборке только связанных курсов.

Дополнительная проверка зафиксированного ranking-loss SBERT на том же полном
candidate pool дала validation Recall@10=0,4838 (80 программ, 644 запроса) и
test Recall@10=0,4693 (80 программ, 629 запросов), при MRR=0,3702/0,4040 и
nDCG@10=0,3470/0,3654. Поэтому прежний результат около 0,7071 нельзя
переносить на полный clean-v3 пул: он относится к более узкой legacy-выборке.
Production-реранкер не меняется до появления модели, устойчивой на полном
programme-disjoint test.

Новый clean-v3 multi-positive listwise pilot (1 000 train-групп, 4 411
положительных и 14 916 отрицательных кандидатов, CUDA) дал validation
Recall@10=0,4804 и test Recall@10=0,4773; validation ниже предыдущего
ranking-loss baseline, поэтому артефакт оставлен экспериментальным.
Аудит candidate pool: 629 test-запросов, медиана 26 кандидатов, oracle
Recall@10=0,9348, пересечение programme ID между split=0. Это подтверждает,
что порог 0,80 достижим теоретически, но требует более точного programme-level
hard-negative/listwise ранжирования.

Проверен отдельный lexical-hard-negative режим (1 000 групп; 4 678 позитивов,
14 640 не связанных, но токеново близких кандидатов). Его validation
Recall@10=0,4788, test=0,4752; средний loss=5,12. Улучшение test относительно
предыдущего pilot недостаточно и не подтверждается validation, поэтому режим
не включён автоматически.

Для weighted-проверки programme-level export пересобран напрямую из
PostgreSQL: 1 771 программа, 87 898 positive pairs; сохранены expert strength
1,0 (72 539), 0,5 (44 152), 0,75 (252), 0,25 (5) и unlabeled (5 873).
Graded listwise pilot на 80 одинаковых validation/test программах сравнен с
исходной 40k-моделью: Recall@10=0,4905/0,4946 против 0,4919/0,4928,
а test MRR вырос 0,4030 → 0,4211. Прирост Recall недостаточен для promotion;
кандидат остаётся экспериментальным.
