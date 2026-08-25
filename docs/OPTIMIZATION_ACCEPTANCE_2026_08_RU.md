# Acceptance-чеклист оптимизации Curriculum-KAG

Снимок: 25.08.2026, после commit `3b55f43`. Статусы отражают проверяемое состояние,
а не намерение.

| № | Требование | Статус | Доказательство / остаток |
|---:|---|---|---|
| 1 | Retrieval, ranking и assembly вынесены из planner-фасада | Улучшено, частично закрыто | `candidate_retrieval.py`, `variant_ranking.py`, `variant_assembly.py`, `variant_diversification.py`, `variant_policy.py`; `variant_strategy.py` остаётся большим оркестратором и требует следующего AST-прохода |
| 2 | Semester repair разделён по ответственности | Закрыто | `semester_load_repair.py`, `semester_domain_repair.py`, `semester_appropriateness.py`, `course_scheduling.py`; regression 72/72 |
| 3 | Fail-fast EPVO/LO evidence | Закрыто | `evidence_preflight.py`; дефицит возвращается до долгого scheduler и не маскируется bridge |
| 4 | Project 135 пересобирается только после восстановления evidence | Защищено | Сборка блокируется при дефиците профессиональных LO-связей; пересборка намеренно не запускалась |
| 5 | Browser smoke graph + RU/KK/EN | Частично закрыто | HTTP smoke 10 маршрутов и RU/KK/EN markers; интерактивный graph smoke требует ручного входа |
| 6 | Progress генерации в PostgreSQL | Закрыто | `plan_build_status` и `planner_state`; Alembic head на PostgreSQL |
| 7 | Checksum-кэш EPVO/LO | Закрыто | stage cache инвалидируется при in-place checksum/fingerprint изменении; тесты проходят |
| 8 | Узкие исключения | Закрыто | В production-коде осталось 2 `except Exception`, оба только на transaction rollback boundaries |
| 9 | Lock-файлы | Закрыто | `backend/requirements.lock`, `frontend/package-lock.json`; dependency profile gate проходит |
| 10 | Programme-level dataset и Recall@10 ≥ 0,80 | В работе | полный export: 11 017 программ, 833 022 edge (train/validation/test=7 706/1 650/1 661); streaming full validation=0,5832 (67 программ/564 запроса), test=0,6098 (67/562, MRR=0,6380); SBERT 40k all-language validation=0,5829, test=0,6137; RU-only validation=0,5914, test=0,6172; graded-anchor validation=0,5814; exact course–LO overlap между train/held-out=0% — кандидаты ниже целевого порога, production не менялся |
| 11 | PostgreSQL restore + Alembic в CI | Закрыто | CI service `pgvector/pgvector:pg16`, endpoint contracts, isolated restore gate; локально сохранён verified backup manifest |
| 12 | Staging backup/manifest/tag/runbook | Частично закрыто | backup manifest, `staging-manifest.json`, runbook и guarded tag script готовы; tag ждёт ручной browser smoke |

## Release gate

Текущие проверки: backend **72/72**, static gate, dependency profile, release
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
