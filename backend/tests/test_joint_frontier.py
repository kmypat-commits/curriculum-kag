from app.planner import domain_evidence, goso


def test_shared_domain_policy_matches_verifier_for_unscoped_real_courses():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.planner.verifier import verify_curriculum_plan

    domains = ("Информационные технологии", "Общественное здоровье")
    schedule = {
        1: [{"course_id": 100, "title": "IT", "domain": domains[0], "credits": 5}],
        2: [{"course_id": 200, "title": "Health", "domain": domains[1], "credits": 6}],
    }
    version = SimpleNamespace(
        id=1,
        project=SimpleNamespace(
            domain1=domains[0], domain2=domains[1],
            constraints_json={"total_semesters": 2, "total_credits": 11,
                              "max_credits_per_semester": 6},
        ),
        learning_outcomes=[],
    )
    result = verify_curriculum_plan(schedule, version, MagicMock())
    expected = [0.0, 0.0]
    for items in schedule.values():
        for item in items:
            shares = domain_evidence.course_domain_shares(
                item_domain=item["domain"], canonical_domain="",
                project_domains=domains, scoped_shares=None,
            )
            expected[0] += item["credits"] * shares[0]
            expected[1] += item["credits"] * shares[1]
    assert result["domain_credits"] == {
        "domain1": expected[0], "domain2": expected[1],
    }


def test_goso_duplicate_cannot_count_as_professional_lo_support():
    assert hasattr(goso, "is_redundant_goso_foundation")
    is_redundant_goso_foundation = goso.is_redundant_goso_foundation
    item = {
        "course_id": 2422,
        "title": "Основы антикоррупционной культуры, безопасности жизнедеятельности и экологии",
    }
    assert is_redundant_goso_foundation(
        item, is_kz=True, has_legal_goso=True, required_ids=set()
    )
    assert not is_redundant_goso_foundation(
        item, is_kz=False, has_legal_goso=True, required_ids=set()
    )


def test_canonical_domain_overrides_broad_epvo_scope():
    assert hasattr(domain_evidence, "course_domain_shares")
    course_domain_shares = domain_evidence.course_domain_shares
    assert course_domain_shares(
        item_domain="Общественное здоровье",
        canonical_domain="Общественное здоровье",
        project_domains=("Информационные технологии", "Общественное здоровье"),
        scoped_shares=(1.0, 0.0),
    ) == (0.0, 1.0)
    assert course_domain_shares(
        item_domain="Информационные технологии",
        canonical_domain="Информационные технологии",
        project_domains=("Информационные технологии", "Общественное здоровье"),
        scoped_shares=None,
    ) == (1.0, 0.0)


def test_problem_indexes_candidates_by_stable_course_id():
    from app.planner.joint_contract import Candidate, PlanningProblem

    candidate = Candidate(
        course_id=33472,
        item={"course_id": 33472, "credits": 5},
        allowed_semesters=(6, 7),
        prerequisites=(31489, 33539),
        lo_scores={"ON1": 0.568},
        domain_shares=(1.0, 0.0),
        utility=0.568,
    )
    problem = PlanningProblem(
        candidates=(candidate,), fixed_schedule={}, required_los=("ON1",),
        target_credits=240, credit_tolerance=5, min_load=27, max_load=33,
        domain_minima=(0.0, 0.0), exclusions={}, frontier_truncated=False,
    )
    assert problem.candidates_by_id[33472].prerequisites == (31489, 33539)
