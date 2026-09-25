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


def test_frontier_keeps_complete_prerequisite_closure_not_lone_child():
    from app.planner.joint_frontier import prerequisite_closure

    parents = {33472: (31489, 33539), 31489: (31000,), 33539: (), 31000: ()}
    assert prerequisite_closure(33472, parents, set(parents)) == (31000, 31489, 33539, 33472)


def test_frontier_rejects_missing_cycle_and_inadmissible_parent():
    from app.planner.joint_frontier import prerequisite_closure

    assert prerequisite_closure(3, {3: (2,), 2: (1,), 1: (3,)}, {1, 2, 3}) is None
    assert prerequisite_closure(3, {3: (2,)}, {3}) is None
    assert prerequisite_closure(3, {3: (2,), 2: ()}, {3}) is None


def test_21992_shaped_frontier_excludes_goso_duplicate_before_lo_coverage():
    from app.planner.joint_contract import Candidate
    from app.planner.joint_frontier import admit_candidate_chains

    def candidate(course_id, score, parents=()):
        return Candidate(
            course_id=course_id,
            item={"course_id": course_id, "credits": 5},
            allowed_semesters=(1, 2, 3), prerequisites=parents,
            lo_scores={"ON1": score}, domain_shares=(1.0, 0.0), utility=score,
        )

    catalogue = {
        2422: candidate(2422, 0.78),
        33472: candidate(33472, 0.568, (31489, 33539)),
        31489: candidate(31489, 0.0),
        33539: candidate(33539, 0.0),
    }
    frontier, exclusions = admit_candidate_chains(
        catalogue, (2422, 33472), duplicate_ids={2422}, limit=4,
    )
    assert {c.course_id for c in frontier} == {33472, 31489, 33539}
    assert exclusions["goso_duplicate"] == 1
    assert max(c.lo_scores.get("ON1", 0) for c in frontier) == 0.568


def test_limited_frontier_does_not_include_orphaned_child():
    from app.planner.joint_contract import Candidate
    from app.planner.joint_frontier import admit_candidate_chains

    catalogue = {
        course_id: Candidate(
            course_id=course_id, item={"course_id": course_id, "credits": 5},
            allowed_semesters=(1, 2), prerequisites=parents,
            lo_scores={}, domain_shares=(1.0, 0.0), utility=1.0,
        )
        for course_id, parents in ((1, (2,)), (2, ()))
    }
    frontier, exclusions = admit_candidate_chains(
        catalogue, (1,), duplicate_ids=set(), limit=1,
    )
    assert frontier == ()
    assert exclusions["frontier_capacity"] == 1


def test_frontier_rejects_chain_that_cannot_fit_semester_windows():
    from app.planner.joint_contract import Candidate
    from app.planner.joint_frontier import admit_candidate_chains

    def candidate(course_id, parents, semesters):
        return Candidate(
            course_id=course_id, item={"course_id": course_id, "credits": 5},
            allowed_semesters=semesters, prerequisites=parents,
            lo_scores={}, domain_shares=(1.0, 0.0), utility=1.0,
        )

    catalogue = {1: candidate(1, (2,), (1, 2)), 2: candidate(2, (), (2, 3))}
    frontier, exclusions = admit_candidate_chains(
        catalogue, (1,), duplicate_ids=set(), limit=10,
    )
    assert frontier == ()
    assert exclusions["illegal_prerequisite_semester"] == 1
