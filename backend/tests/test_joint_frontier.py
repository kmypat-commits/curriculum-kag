from app.planner import domain_evidence, goso


def test_lo_pipeline_counts_distinguish_scoring_scope_and_chain_loss():
    from types import SimpleNamespace
    from app.planner.joint_frontier import lo_pipeline_counts

    evidence = {
        1: {"ON1": 0.61}, 2: {"ON1": 0.72},
        3: {"ON2": 0.58},
    }
    catalogue = {
        1: SimpleNamespace(lo_scores=evidence[1]),
        3: SimpleNamespace(lo_scores=evidence[3]),
    }
    admitted = (catalogue[3],)
    assert lo_pipeline_counts(evidence, catalogue, admitted, ("ON1", "ON2", "ON3")) == {
        "ON1": {"scored": 2, "scoped": 1, "admitted": 0, "max_scored": 0.72},
        "ON2": {"scored": 1, "scoped": 1, "admitted": 1, "max_scored": 0.58},
        "ON3": {"scored": 0, "scoped": 0, "admitted": 0, "max_scored": 0.0},
    }


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
        31489: candidate(31489, 0.4),
        33539: candidate(33539, 0.4),
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
            lo_scores={"ON1": 0.4}, domain_shares=(1.0, 0.0), utility=1.0,
        )
        for course_id, parents in ((1, (2,)), (2, ()))
    }
    frontier, exclusions = admit_candidate_chains(
        catalogue, (1,), duplicate_ids=set(), limit=1,
    )
    assert frontier == ()
    assert exclusions["frontier_capacity"] == 1


def test_frontier_rejects_chain_with_parent_below_current_verifier_gate():
    from app.planner.joint_contract import Candidate
    from app.planner.joint_frontier import admit_candidate_chains

    def candidate(course_id, parent_ids, score):
        return Candidate(
            course_id=course_id, item={"course_id": course_id, "credits": 5},
            allowed_semesters=(1, 2), prerequisites=parent_ids,
            lo_scores={"ON1": score}, domain_shares=(1.0, 0.0), utility=score,
        )

    catalogue = {1: candidate(1, (2,), 0.6), 2: candidate(2, (), 0.0)}
    frontier, exclusions = admit_candidate_chains(
        catalogue, (1,), duplicate_ids=set(), limit=10,
    )
    assert frontier == ()
    assert exclusions["unverified_course_evidence"] == 1


def test_frontier_rejects_chain_that_cannot_fit_semester_windows():
    from app.planner.joint_contract import Candidate
    from app.planner.joint_frontier import admit_candidate_chains

    def candidate(course_id, parents, semesters):
        return Candidate(
            course_id=course_id, item={"course_id": course_id, "credits": 5},
            allowed_semesters=semesters, prerequisites=parents,
            lo_scores={"ON1": 0.4}, domain_shares=(1.0, 0.0), utility=1.0,
        )

    catalogue = {1: candidate(1, (2,), (1, 2)), 2: candidate(2, (), (2, 3))}
    frontier, exclusions = admit_candidate_chains(
        catalogue, (1,), duplicate_ids=set(), limit=10,
    )
    assert frontier == ()
    assert exclusions["illegal_prerequisite_semester"] == 1


def test_frontier_accepts_already_fixed_regulatory_parent_only_if_earlier():
    from app.planner.joint_contract import Candidate
    from app.planner.joint_frontier import admit_candidate_chains

    candidate = Candidate(
        course_id=10, item={"course_id": 10, "credits": 5},
        allowed_semesters=(2, 3), prerequisites=(99,),
        lo_scores={"ON1": 0.6}, domain_shares=(1.0, 0.0), utility=0.6,
    )
    valid, _ = admit_candidate_chains(
        {10: candidate}, (10,), duplicate_ids={99}, limit=10,
        fixed_semesters={99: 1},
    )
    invalid, exclusions = admit_candidate_chains(
        {10: candidate}, (10,), duplicate_ids={99}, limit=10,
        fixed_semesters={99: 3},
    )
    assert {c.course_id for c in valid} == {10}
    assert invalid == ()
    assert exclusions["illegal_prerequisite_semester"] == 1


def test_database_frontier_uses_raw_evidence_and_closes_parents():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.database import Base
    from app.models.course import Course
    from app.models.embedding import MatchScore
    from app.models.epvo import EpvoDisciplineNormalized
    from app.models.project import LearningOutcome, Project, ProjectVersion
    from app.planner.joint_frontier import build_joint_frontier

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            project = Project(
                title="Test", domain1="Информационные технологии", domain2="",
                constraints_json={"total_semesters": 4, "total_credits": 120,
                                  "max_credits_per_semester": 30,
                                  "jurisdiction": "KZ", "education_level": "bachelor",
                                  "group_code": "B074"},
            )
            version = ProjectVersion(version_number=1, project=project)
            lo = LearningOutcome(lo_code="ON1", lo_text="Разрабатывать информационные системы")
            version.learning_outcomes.append(lo)
            parent = Course(course_id="EPVO-100", title="Основы программирования",
                            domain="Информационные технологии", credits=5,
                            recommended_semester=1)
            strong = Course(course_id="EPVO-101", title="Разработка информационных систем",
                            domain="Информационные технологии", credits=5,
                            recommended_semester=3, prerequisites=[parent])
            boosted = Course(course_id="EPVO-102", title="Общие вопросы технологий",
                             domain="Информационные технологии", credits=5,
                             recommended_semester=3)
            duplicate = Course(course_id="EPVO-103", title="Основы антикоррупционной культуры",
                               domain="Информационные технологии", credits=5,
                               recommended_semester=1)
            wrong_level = Course(course_id="EPVO-900", title="Магистерский курс информатики",
                                 domain="Информационные технологии", credits=5,
                                 recommended_semester=3)
            foreign = Course(course_id="EPVO-104", title="Финансовая грамотность и навыки предпринимательства",
                             domain="Информационные технологии", credits=5,
                             recommended_semester=3)
            wrong_level_source = EpvoDisciplineNormalized(
                id=900, canonical_title=wrong_level.title,
                dedup_fingerprint="wrong-level-900", group_codes=["M100"],
                direction_codes=["7M061"],
            )
            valid_sources = [
                EpvoDisciplineNormalized(
                    id=epvo_id, canonical_title=title,
                    dedup_fingerprint=f"valid-level-{epvo_id}",
                    group_codes=["B074"], direction_codes=["6B073"],
                    typical_semester={100: 1, 101: 2, 102: 3, 104: 3}[epvo_id],
                )
                for epvo_id, title in ((100, parent.title), (101, strong.title),
                                       (102, boosted.title), (104, foreign.title))
            ]
            db.add_all([version, parent, strong, boosted, duplicate,
                        wrong_level, foreign, wrong_level_source, *valid_sources])
            db.flush()
            db.add_all([
                MatchScore(project_version_id=version.id, course_id=parent.id,
                           lo_id=lo.id, score=0.4,
                           evidence_json={"semantic_score": 0.4}),
                MatchScore(project_version_id=version.id, course_id=strong.id,
                           lo_id=lo.id, score=0.9,
                           evidence_json={"semantic_score": 0.568}),
                MatchScore(project_version_id=version.id, course_id=boosted.id,
                           lo_id=lo.id, score=1.0,
                           evidence_json={"semantic_score": 0.453}),
                MatchScore(project_version_id=version.id, course_id=duplicate.id,
                           lo_id=lo.id, score=0.95,
                           evidence_json={"semantic_score": 0.78}),
                MatchScore(project_version_id=version.id, course_id=wrong_level.id,
                           lo_id=lo.id, score=0.95,
                           evidence_json={"semantic_score": 0.78}),
                MatchScore(project_version_id=version.id, course_id=foreign.id,
                           lo_id=lo.id, score=0.95,
                           evidence_json={"semantic_score": 0.78}),
            ])
            db.flush()
            problem = build_joint_frontier(version, db, limit=10)
            assert {strong.id, parent.id}.issubset(problem.candidates_by_id)
            assert problem.candidates_by_id[strong.id].lo_scores["ON1"] == 0.568
            assert problem.candidates_by_id[strong.id].item["admission_score"] == 0.568
            assert problem.candidates_by_id[strong.id].item["recommended_semester"] == 2
            assert problem.candidates_by_id[parent.id].item["source_semester_required"] is True
            assert problem.candidates_by_id[boosted.id].lo_scores["ON1"] == 0.453
            assert problem.candidates_by_id[strong.id].prerequisites == (parent.id,)
            assert duplicate.id not in problem.candidates_by_id
            assert wrong_level.id not in problem.candidates_by_id
            assert foreign.id not in problem.candidates_by_id
            assert problem.exclusions["goso_duplicate"] == 1
    finally:
        engine.dispose()


def test_final_admission_rejects_structural_parent_without_direct_lo():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.database import Base
    from app.models.course import Course
    from app.models.embedding import MatchScore
    from app.models.project import LearningOutcome, Project, ProjectVersion
    from app.planner.admission import audit_final_course_admission

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            project = Project(title="Test", domain1="Информационные технологии",
                              domain2="", constraints_json={"total_semesters": 2})
            version = ProjectVersion(version_number=1, project=project)
            lo = LearningOutcome(lo_code="ON1", lo_text="Разрабатывать системы")
            version.learning_outcomes.append(lo)
            db.add(version)
            db.flush()
            parent = Course(course_id=f"AI-CONFIRMED-{version.id}-1",
                            title="Основы программирования",
                            domain="Информационные технологии", credits=5)
            child = Course(course_id=f"AI-CONFIRMED-{version.id}-2",
                           title="Разработка информационных систем",
                           domain="Информационные технологии", credits=5)
            unrelated = Course(course_id=f"AI-CONFIRMED-{version.id}-3",
                               title="Общие технологии",
                               domain="Информационные технологии", credits=5)
            db.add_all([parent, child, unrelated])
            db.flush()
            db.add(MatchScore(project_version_id=version.id, course_id=child.id,
                              lo_id=lo.id, score=0.6,
                              evidence_json={"semantic_score": 0.6}))
            db.flush()
            schedule = {
                1: [{"course_id": parent.id, "title": parent.title,
                     "credits": 5, "prerequisites": [], "domain": parent.domain}],
                2: [{"course_id": child.id, "title": child.title,
                     "credits": 5, "prerequisites": [parent.id], "domain": child.domain,
                     "admission_score": 0.6}],
            }
            check = audit_final_course_admission(schedule, version, db)
            assert not check["passed"]
            assert any(v["course_id"] == parent.id and
                       v["reason"] == "no_credible_professional_lo"
                       for v in check["violations"])
            schedule[2].append({"course_id": unrelated.id, "title": unrelated.title,
                                "credits": 5, "prerequisites": [],
                                "domain": unrelated.domain})
            check = audit_final_course_admission(schedule, version, db)
            assert not check["passed"]
            assert any(v["course_id"] == unrelated.id and
                       v["reason"] == "no_credible_professional_lo"
                       for v in check["violations"])
    finally:
        engine.dispose()
