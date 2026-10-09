from types import SimpleNamespace


def test_cyrillic_cefr_levels_are_kept_distinct_for_copied_language_descriptions():
    text = 'Развитие коммуникативных компетенций и навыков устного и письменного общения.'
    rows = [course(1, 'Казахский (руский) язык 1 (А2)', text),
            course(2, 'Казахский (руский) язык 1 (А1)', text),
            course(3, 'Английский язык (В1)', text),
            course(4, 'Английский язык (В2)', text)]
    assert evaluate(rows, content_vectors={c.id: {'model': 'local', 'vector': [1, 0]}
                                         for c in rows})['duplicate_groups'] == []


def test_instruction_language_note_does_not_turn_ecology_into_language_support():
    from app.planner.content_evaluation import assess_course
    row = assess_course({'title': '6B05203 Экология и природопользование'}, course(30200,
        'Окружающая среда и устойчивое развитие Казахстана (на ангийском языке)',
        'Краткая физико-географическая характеристика Казахстана; влияние загрязнения на окружающую '
        'среду Казахстана; экологические последствия деятельности человека; зоны экологической '
        'катастрофы и экологического бедствия; охрана окружающей среды в Республике Казахстан; '
        'международное и региональное сотрудничество Казахстана в интересах устойчивого развития общества.'))
    assert row['role'] == 'professional'
    assert row['status'] == 'supported'


def test_geographic_kazakhstan_reference_does_not_imply_kazakh_language_target():
    rows = [course(1, 'Иностранный язык для специалистов Казахстана',
                   'Развитие навыков межкультурной деловой коммуникации в профессиональной деятельности.'),
            course(2, 'Иностранный язык для специалистов',
                   'Развитие навыков межкультурной деловой коммуникации в профессиональной деятельности.')]
    result = evaluate(rows)
    assert len(result['duplicate_groups']) == 1
    assert result['duplicate_groups'][0]['course_ids'] == [1, 2]


def test_western_and_unspecified_foreign_languages_keep_distinct_target_categories():
    text = 'Формирование навыков межкультурного делового общения и профессиональной коммуникации.'
    assert evaluate([course(1, 'Иностранный язык: западные языки', text),
                     course(2, 'Иностранный язык', text)])['duplicate_groups'] == []


def test_copied_language_descriptions_do_not_override_target_language_in_title():
    text = 'Развитие межкультурного делового общения и письменной профессиональной коммуникации.'
    rows = [course(1, 'Профессиональный иностранный язык', text),
            course(2, 'Профессиональный казахский (русский) язык', text),
            course(3, 'Английский язык B1', text),
            course(4, 'Немецкий язык B1', text)]
    result = evaluate(rows, content_vectors={c.id: {'model': 'local', 'vector': [1, 0]} for c in rows})
    assert result['duplicate_groups'] == []


def test_professional_kazakh_russian_is_supporting_outside_language_programme():
    result = evaluate([course(1, 'Профессиональный казахский (русский) язык',
        'Деловая коммуникация в производстве изделий из древесины и деревообработке.')])
    assert result['courses'][0]['role'] == 'supporting'
    assert result['courses'][0]['priority_adjustment'] == 0


def test_generic_culture_in_other_subject_does_not_earn_culturology_priority():
    from app.planner.content_evaluation import evaluate_content
    rows = [course(1, 'Основы экологии', 'Формирование экологической культуры и охрана окружающей среды.'),
            course(2, 'Противодействие коррупции', 'Формирование антикоррупционной культуры и изучение законодательства.'),
            course(3, 'Теория культуры', 'Изучение культурологических теорий и методов анализа культурных процессов.')]
    result = evaluate_content(profile={'title': '6В03102 Культурология'}, courses=rows, schedule={})
    assert [r['status'] for r in result['courses']] == ['needs_review', 'needs_review', 'supported']
    assert [r['priority_adjustment'] for r in result['courses']] == [0, 0, .15]


def test_language_of_art_is_not_misclassified_as_foreign_language_support():
    from app.planner.content_evaluation import assess_course
    row = assess_course({'title': 'Культурология'}, course(1, 'Язык искусства',
        'Семиотика искусства и теория культуры в анализе художественных произведений.'))
    assert row['role'] == 'professional'
    assert row['status'] == 'supported'


def test_named_cultural_subject_retains_priority_with_substantive_cultural_evidence():
    from app.planner.content_evaluation import assess_course
    row = assess_course({'title': 'Культурология'}, course(1, 'Культура Ренессанса',
        'Изучение культуры эпохи Возрождения, художественных традиций и общественных изменений.'))
    assert row['status'] == 'supported'
    assert row['priority_adjustment'] == .15


def test_snapshot_survives_publication_metadata_and_row_order_but_detects_real_edits():
    from app.planner.content_evaluation import evaluate_content
    courses = [course(1, 'Обработка древесины', 'Технология обработки древесины.'),
               course(2, 'Изделия из древесины', 'Проектирование изделий из древесины.')]
    def report(schedule):
        return evaluate_content(profile={'title': 'Деревообработка'}, courses=courses, schedule=schedule)
    before = report({1: [{'course_id': 1, 'credits': 5, 'title': 'Обработка древесины', 'score': .8},
                         {'course_id': 2, 'credits': 5, 'title': 'Изделия из древесины'}]})
    saved = {1: [{'course_id': 2, 'bridge_module_id': None, 'credits': 5, 'prerequisites': []},
                 {'course_id': 1, 'bridge_module_id': None, 'credits': 5, 'prerequisites': []}]}
    assert before['snapshot_hash'] == report(saved)['snapshot_hash']
    saved[1][0]['credits'] = 4
    assert before['snapshot_hash'] != report(saved)['snapshot_hash']


def course(cid, title, description='', **kw):
    return SimpleNamespace(id=cid, course_id=f'EPVO-{cid}', title=title,
                           description=description, topics=[], learning_outcomes=[],
                           assessment_methods=[], domain='Производство', credits=5,
                           language='ru', **kw)


def evaluate(courses, **kw):
    from app.planner.content_evaluation import evaluate_content
    return evaluate_content(profile={'title': 'Технология деревообработки',
                                    'goal': 'Проектировать изделия из древесины',
                                    'learning_outcomes': {'ON1': 'Обработка древесины'}},
                            courses=courses, schedule={1: [{'course_id': c.id, 'credits': 5}
                                                        for c in courses]}, **kw)


def test_profile_mismatch_is_explained_even_when_semantic_score_is_high():
    result = evaluate([course(1, 'Металлургия', 'Обработка металлов и производство стали.')],
                      lo_scores={1: {'ON1': .9}})
    row = result['courses'][0]
    assert row['status'] == 'profile_mismatch'
    assert row['evidence'][0]['excerpt'] in 'Обработка металлов и производство стали.'
    assert row['evidence'][0]['source_reference'] == 'EPVO-1'
    assert result['indicators']['profile_mismatch_count'] == 1
    assert 'overall_score' not in result


def test_missing_content_and_support_do_not_claim_professional_coverage():
    result = evaluate([course(1, 'Деревообработка'),
                       course(2, 'Иностранный язык', 'Деловая коммуникация на иностранном языке.')],
                      lo_scores={1: {'ON1': .9}, 2: {'ON1': .9}},
                      core_blocks=[{'id': 'wood', 'title': 'Деревообработка',
                                    'min_courses': 1, 'min_credits': 5}])
    assert result['courses'][0]['status'] == 'insufficient_data'
    assert result['courses'][1]['role'] == 'supporting'
    assert result['core_coverage'][0]['status'] == 'unconfirmed'


def test_same_content_warns_but_different_levels_are_not_equivalent():
    from app.planner.content_evaluation import evaluate_content
    text = 'Обработка древесины. Проектирование изделий из древесины.'
    rows = [course(1, 'Обработка древесины', text), course(2, 'Технология древесины', text),
            course(3, 'Обработка древесины II', text)]
    result = evaluate(rows)
    assert any(set(x['course_ids']) == {1, 2} for x in result['duplicate_groups'])
    assert not any(3 in x['course_ids'] for x in result['duplicate_groups'])
    assert all(x['status'] == 'needs_review' for x in result['duplicate_groups'])


def test_snapshot_changes_for_content_schedule_and_profile():
    a = evaluate([course(1, 'Обработка древесины', 'Обработка древесины и изделий.')])
    b = evaluate([course(1, 'Обработка древесины', 'Другие технологии.')])
    assert a['snapshot_hash'] != b['snapshot_hash']


def test_prerequisite_order_is_reported_with_schedule_evidence():
    result = evaluate([course(1, 'Обработка древесины', 'Обработка древесины.')],
                      prerequisites={1: [2]})
    assert result['sequence_findings'][0]['reason'] == 'missing_prerequisite'
    assert result['sequence_findings'][0]['course_id'] == 1


def test_shadow_preserves_ranking_and_prioritise_uses_content_without_changing_lo():
    from app.planner.content_evaluation import prioritise_candidates
    from app.planner.joint_contract import Candidate
    courses = {1: course(1, 'Деревообработка', 'Обработка древесины и изделий.'),
               2: course(2, 'Металлургия', 'Обработка металлов и производство стали.')}
    profile = {'title': 'Деревообработка', 'goal': 'Обработка древесины'}
    candidates = tuple(Candidate(cid, {'title': c.title, 'credits': 5}, (1,), (),
                                 {'ON1': .9}, (1, 0), .9) for cid, c in courses.items())
    assert prioritise_candidates(candidates, courses, profile, mode='shadow') == candidates
    selected = prioritise_candidates(candidates, courses, profile, mode='prioritise')
    assert selected[0].utility > selected[1].utility
    assert selected[0].lo_scores == {'ON1': .9}
    assert len(selected) == 2


def test_generic_lo_words_and_high_similarity_do_not_prove_professional_relevance():
    result = evaluate([course(1, 'Управление качеством продукции',
                              'Контроль качества продукции и технологических процессов.')],
                      lo_scores={1: {'ON1': .9}})
    assert result['courses'][0]['status'] == 'needs_review'
    assert result['courses'][0]['priority_adjustment'] == 0


def test_regulatory_components_do_not_create_false_semantic_duplicate_warnings():
    a = course(1, 'Практика', 'Профессиональная практика и итоговая работа.')
    b = course(2, 'Итоговая аттестация', 'Профессиональная практика и итоговая работа.')
    a.course_id = 'GOSO-KZ-PRACTICE'
    b.course_id = 'GOSO-KZ-FINAL'
    assert evaluate([a, b])['duplicate_groups'] == []


def test_semantic_duplicate_suggestions_use_compatible_vectors_and_keep_levels():
    rows = [course(1, 'История науки', 'Историческое развитие научных идей и подходов.'),
            course(2, 'История научного знания', 'Эволюция научных концепций и методов познания.'),
            course(3, 'История науки II', 'Историческое развитие научных идей и подходов.')]
    result = evaluate(rows, content_vectors={1: {'model': 'local', 'vector': [1, 0]},
                                            2: {'model': 'local', 'vector': [1, .01]},
                                            3: {'model': 'local', 'vector': [1, 0]}})
    assert any(set(g['course_ids']) == {1, 2} and g['reason'] == 'similar_content_embedding'
               for g in result['duplicate_groups'])
    assert not any(3 in g['course_ids'] for g in result['duplicate_groups'])


def test_corrupt_optional_embedding_does_not_prevent_content_review():
    rows = [course(1, 'История науки', 'История научных идей и подходов.'),
            course(2, 'История научного знания', 'Развитие научных методов познания.')]
    result = evaluate(rows, content_vectors={1: {'model': 'local', 'vector': ['corrupt']},
                                            2: {'model': 'local', 'vector': [1]}})
    assert result['indicators']['reviewed_courses'] == 2
    assert result['duplicate_groups'] == []
    assert result['embedding_findings'][0]['reason'] == 'invalid_embedding'


def test_generic_programme_goal_does_not_validate_unrelated_food_course():
    from app.planner.content_evaluation import evaluate_content
    result = evaluate_content(profile={
        'title': 'Проектирование изделий из древесины',
        'goal': 'Фундаментально образованные специалисты для научного и социального развития национального производства.',
        'learning_outcomes': {}}, courses=[course(7, 'Испытание муки и кондитерских изделий',
        'Научные исследования пищевой продукции для социального развития национального производства.')], schedule={})
    assert result['courses'][0]['status'] == 'needs_review'
    assert result['courses'][0]['priority_adjustment'] == 0
