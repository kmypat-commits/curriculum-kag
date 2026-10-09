from types import SimpleNamespace


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
