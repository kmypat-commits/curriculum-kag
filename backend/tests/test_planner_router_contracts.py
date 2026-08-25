"""Composition tests for the split planner API routers."""

from types import SimpleNamespace

from app.api import planner
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError


def _paths():
    return {route.path for route in planner.router.routes}


def test_planner_build_router_contract_is_registered():
    assert {"/{project_version_id}/build", "/{project_version_id}/build-status"} <= _paths()


def test_planner_coverage_router_contract_is_registered():
    assert {"/{project_version_id}/lo-coverage-sources", "/{project_version_id}/evaluation"} <= _paths()


def test_planner_graph_router_contract_is_registered():
    assert {"/version/{project_version_id}/graph", "/version/{project_version_id}/semester-insight"} <= _paths()


def test_planner_replacement_router_contract_is_registered():
    assert {"/{project_version_id}/bridge-replacement-preview", "/{project_version_id}/bridge-ai-candidates"} <= _paths()


def test_course_replacement_router_contract_is_registered():
    assert {
        "/{project_version_id}/course-replacement-preview",
        "/{project_version_id}/course-replacement-apply",
    } <= _paths()


def test_planner_syllabus_router_contract_is_registered():
    assert {"/syllabus/{kind}/{entity_id}", "/syllabus/export-docx"} <= _paths()


def test_course_selection_facade_exposes_split_pipeline():
    from app.planner.course_selection import ensure_credit_bridge_modules, select_courses_for_variant

    assert callable(select_courses_for_variant)
    assert callable(ensure_credit_bridge_modules)


def test_variant_strategy_imports_its_bridge_dependencies():
    from app.planner.variant_strategy import select_courses_for_variant

    assert callable(select_courses_for_variant)


def test_variant_admission_predicate_is_extracted_from_orchestrator():
    from app.planner.variant_admission import is_project_domain_course

    assert callable(is_project_domain_course)


def test_semester_repair_facade_keeps_admission_repair_isolated():
    from app.planner.semester_repair import _repair_final_admission_misplacements

    assert callable(_repair_final_admission_misplacements)
    assert _repair_final_admission_misplacements.__module__.endswith(
        "semester_admission_repair"
    )


def test_variant_ranking_keeps_best_unique_titles():
    from app.planner.variant_ranking import ranked_unique_candidate_ids

    rows = {1: "math", 2: "math", 3: "security"}
    result = ranked_unique_candidate_ids(
        rows,
        rank=lambda course_id: {1: (2,), 2: (1,), 3: (3,)}[course_id],
        title_for=rows.get,
        limit=10,
    )
    assert result == [3, 1]


def test_variant_ranking_stage_preserves_variant_specific_ordering():
    from app.planner.variant_ranking import rank_variant_candidates

    courses = {
        1: SimpleNamespace(id=1, credits=5, recommended_semester=1, domain="IT", title="A"),
        2: SimpleNamespace(id=2, credits=5, recommended_semester=3, domain="IT", title="B"),
    }
    result = rank_variant_candidates(
        [1, 2],
        aggregates={
            1: {"max": 0.80, "sum": 0.80, "los": {"LO1"}},
            2: {"max": 0.80, "sum": 0.80, "los": {"LO1"}},
        },
        courses=courses,
        prerequisite_ids_by_course={1: [], 2: []},
        course_depth=lambda course_id: 0,
        role_rank=lambda _course: 1,
        scope_rank=lambda _course: 1,
        priority_rank=lambda _course: 1,
        semester_stability_rank=lambda _course: 1,
        variant_type="A",
        project_domains=("IT", ""),
        title_for=lambda course_id: courses[course_id].title,
    )
    assert result == [1, 2]


def test_variant_ranking_retrieves_only_admissible_depth_frontier():
    from app.planner.variant_ranking import rank_admissible_frontier

    courses = {
        1: SimpleNamespace(id=1, credits=5, recommended_semester=1, domain="IT", title="A"),
        2: SimpleNamespace(id=2, credits=5, recommended_semester=1, domain="IT", title="B"),
        3: SimpleNamespace(id=3, credits=5, recommended_semester=1, domain="IT", title="C"),
    }
    result = rank_admissible_frontier(
        [1, 2, 3],
        is_admissible=lambda course_id: course_id != 2,
        course_depth=lambda course_id: course_id,
        max_depth=3,
        aggregates={course_id: {"max": 0.8, "sum": 0.8, "los": {"LO1"}} for course_id in courses},
        courses=courses,
        prerequisite_ids_by_course={1: [], 2: [], 3: []},
        role_rank=lambda _course: 1,
        scope_rank=lambda _course: 1,
        priority_rank=lambda _course: 1,
        semester_stability_rank=lambda _course: 1,
        variant_type="A",
        title_for=lambda course_id: courses[course_id].title,
    )
    assert result == [1]


def test_variant_assembly_adds_bundle_atomically():
    from app.planner.variant_assembly import add_bundle_if_fits

    selected = {1: {"course_id": 1, "credits": 5}}
    total, added = add_bundle_if_fits(
        selected,
        [{"course_id": 2, "credits": 5}, {"course_id": 3, "credits": 3}],
        maximum_credits=12,
    )
    assert added is False
    assert total == 5
    assert set(selected) == {1}


def test_variant_assembly_foundation_frontier_commits_ranked_roots():
    from app.planner.variant_assembly import assemble_foundation_frontier

    selected = {}
    bundles = {1: [{"course_id": 1, "credits": 5}], 2: [{"course_id": 2, "credits": 3}]}
    total = assemble_foundation_frontier(
        [1, 2],
        selected=selected,
        bundle_for_course=bundles.get,
        rank_key=lambda course_id: (course_id,),
        foundation_target=5,
        maximum_credits=30,
    )
    assert total == 8
    assert set(selected) == {2, 1}


def test_variant_assembly_domain_credit_total_uses_shared_domain_share():
    from app.planner.variant_assembly import selected_domain_credits

    selected = {
        1: {"course_id": 10, "credits": 5},
        2: {"course_id": 11, "credits": 3},
    }
    courses = {10: SimpleNamespace(id=10), 11: SimpleNamespace(id=11)}
    assert selected_domain_credits(
        selected,
        courses=courses,
        domain_index=0,
        domain_share=lambda course, _index: 0.5 if course.id == 10 else 1.0,
    ) == 6


def test_variant_assembly_top_up_prefers_real_scoped_epvo_course():
    from app.planner.variant_assembly import top_up_with_real_epvo_courses

    course = SimpleNamespace(
        id=2,
        course_id="EPVO-2",
        title="Scoped course",
        domain="D",
        credits=5,
        recommended_semester=2,
        cycle_component="elective",
    )
    result = top_up_with_real_epvo_courses(
        [{"course_id": 1, "title": "Existing", "credits": 5}],
        target_credits=10,
        maximum_credits=15,
        courses={2: course},
        prerequisite_ids_by_course={2: []},
        aggregates={2: {"professional_lo_codes": {"LO1"}, "max": 0.8}},
        num_semesters=4,
        title_key=lambda value: str(value).casefold(),
        is_project_domain=lambda _course: True,
        scope_rank=lambda _course: 3,
        priority_rank=lambda _course: 10,
        course_depth=lambda _course_id: 1,
        course_matches_scope_theme=lambda _course: True,
        has_strong_exact_scope_evidence=lambda _course: True,
        unique_items_by_title=lambda items: items,
        admit_real_courses=lambda items: items,
    )
    assert [item["course_id"] for item in result] == [1, 2]
    assert result[-1]["selection_method"] == "real_epvo_credit_top_up"


def test_variant_quota_helpers_preserve_domain_credits_and_unique_lo_sources():
    from app.planner.variant_quota import (
        credits_by_domain,
        protected_quota_course_ids,
        quality_preserved_after_swap,
    )

    courses = {
        1: SimpleNamespace(id=1),
        2: SimpleNamespace(id=2),
    }
    items = [
        {"course_id": 1, "credits": 5, "prerequisites": [], "domain_quota_reserve": True},
        {"course_id": 2, "credits": 3, "prerequisites": [1]},
        {"bridge_module_id": 7, "credits": 4},
    ]
    assert credits_by_domain(
        items,
        courses=courses,
        project_domain_share=lambda _course, index: 1.0 if index == 0 else 0.0,
        project_domain_index=lambda _course: 0,
        secondary_bridge_ids={7},
        core_bridge_id=None,
        domain_bridge_codes={},
    ) == [8.0, 4.0]
    aggregates = {
        1: {"professional_lo_codes": {"LO1"}, "lo_scores": {"LO1": 0.8}},
        2: {"professional_lo_codes": {"LO2"}, "lo_scores": {"LO2": 0.7}},
    }
    protected = protected_quota_course_ids(
        items[:2],
        courses=courses,
        aggregates=aggregates,
        constraints={},
        project_domains=["A"],
        curriculum_role=lambda _course, _domains: "core" if _course.id == 1 else "elective",
    )
    assert protected == {1, 2}
    assert quality_preserved_after_swap(
        items[:2],
        baseline_core_ids={1},
        baseline_professional_codes={"LO1"},
        baseline_lo_scores={"LO1": 0.8},
        aggregates=aggregates,
    )


def test_variant_ranking_domain_frontier_applies_admission_and_depth():
    from app.planner.variant_ranking import rank_domain_quota_candidates

    courses = [SimpleNamespace(id=1), SimpleNamespace(id=2), SimpleNamespace(id=3)]
    result = rank_domain_quota_candidates(
        courses,
        domain_index=0,
        is_admissible=lambda course: course.id != 2,
        domain_share=lambda _course, _index: 1.0,
        course_depth=lambda course_id: course_id,
        max_depth=3,
        rank_key=lambda course: (-course.id,),
    )
    assert [course.id for course in result] == [1]


def test_streaming_benchmark_selected_offsets_are_deterministic():
    import json
    import sys
    import tempfile
    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        from benchmark_epvo_streaming import selected_offsets
    finally:
        sys.path.remove(str(scripts_dir))

    rows = [
        {"program_id": "p1", "split": "test"},
        {"program_id": "p2", "split": "validation"},
        {"program_id": "p3", "split": "test"},
    ]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "programs.jsonl"
        path.write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n",
            encoding="utf-8",
        )
        first = selected_offsets(path, "test", 2)
        second = selected_offsets(path, "test", 2)
    assert first == second
    assert set(first) == {"p1", "p3"}


def test_variant_scope_retrieval_keeps_group_and_domain_evidence_separate():
    from types import SimpleNamespace

    import app.planner.variant_scope as scope_module
    from app.planner.variant_scope import build_epvo_scope_index

    row = SimpleNamespace(
        approved_course_id=10,
        group_codes=["G1"],
        direction_codes=["D1"],
        source_programs=["p1", "p2"],
        typical_semester=2,
        title_ru="Анализ данных",
        title_kk="Деректерді талдау",
        title_en="Data analysis",
    )

    class Query:
        def filter(self, *_args):
            return self

        def all(self):
            return [row]

    class Database:
        def query(self, _model):
            return Query()

    previous = scope_module.epvo_row_relevance_score
    scope_module.epvo_row_relevance_score = lambda _row, _version: 0.8
    try:
        result = build_epvo_scope_index(
            Database(),
            version=SimpleNamespace(),
            constraints={
                "group_code": "G1",
                "direction_code": "D1",
                "total_semesters": 4,
            },
            aggregates={10: {"max": 0.8, "expert": 1.0}},
            courses={10: SimpleNamespace(id=10)},
            title_key=lambda value: str(value).casefold(),
        )
    finally:
        scope_module.epvo_row_relevance_score = previous

    assert result.level_scope_allowed_ids == {10}
    assert result.scope_by_course[10] == 3
    assert result.priority_by_course[10] > 0
    assert result.semester_values_by_course[10] == [2]
    assert result.domain_index_by_course[10] == 0


def test_variant_prerequisites_filter_keeps_supported_earlier_edges_only():
    from app.planner.variant_prerequisites import filter_supported_prerequisites

    courses = {
        1: SimpleNamespace(title="Python programming", recommended_semester=1),
        2: SimpleNamespace(title="Advanced Python programming", recommended_semester=2),
        3: SimpleNamespace(title="Unrelated late course", recommended_semester=3),
    }
    result = filter_supported_prerequisites(
        {2: [1], 3: [2]},
        courses=courses,
        aggregates={1: {"max": 0.0}, 2: {"max": 0.0}},
        num_semesters=4,
        normalize_title=lambda value: str(value or "").casefold(),
        excluded_prefixes=("advanced",),
    )
    assert result == {2: [1]}


def test_variant_prerequisite_depth_is_cycle_safe_and_memoized():
    from app.planner.variant_prerequisites import make_course_depth

    courses = {1: object(), 2: object(), 3: object()}
    depth = make_course_depth({1: [2], 2: [3], 3: [1]}, courses=courses, num_semesters=4)
    assert depth(1) == 8
    assert depth(99) == 5


def test_build_claim_blocks_a_duplicate_even_when_status_storage_is_unavailable():
    from app.api import planner_state

    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def query(self, *_args):
            raise SQLAlchemyError("status store unavailable")

    class BrokenSessionFactory:
        def __call__(self):
            return BrokenSession()

        def begin(self):
            raise SQLAlchemyError("status store unavailable")

    version_id = 987654321
    original = planner_state.SessionLocal
    planner_state.SessionLocal = BrokenSessionFactory()
    planner_state.plan_build_status.pop(version_id, None)
    try:
        first = planner_state.claim_build_status(version_id, state="running", stage="matching", progress=5)
        second = planner_state.claim_build_status(version_id, state="running", stage="matching", progress=5)
        assert first is not None
        assert second is None
    finally:
        planner_state.plan_build_status.pop(version_id, None)
        planner_state.SessionLocal = original


def test_hard_variant_failure_is_rejected_for_every_jurisdiction():
    from app.api.planner_build import must_reject_variant

    assert must_reject_variant({"feasible": False, "hard_violation_count": 0})
    assert must_reject_variant({"feasible": True, "hard_violation_count": 1})
    assert must_reject_variant({
        "feasible": True,
        "hard_violation_count": 0,
        "quality_violations": [{"reason": "lo_without_real_course"}],
    })
    assert must_reject_variant({
        "feasible": True,
        "hard_violation_count": 0,
        "quality_violations": [{"reason": "semester_appropriateness"}],
    })
    assert must_reject_variant({
        "feasible": True,
        "hard_violation_count": 0,
        "quality_violations": [{"reason": "missing_core_competency_blocks"}],
    })
    assert not must_reject_variant({
        "feasible": True,
        "hard_violation_count": 0,
        "quality_violations": [{"reason": "advisory_domain_review"}],
    })


def test_partial_rebuild_keeps_one_and_only_one_active_variant():
    from app.api.planner_build import activate_only_plan

    class PlanRow:
        def __init__(self, plan_id, active):
            self.id = plan_id
            self.is_active = active

    plans = [PlanRow(1, 0), PlanRow(2, 1), PlanRow(3, 0)]
    active = activate_only_plan(plans, active_plan_id=1)

    assert active is plans[0]
    assert [plan.id for plan in plans if plan.is_active] == [1]


def _programme_payload(program_type="standard"):
    constraints = {
        "education_level": "bachelor",
        "education_area": "6B06",
        "direction_code": "6B061",
        "group_code": "B057",
        "program_type": program_type,
        "instruction_language": "ru",
        "duration_years": 4,
        "total_semesters": 8,
        "total_credits": 240,
        "max_credits_per_semester": 30,
        "min_domain2_percent": 40,
    }
    if program_type == "interdisciplinary":
        constraints.update({
            "secondary_education_area": "6B07",
            "secondary_direction_code": "6B071",
            "secondary_group_code": "B063",
        })
    return {
        "title": "Contract programme",
        "goal": "Train specialists for the selected direction.",
        "domain1": "Information and communication technologies",
        "domain2": "Engineering" if program_type == "interdisciplinary" else "ignored",
        "learning_outcomes": [{"lo_code": "LO1", "lo_text": "Apply professional methods."}],
        "constraints": constraints,
    }


def test_standard_program_requires_primary_epvo_scope_and_clears_secondary_scope():
    from app.api.projects import ProjectCreate

    model = ProjectCreate(**_programme_payload())
    assert model.domain2 == ""
    assert model.constraints["min_domain2_percent"] == 0


def test_interdisciplinary_program_rejects_duplicate_epvo_scope():
    from app.api.projects import ProjectCreate

    payload = _programme_payload("interdisciplinary")
    payload["constraints"]["secondary_direction_code"] = "6B061"
    try:
        ProjectCreate(**payload)
    except ValidationError:
        return
    raise AssertionError("A duplicate interdisciplinary direction must be rejected")


def test_program_rejects_credit_volume_that_cannot_fit_the_duration():
    from app.api.projects import ProjectCreate

    payload = _programme_payload()
    payload["constraints"].update({"total_credits": 300, "credit_tolerance": 3})
    try:
        ProjectCreate(**payload)
    except ValidationError:
        return
    raise AssertionError("A programme volume outside the duration tolerance must be rejected")


def test_legacy_metrics_without_admission_evidence_are_not_current():
    from app.planner.plan_metrics import PLAN_METRICS_SCHEMA_VERSION, persisted_metrics_current

    assert not persisted_metrics_current({"metrics_schema_version": PLAN_METRICS_SCHEMA_VERSION})
    assert persisted_metrics_current({
        "metrics_schema_version": PLAN_METRICS_SCHEMA_VERSION,
        "course_admission": {"passed": True},
    })
