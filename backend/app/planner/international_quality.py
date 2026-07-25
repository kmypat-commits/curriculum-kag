from __future__ import annotations

from typing import Dict, List
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.bridge_module import BridgeModule
from app.models.course import Course
from app.models.embedding import MatchFeedback, MatchScore
from app.models.epvo import EpvoDisciplineNormalized
from app.models.project import ProjectVersion


def _is_kz_regulatory_course(course: Course) -> bool:
    """ГОСО РК units are mandatory scaffolding, not profile mismatches."""
    code = str(course.course_id or "").upper()
    ctype = str(course.cycle_component or "").lower()
    title = str(course.title or "").lower()
    markers = (
        "goso", "practice", "final", "attestation", "research",
        "практика", "итоговая", "аттестация", "диплом", "диссертац",
        "нирм", "нирд", "эирм", "эирд",
    )
    return code.startswith("GOSO-KZ-") or any(marker in ctype or marker in title for marker in markers)


def _score_item(passed: bool, name: str, evidence: str, recommendation: str) -> Dict:
    return {
        "name": name,
        "passed": passed,
        "score": 1 if passed else 0,
        "evidence": evidence,
        "recommendation": recommendation,
    }


def project_course_relevance(project_version: ProjectVersion, courses: List[Course], db: Session) -> Dict:
    """Explain relevance using EPVO scope and LO evidence, not fragile domain strings."""
    course_ids = {int(course.id) for course in courses}
    constraints = project_version.project.constraints_json or {}
    selected_groups = {
        str(constraints.get(key) or "").strip()
        for key in ("group_code", "secondary_group_code")
        if str(constraints.get(key) or "").strip()
    }
    selected_directions = {
        str(constraints.get(key) or "").strip()
        for key in ("direction_code", "secondary_direction_code")
        if str(constraints.get(key) or "").strip()
    }
    scope_ids = set()
    normalized_rows = db.query(EpvoDisciplineNormalized).filter(
        EpvoDisciplineNormalized.approved_course_id.in_(course_ids or {-1})
    ).all()
    for row in normalized_rows:
        if selected_groups.intersection(set(row.group_codes or [])) or selected_directions.intersection(set(row.direction_codes or [])):
            scope_ids.add(int(row.approved_course_id))

    latest_feedback = {}
    feedback_rows = db.query(MatchFeedback).filter(
        MatchFeedback.project_version_id == project_version.id,
        MatchFeedback.course_id.in_(course_ids or {-1}),
    ).order_by(MatchFeedback.created_at.asc(), MatchFeedback.id.asc()).all()
    for row in feedback_rows:
        latest_feedback[(row.course_id, row.lo_id)] = row

    lo_ids = {lo.id for lo in project_version.learning_outcomes}
    lo_ids_by_course = set()
    if lo_ids and course_ids:
        for row in db.query(MatchScore).filter(
            MatchScore.project_version_id == project_version.id,
            MatchScore.course_id.in_(course_ids),
            MatchScore.lo_id.in_(lo_ids),
        ).all():
            feedback = latest_feedback.get((row.course_id, row.lo_id))
            if feedback and feedback.verdict == "incorrect":
                continue
            expert = float((row.evidence_json or {}).get("epvo_expert_score") or 0)
            corrected = float(feedback.corrected_score or 0) if feedback and feedback.verdict == "corrected" else 0
            if float(row.score or 0) >= 0.4 or expert >= 0.5 or corrected >= 0.4 or (feedback and feedback.verdict == "confirmed"):
                lo_ids_by_course.add(int(row.course_id))

    domains = {
        (project_version.project.domain1 or "").casefold().strip(),
        (project_version.project.domain2 or "").casefold().strip(),
    }
    domain_ids = {
        int(course.id) for course in courses
        if any(value and (value in (course.domain or "").casefold() or (course.domain or "").casefold() in value) for value in domains)
    }
    goso_applies = str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() == "KZ"
    regulatory_ids = {
        int(course.id) for course in courses
        if goso_applies and _is_kz_regulatory_course(course)
    }
    relevant_ids = scope_ids | lo_ids_by_course | domain_ids | regulatory_ids
    unsupported_ids = course_ids - relevant_ids
    return {
        "relevant_ids": relevant_ids,
        "scope_ids": scope_ids,
        "lo_ids": lo_ids_by_course,
        "domain_ids": domain_ids,
        "regulatory_ids": regulatory_ids,
        "unsupported_ids": unsupported_ids,
        "replaceable_unsupported_ids": unsupported_ids - regulatory_ids,
    }


def evaluate_international_quality(
    schedule: Dict[int, List[Dict]],
    project_version: ProjectVersion,
    db: Session,
    verification: Dict,
) -> Dict:
    """International curriculum-quality checklist.

    The rubric operationalizes common international practice: outcome-based
    curriculum mapping, documented continuous improvement, integrated curriculum,
    assessment alignment, progression, and expert-in-the-loop learning.
    """

    course_ids = [
        item["course_id"]
        for items in schedule.values()
        for item in items
        if item.get("course_id") is not None
    ]
    bridge_ids = [
        item["bridge_module_id"]
        for items in schedule.values()
        for item in items
        if item.get("bridge_module_id") is not None
    ]
    courses = db.query(Course).filter(Course.id.in_(course_ids or [-1])).all()
    bridges = db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids or [-1])).all()

    relevance = project_course_relevance(project_version, courses, db)
    courses_by_id = {int(course.id): course for course in courses}
    relevance_details = {
        "relevant_courses": len(relevance["relevant_ids"]),
        "total_courses": len(courses),
        "epvo_scope_courses": len(relevance["scope_ids"]),
        "lo_supported_courses": len(relevance["lo_ids"]),
        "domain_supported_courses": len(relevance["domain_ids"]),
        "regulatory_protected_courses": len(relevance["regulatory_ids"]),
        "unsupported_courses": len(relevance["unsupported_ids"]),
        "replaceable_unsupported_courses": len(relevance["replaceable_unsupported_ids"]),
        "unsupported_examples": [
            {
                "id": course_id,
                "title": courses_by_id[course_id].title,
                "credits": courses_by_id[course_id].credits,
                "cycle_component": courses_by_id[course_id].cycle_component,
            }
            for course_id in sorted(relevance["replaceable_unsupported_ids"])
            if course_id in courses_by_id
        ][:8],
        "regulatory_examples": [
            {
                "id": course_id,
                "title": courses_by_id[course_id].title,
                "credits": courses_by_id[course_id].credits,
                "cycle_component": courses_by_id[course_id].cycle_component,
            }
            for course_id in sorted(relevance["regulatory_ids"])
            if course_id in courses_by_id
        ][:8],
    }
    interdisciplinary_count = len(bridges) + sum(
        1 for course in courses if "interdisciplinary" in (course.domain or "").lower()
    )
    assessment_ready = sum(
        1 for item in list(courses) + list(bridges)
        if getattr(item, "assessment_methods", None)
    )
    total_learning_units = max(len(courses) + len(bridges), 1)
    promoted_count = db.query(AuditEvent).filter(
        AuditEvent.action == "promote_bridge_to_course",
        AuditEvent.entity_id == project_version.id,
    ).count()
    feedback_count = db.query(MatchFeedback).filter(
        MatchFeedback.project_version_id == project_version.id
    ).count()
    constraints = project_version.project.constraints_json or {}
    interdisciplinary = (
        str(constraints.get("program_type") or "standard").lower() in {"interdisciplinary", "joint"}
        and bool((project_version.project.domain2 or "").strip())
    )
    domain_credits = verification.get("domain_credits") or {}
    domain1_credits = float(domain_credits.get("domain1") or 0.0)
    domain2_credits = float(domain_credits.get("domain2") or 0.0)
    target_credits = float(verification.get("target_credits") or constraints.get("total_credits") or 0.0)
    tolerance = float(verification.get("domain_quota_tolerance_credits") or 0.0)
    required_domain1 = max(
        0.0,
        target_credits * float(constraints.get("min_domain1_percent") or 0.0) / 100.0 - tolerance,
    )
    required_domain2 = max(
        0.0,
        target_credits * float(constraints.get("min_domain2_percent") or 0.0) / 100.0 - tolerance,
    )
    real_domain_integration = (
        domain1_credits > 0
        and domain2_credits > 0
        and domain1_credits >= required_domain1
        and domain2_credits >= required_domain2
    )

    expert_evidence_count = 0
    if course_ids:
        for row in db.query(MatchScore).filter(
            MatchScore.project_version_id == project_version.id,
            MatchScore.course_id.in_(course_ids),
        ).all():
            if float((row.evidence_json or {}).get("epvo_expert_score") or 0.0) > 0:
                expert_evidence_count += 1

    coverage_items = verification.get("coverage_by_lo", {})
    threshold = verification.get("coverage_threshold", 0.60)
    mapped_los = sum(1 for item in coverage_items.values() if item.get("coverage", 0) >= threshold)
    total_los = max(len(coverage_items), 1)

    relevant_ratio = len(relevance["relevant_ids"]) / max(len(courses), 1)
    domain_quota_violations = verification.get("domain_quota_violations") or []

    checks = [
        _score_item(
            mapped_los == total_los,
            "Outcome-based curriculum mapping",
            f"{mapped_los}/{total_los} learning outcomes meet the coverage threshold.",
            "Ensure every programme LO has explicit course or bridge-module evidence.",
        ),
        _score_item(
            verification.get("hard_violation_count", 0) == 0,
            "Structured progression and prerequisite integrity",
            f"Hard violations: {verification.get('hard_violation_count', 0)}.",
            "Fix prerequisite order, semester load, or total-credit violations.",
        ),
        _score_item(
            relevant_ratio >= 0.85 and not domain_quota_violations,
            "Domain relevance control",
            (
                f"{len(relevance['relevant_ids'])}/{len(courses)} courses have direct EPVO scope, programme-LO evidence, "
                f"domain evidence, or RK mandatory status; domain quota violations: {len(domain_quota_violations)}."
            ),
            "Review only the unsupported professional courses; RK mandatory components, practices, and final attestation are not removed in KZ mode.",
        ),
        _score_item(
            (not interdisciplinary) or interdisciplinary_count > 0 or real_domain_integration,
            "Integrated interdisciplinary curriculum",
            (
                f"Bridge units: {interdisciplinary_count}; real-course domain credits: "
                f"{domain1_credits:g}/{domain2_credits:g}."
                if interdisciplinary
                else "Not applicable: this is a standard single-direction programme."
            ),
            "Add an explicit bridge module or real courses from both selected domains.",
        ),
        _score_item(
            assessment_ready / total_learning_units >= 0.5,
            "Assessment alignment",
            f"{assessment_ready}/{total_learning_units} learning units include assessment methods.",
            "Add assessment methods for courses/modules to support outcome-attainment evidence.",
        ),
        _score_item(
            promoted_count > 0 or len(bridges) > 0 or feedback_count > 0 or expert_evidence_count > 0,
            "Continuous improvement and expert-in-the-loop learning",
            (
                f"Project feedback: {feedback_count}; EPVO expert-supported links: {expert_evidence_count}; "
                f"promoted bridge events: {promoted_count}; bridge modules in plan: {len(bridges)}."
            ),
            "Confirm or correct AI-proposed course–LO links to document the next improvement cycle.",
        ),
    ]

    score = round(sum(item["score"] for item in checks) / len(checks) * 100, 1)
    return {
        "score": score,
        "passed": score >= 80,
        "relevance": relevance_details,
        "frameworks": [
            "Outcome-Based Education",
            "ABET-style continuous improvement",
            "CDIO integrated curriculum",
            "Tuning competences",
        ],
        "checks": checks,
    }
