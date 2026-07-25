# Рисунки и скриншоты для статьи

## Скриншоты интерфейса

1. `S01_wizard_epvo_directions.png` — мастер: уровень, тип программы, два направления/группы и квоты.
2. `S02_goal_lo_suggestions.png` — предложения целей и LO, tooltip с полным LO.
3. `S03_plan_variants_abc.png` — разные A/B/C, 240 кредитов, выбор активного варианта.
4. `S04_why_selected.png` — «Почему выбрана?», AI/EPVO score и экспертная обратная связь.
5. `S05_prerequisite_graph.png` — граф по семестрам и результаты обучения семестра.
6. `S06_lo_coverage_sources.png` — real/bridge/weak coverage.
7. `S07_bridge_replacement.png` — кандидаты ЕПВО и «Добавить в проект».
8. `S08_international_quality.png` — чек-лист и кнопка исправления.
9. `S09_compare_epvo.png` — сравнение с похожими программами ЕПВО.
10. `S10_dataset_passport.png` — объёмы, split, seed, checksum.
11. `S11_model_benchmark.png` — SBERT/GNN/LSTM/ranking metrics.
12. `S12_course_syllabus.png` — тематический план по неделям.

## Научные схемы

1. `fig01_curriculum_kag_architecture.pdf` — общая архитектура.
2. `fig02_epvo_data_pipeline.pdf` — raw → normalized → approved → candidates.
3. `fig03_nsga2_pareto.pdf` — Парето-фронт A/B/C.
4. `fig04_two_stage_model.pdf` — classifier + reranker.
5. `fig05_human_feedback_loop.pdf` — human-in-the-loop.
6. `fig06_verified_plan_regression.pdf` — проверенные изменения качества трёх контрольных программ.
7. `fig07_aggregated_domain_evidence.pdf` — агрегация происхождения дедуплицированной дисциплины и доменные квоты.
8. `fig08_transactional_abc_semester_graph.pdf` — атомарная генерация A/B/C и семестровый граф пререквизитов.

Полные промпты для генерации схем находятся в приложении B файла `Curriculum_KAG_EPVO_RU.tex`.

## Требования к оформлению

- схемы лучше сохранять в PDF/SVG;
- скриншоты — PNG, ширина от 1600 px;
- единый светлый фон;
- скрыть персональные данные и лишние project ID;
- не использовать декоративные «ИИ-мозги», роботов и неон;
- подписи и легенды должны читаться после уменьшения до ширины журнальной колонки.
