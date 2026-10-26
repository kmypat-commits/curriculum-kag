from dataclasses import replace
from types import SimpleNamespace

from app.planner.joint_contract import Candidate, PlanningProblem
from app.planner.joint_solver import solve_joint
from app.planner.verifier import _ict_competency_audit


def test_competency_blocks_use_the_same_canonical_titles_as_final_verification():
    from app.planner.joint_frontier import ict_competency_blocks
    titles = {1: 'Программирование', 2: 'Базы данных', 3: 'Компьютерные сети',
              4: 'Информационная безопасность', 5: 'Искусственный интеллект',
              6: 'Управление проектами', 7: 'Общая дисциплина'}
    constraints = {'direction_code': '6B061', 'education_level': 'bachelor'}
    blocks = ict_competency_blocks(titles, constraints)
    assert len(blocks) == 6
    for block in blocks:
        assert block.min_courses == 1
        assert block.min_credits == 0
        assert 7 not in block.course_ids
    picked = {cid for block in blocks for cid in block.course_ids}
    assert _ict_competency_audit([SimpleNamespace(title=titles[cid]) for cid in picked], constraints)['passed']
    assert ict_competency_blocks(titles, {'direction_code': '6B081', 'secondary_direction_code': '6B061'}) == ()


def test_solver_keeps_security_instead_of_repeated_high_scoring_electives():
    from app.planner.joint_frontier import ict_competency_blocks
    def course(cid, title, score):
        return Candidate(cid, {'course_id': cid, 'title': title, 'credits': 5},
                         (1,), (), {'LO1': score}, (1., 0.), score)
    candidates = (
        course(1, 'Программирование; базы данных; компьютерные сети; искусственный интеллект; управление проектами', .95),
        course(2, 'Информационная безопасность', .55),
        course(3, 'Общий аналитический курс', .9),
    )
    setup = PlanningProblem(candidates, {1: []}, ('LO1',), 10, 0, 10, 10,
                            (0., 0.), {}, False, variant_strategy='A')
    blocks = ict_competency_blocks({c.course_id: c.item['title'] for c in candidates}, {'direction_code': '6B061'})
    selected = solve_joint(replace(setup, required_core_blocks=blocks), time_limit_seconds=5)
    assert selected.selected_course_ids == frozenset({1, 2})
