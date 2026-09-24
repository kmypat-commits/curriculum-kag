"""Retrieval confidence must not hide an uncovered learning outcome."""
from types import SimpleNamespace as NS

from app.planner.variant_lo_repair import close_professional_lo_gaps


class Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args):
        return self

    def all(self):
        return self.rows


def repair(weak, strong, *, expert=0.0):
    courses = {i: NS(id=i, course_id=f"EPVO-{i}", title=f"Course {i}",
                     credits=5, domain="Culture", recommended_semester=2,
                     cycle_component="elective") for i in (1, 2)}
    rows = [NS(course_id=i, lo_id=1, score=1.0,
               evidence_json={"semantic_score": score,
                              "epvo_expert_score": expert if i == 2 else 0.0})
            for i, score in ((1, weak), (2, strong))]
    return close_professional_lo_gaps(
        [{"course_id": 1, "credits": 5, "title": "Course 1"}],
        professional_scope=True,
        version=NS(learning_outcomes=[NS(id=1, lo_code="ON11")]),
        db=NS(query=lambda model: Query(rows)), project_version_id=1,
        courses=courses, constraints={"total_credits": 5, "allow_new_courses": False},
        project_domains=["Culture"], aggregates={}, prereq_ids_by_course={},
        scope_rank=lambda course: 3, priority_rank=lambda course: 0,
        is_project_domain=lambda course: True, variant_type="A", coverage_threshold=0.8,
        unique_items_by_title=lambda items: items, bridge_item=lambda bridge: {},
    )


def test_saturated_ranking_does_not_hide_real_lo_gap():
    result = repair(0.30, 0.90)
    assert result[0]["course_id"] == 2
    assert result[0]["selection_evidence"]["model_score"] == 0.90


def test_weak_candidate_cannot_gain_evidence_from_ranking():
    assert repair(0.30, 0.20)[0]["course_id"] == 1


def test_expert_evidence_remains_valid():
    assert repair(0.30, 0.20, expert=0.9)[0]["course_id"] == 2


def test_already_covered_outcome_is_unchanged():
    assert repair(0.85, 0.90)[0]["course_id"] == 1
