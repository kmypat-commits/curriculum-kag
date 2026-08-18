"""Composition tests for the split planner API routers."""

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
