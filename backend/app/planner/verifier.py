from __future__ import annotations
from typing import Dict, List
from sqlalchemy.orm import Session
from app.config import settings
from app.models.bridge_module import BridgeModule
from app.models.embedding import MatchScore
from app.models.course import Course
from app.models.project import ProjectVersion
from app.models.epvo import EpvoDisciplineNormalized
from app.kag.embedding_service import embedding_service
from app.planner.goso import GOSO_COURSE_LO_CODES, evaluate_goso_compliance
from app.planner.bridge_policy import bridge_module_limit
from app.planner.domain_evidence import domain_credit_shares, domain_label_matches
LOAD_TOLERANCE = 3
TOTAL_CREDIT_TOLERANCE = 5
MATCH_THRESHOLD = 0.4
REDUNDANCY_THRESHOLD = 0.45
FALLBACK_REDUNDANCY_THRESHOLD = 0.65


def _semantic_min_semester(title: str | None, num_semesters: int) -> int:
    text = str(title or "")
    suspicious = "Ð" in text or "Ñ" in text or (
        len(text) > 6 and (text.count("Р") + text.count("С")) > len(text) / 4
    )
    if suspicious:
        for source_encoding in ("latin1", "cp1251"):
            try:
                repaired = text.encode(source_encoding).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            if repaired and repaired != text:
                text = repaired
                break
    text = text.casefold()
    clinical = (
        "хирург", "surgery", "кардио", "гастро", "онколог", "уролог",
        "невролог", "паразитолог", "психиатр", "офтальм", "реаним",
        "терапи", "педиатр", "акуш", "гинек", "дермат", "клиническ",
        "диагност", "врачебн",
    )
    research = (
        "методология науч", "scientific methodology", "доказательная медицина",
        "evidence based medicine", "научных исследований", "research methods",
    )
    if any(marker in text for marker in clinical):
        return max(2, min(num_semesters, -(-num_semesters * 55 // 100)))
    if any(marker in text for marker in research):
        if num_semesters <= 6:
            return 1
        return max(2, min(num_semesters, -(-num_semesters * 35 // 100)))
    if "первичной медицинской помощи" in text or "primary medical care" in text:
        return max(2, min(num_semesters, -(-num_semesters * 45 // 100)))
    return 1


def _semantic_max_semester(title: str | None, num_semesters: int) -> int:
    text = str(title or "")
    for source_encoding in ("latin1", "cp1251"):
        try:
            repaired = text.encode(source_encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if repaired != text:
            text = repaired
            break
    text = text.casefold().strip()
    if any(marker in text for marker in (
        "клиническ", "диагност", "врачебн", "хирург", "терапи",
        "педиатр", "акуш", "гинек", "онколог", "кардио",
        "clinical", "diagnostic", "surgery",
    )):
        return num_semesters
    if any(marker in text for marker in (
        "информационной безопасности", "кибербезопасности",
        "цифровой криминалистики", "digital forensics", "cybersecurity",
    )):
        return max(2, min(num_semesters, -(-num_semesters * 65 // 100)))
    if any(marker in text for marker in (
        "доказательной медицины", "evidence based medicine",
    )):
        return max(2, min(num_semesters, -(-num_semesters * 90 // 100)))
    if any(marker in text for marker in (
        "научных исследований", "research methods", "academic writing",
    )):
        return max(2, min(num_semesters, -(-num_semesters * 50 // 100)))
    if text.startswith(("основы ", "введение ")) or any(marker in text for marker in (
        "теоретические основы", "fundamentals", "introduction",
        "инструментарий технологии программирования",
    )):
        return max(1, min(num_semesters, -(-num_semesters * 35 // 100)))
    return num_semesters


def _ict_competency_requirements(constraints: Dict) -> Dict:
    """Return the explainable competency ontology for a known ICT scope."""
    scope = " ".join(str(constraints.get(key) or "").upper() for key in (
        "direction_code", "secondary_direction_code", "group_code", "secondary_group_code",
    ))
    if not any(code in scope for code in ("6B061", "7M061", "8D061", "B057", "M094", "D094")):
        return {}
    level = str(constraints.get("education_level") or "bachelor").lower()
    if level in {"doctorate", "doctoral", "phd"}:
        return {
            "research_methodology": (("исслед",), ("методолог",), ("research",)),
            "advanced_ai_and_data": (("искусствен", "интеллект"), ("больш", "данн"), ("data",)),
            "experimental_validation": (("эксперимент",), ("валидац",), ("validation",)),
            "systems_modelling": (("модел", "систем"), ("информацион", "ресурс")),
            "research_leadership": (("управлен", "проект"), ("project management",)),
        }
    elif level in {"master", "masters", "magistracy"}:
        return {
            "research_methodology": (("исслед",), ("методолог",), ("research",)),
            "ai_and_data": (("искусствен", "интеллект"), ("машин", "обуч"), ("анализ", "данн")),
            "systems_architecture": (("проектирован", "информацион", "систем"), ("архитектур",)),
            "information_security": (("безопас",), ("кибер",), ("security",)),
            "project_and_communication": (("управлен", "проект"), ("научн", "коммуникац"), ("project management",)),
        }
    else:
        return {
            "programming_and_algorithms": (("программир",), ("алгоритм",)),
            "data_and_databases": (("баз", "данн"), ("анализ", "данн"), ("database",)),
            "systems_and_networks": (
                ("операцион", "систем"),
                ("компьютер", "сет"),
                ("системн", "программ"),
                ("автоматизированн", "систем"),
                ("информационн", "систем"),
                ("систем", "управлен"),
                ("information", "system"),
                ("computer", "network"),
            ),
            "information_security": (("безопас",), ("кибер",), ("security",)),
            "ai_and_analytics": (("искусствен", "интеллект"), ("машин", "обуч"), ("аналитик",)),
            "project_and_research": (("проект",), ("научн", "исслед"), ("academic writing",)),
        }


def _ict_competency_audit(courses: List[Course], constraints: Dict) -> Dict:
    """Verify explainable core blocks for EPVO ICT programmes.

    LO coverage alone can be high while a conventional core block is absent.
    This audit is intentionally activated only for the known 6B061/7M061/8D061
    scope (and corresponding groups), so it does not impose ICT rules on other
    educational fields.
    """
    scope = " ".join(str(constraints.get(key) or "").upper() for key in (
        "direction_code", "secondary_direction_code", "group_code", "secondary_group_code",
    ))
    requirements = _ict_competency_requirements(constraints)
    if not requirements:
        return {"applicable": False, "passed": True, "covered": {}, "missing": []}
    level = str(constraints.get("education_level") or "bachelor").lower()
    titles = [str(course.title or "") for course in courses]
    normalized = [(title, title.casefold()) for title in titles]
    covered = {}
    for code, alternatives in requirements.items():
        evidence = [
            title
            for title, text in normalized
            if any(all(stem in text for stem in stems) for stems in alternatives)
        ]
        covered[code] = evidence[:5]
    missing = [code for code, evidence in covered.items() if not evidence]
    return {
        "applicable": True,
        "scope": scope.strip(),
        "level": level,
        "passed": not missing,
        "covered": covered,
        "missing": missing,
        "covered_count": len(covered) - len(missing),
        "required_count": len(covered),
    }


def verify_curriculum_plan(schedule: Dict[int, List[Dict]], project_version: ProjectVersion, db: Session) -> Dict:
    constraints = project_version.project.constraints_json or {}
    num_semesters = int(constraints.get("total_semesters", len(schedule) or 1))
    target_credits = int(constraints.get("total_credits", 240))
    nominal_load = float(constraints.get("max_credits_per_semester", target_credits / max(num_semesters, 1)))
    min_load, max_load = max(0.0, nominal_load - LOAD_TOLERANCE), nominal_load + LOAD_TOLERANCE
    semester_loads = {s: sum(int(i.get("credits") or 0) for i in items) for s, items in schedule.items()}
    total_credits = sum(semester_loads.values())
    course_semester = {i["course_id"]: s for s, items in schedule.items() for i in items if i.get("course_id") is not None}
    selected_bridge_ids = [
        i["bridge_module_id"]
        for items in schedule.values()
        for i in items
        if i.get("bridge_module_id") is not None
    ]
    bridge_modules = db.query(BridgeModule).filter(BridgeModule.id.in_(selected_bridge_ids or [-1])).all()
    prerequisite_violations = []
    for semester, items in schedule.items():
        for item in items:
            for prerequisite_id in item.get("prerequisites", []) or []:
                prerequisite_semester = course_semester.get(prerequisite_id)
                if prerequisite_semester is None:
                    prerequisite_violations.append({"course_id": item.get("course_id"), "prerequisite_id": prerequisite_id, "semester": semester, "reason": "missing_prerequisite"})
                elif prerequisite_semester >= semester:
                    prerequisite_violations.append({"course_id": item.get("course_id"), "prerequisite_id": prerequisite_id, "semester": semester, "prerequisite_semester": prerequisite_semester, "reason": "prerequisite_not_earlier"})
    education_level = str(constraints.get("education_level") or "").casefold()
    # Doctoral ГОСО allocates fixed research-work and practice blocks (often
    # 20 credits for research and 10 credits for a practice).  Those protected
    # blocks can produce an unavoidable 25/40 split even when the programme is
    # exactly 180 credits.  Do not call that a planning defect: exempt only a
    # semester carrying at least one full 20-credit protected research block;
    # ordinary doctoral electives remain subject to the 27--33 band.
    regulatory_credits_by_semester = {
        semester: sum(
            int(item.get("credits") or 0)
            for item in items
            if item.get("regulatory_required")
        )
        for semester, items in schedule.items()
    }
    goso_load_exemptions = {
        semester
        for semester, credits in regulatory_credits_by_semester.items()
        if education_level in {"doctorate", "doctoral", "phd"} and credits >= 20
    }
    load_violations = [
        {
            "semester": s,
            "credits": semester_loads.get(s, 0),
            "allowed_min": min_load,
            "allowed_max": max_load,
        }
        for s in range(1, num_semesters + 1)
        if (
            s not in goso_load_exemptions
            and (semester_loads.get(s, 0) < min_load or semester_loads.get(s, 0) > max_load)
        )
    ]
    credit_violations = []
    if total_credits < target_credits: credit_violations.append({"reason": "below_target", "actual": total_credits, "target": target_credits})
    credit_tolerance = max(0, int(constraints.get("credit_tolerance", TOTAL_CREDIT_TOLERANCE)))
    if total_credits > target_credits + credit_tolerance: credit_violations.append({"reason": "above_tolerance", "actual": total_credits, "maximum": target_credits + credit_tolerance})
    project_domains = [
        getattr(project_version.project, "domain1", "") or "",
        getattr(project_version.project, "domain2", "") or "",
    ]
    interdisciplinary = str(constraints.get("program_type") or "standard").lower() in {"interdisciplinary", "joint"}
    minimum_domain_percent = [
        float(constraints.get("min_domain1_percent") or 0),
        float(constraints.get("min_domain2_percent") or 0) if interdisciplinary else 0.0,
    ]
    domain_quota_tolerance = max(
        0.0, float(constraints.get("domain_quota_tolerance_credits", 3) or 0)
    )
    domain_credits = [0.0, 0.0]
    selected_course_ids = {
        int(item["course_id"])
        for items in schedule.values()
        for item in items
        if item.get("course_id") is not None
    }
    primary_group = str(constraints.get("group_code") or "").strip()
    secondary_group = str(constraints.get("secondary_group_code") or "").strip()
    primary_direction = str(constraints.get("direction_code") or "").strip()
    secondary_direction = str(constraints.get("secondary_direction_code") or "").strip()
    scoped_domain_by_course: Dict[int, tuple[float, float]] = {}
    if selected_course_ids and (primary_group or secondary_group or primary_direction or secondary_direction):
        normalized_rows = db.query(EpvoDisciplineNormalized).filter(
            EpvoDisciplineNormalized.approved_course_id.in_(selected_course_ids)
        ).all()
        scope_evidence: Dict[int, List[int]] = {}
        for row in normalized_rows:
            row_groups = set(row.group_codes or [])
            row_directions = set(row.direction_codes or [])
            primary_scope = 3 if primary_group and primary_group in row_groups else 2 if primary_direction and primary_direction in row_directions else 0
            secondary_scope = 3 if secondary_group and secondary_group in row_groups else 2 if secondary_direction and secondary_direction in row_directions else 0
            if row.approved_course_id and (primary_scope or secondary_scope):
                evidence = scope_evidence.setdefault(int(row.approved_course_id), [0, 0])
                evidence[0] = max(evidence[0], primary_scope)
                evidence[1] = max(evidence[1], secondary_scope)
        scoped_domain_by_course = {
            course_id: domain_credit_shares(primary_scope, secondary_scope)
            for course_id, (primary_scope, secondary_scope) in scope_evidence.items()
        }
    for items in schedule.values():
        for item in items:
            scoped_shares = scoped_domain_by_course.get(item.get("course_id"))
            if scoped_shares is not None:
                # A course may have a broad EPVO link to the primary scope while
                # its explicit catalogue domain is the secondary discipline.
                # Do not let that broad link erase auditable domain evidence.
                item_domain = str(item.get("domain") or "")
                explicit_matches = [
                    domain_label_matches(item_domain, [project_domains[index]])
                    for index in range(2)
                ]
                if explicit_matches[1] and not explicit_matches[0]:
                    scoped_shares = (0.0, 1.0)
                elif explicit_matches[0] and not explicit_matches[1]:
                    scoped_shares = (1.0, 0.0)
                credits = float(item.get("credits") or 0)
                domain_credits[0] += credits * scoped_shares[0]
                domain_credits[1] += credits * scoped_shares[1]
                continue
            item_domain = str(item.get("domain") or "").casefold().strip()
            for index, domain in enumerate(project_domains):
                if domain_label_matches(item_domain, [domain]):
                    domain_credits[index] += int(item.get("credits") or 0)
                    break
    # Explicit interdisciplinary modules are part of the domain envelope:
    # secondary foundations belong to domain 2, while the integration module
    # is shared equally. Generic LO-gap bridges are not counted as domain
    # evidence and therefore cannot hide a shortage of real subject content.
    bridge_by_id = {bridge.id: bridge for bridge in bridge_modules}
    for items in schedule.values():
        for item in items:
            bridge = bridge_by_id.get(item.get("bridge_module_id"))
            if not bridge:
                continue
            credits = float(item.get("credits") or bridge.credits or 0)
            code = str(bridge.course_id or "")
            if code.startswith("SECONDARY_"):
                domain_credits[1] += credits
            elif code.startswith("CORE_BRIDGE_") or code.startswith("AUTO_BRIDGE_") or code.startswith("QUALITY_BRIDGE_"):
                domain_credits[0] += credits / 2.0
                domain_credits[1] += credits / 2.0
    regulatory_credits = sum(
        int(item.get("credits") or 0)
        for items in schedule.values()
        for item in items
        if item.get("regulatory_required")
    )
    # Domain proportions describe the professional part of a curriculum.
    # Applying 40%+40% to all 240 credits made the requirement impossible once
    # common ГОСО units, practices and final attestation were included.
    domain_quota_base_credits = max(0, target_credits - regulatory_credits)
    domain_quota_violations = []
    for index, required_percent in enumerate(minimum_domain_percent):
        required_credits = domain_quota_base_credits * required_percent / 100.0
        if (
            required_percent > 0
            and domain_credits[index] + domain_quota_tolerance + 1e-9 < required_credits
        ):
            domain_quota_violations.append({
                "reason": "domain_credit_quota",
                "domain_index": index + 1,
                "domain": project_domains[index],
                "actual_credits": domain_credits[index],
                "required_credits": round(required_credits, 2),
                "required_percent": required_percent,
                "tolerance_credits": domain_quota_tolerance,
            })
    selected_course_ids = list(course_semester)
    selected_match_rows = db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version.id,
        MatchScore.course_id.in_(selected_course_ids or [-1]),
    ).all()
    matches_by_lo: Dict[int, List[MatchScore]] = {}
    matches_by_course: Dict[int, List[MatchScore]] = {}
    for row in selected_match_rows:
        matches_by_lo.setdefault(int(row.lo_id), []).append(row)
        matches_by_course.setdefault(int(row.course_id), []).append(row)
    selected_goso_lo_codes = {
        GOSO_COURSE_LO_CODES.get(str(course.course_id or "").removeprefix("GOSO-KZ-"))
        for course in db.query(Course).filter(Course.id.in_(selected_course_ids or [-1])).all()
        if str(course.course_id or "").startswith("GOSO-KZ-")
    }
    selected_goso_lo_codes.discard(None)
    coverage_by_lo, evidence_count = {}, 0
    lo_without_real_course = []
    for lo in project_version.learning_outcomes:
        rows = matches_by_lo.get(int(lo.id), [])
        scores = [
            max(0.0, min(1.0, max(
                float(row.score or 0.0),
                float((row.evidence_json or {}).get("epvo_expert_score") or 0.0),
            )))
            for row in rows
        ]
        if lo.lo_code in selected_goso_lo_codes:
            scores.append(1.0)
        real_max = max(scores) if scores else 0.0
        bridge_supported = False
        for bridge in bridge_modules:
            target_los = bridge.target_los or []
            if lo.lo_code in target_los:
                scores.append(0.75)
                bridge_supported = True
        product = 1.0
        for score in scores: product *= 1.0 - score
        coverage = 1.0 - product if scores else 0.0
        strong_evidence = sum(1 for score in scores if score >= MATCH_THRESHOLD)
        evidence_count += strong_evidence
        coverage_by_lo[lo.lo_code] = {
            "coverage": round(coverage, 4),
            "evidence_count": strong_evidence,
            "max_single_score": round(max(scores), 4) if scores else 0.0,
            "max_real_course_score": round(real_max, 4),
            "bridge_supported": bridge_supported,
        }
        # A bridge is an explicit generated learning unit with its own target
        # LO and assessment, so it can close a gap when no repository course
        # reaches the threshold. Keep that evidence visible as
        # ``bridge_supported``; only an LO with neither a credible real-course
        # signal nor a targeted bridge is a hard quality defect.
        if real_max < 0.5 and not bridge_supported:
            lo_without_real_course.append({
                "lo_code": lo.lo_code,
                "lo_text": lo.lo_text,
                "max_real_course_score": round(real_max, 4),
                "bridge_supported": bridge_supported,
            })
    coverages = [item["coverage"] for item in coverage_by_lo.values()]
    min_coverage = min(coverages) if coverages else 0.0
    average_coverage = sum(coverages) / len(coverages) if coverages else 0.0
    redundancy = _mean_pairwise_cosine_redundancy(selected_course_ids, db)
    embedding_mode = embedding_service.get_status()["mode"]
    redundancy_threshold = (
        REDUNDANCY_THRESHOLD
        if embedding_mode == "sentence_transformer"
        else FALLBACK_REDUNDANCY_THRESHOLD
    )
    quality_violations = []
    if min_coverage < settings.COVERAGE_THRESHOLD:
        quality_violations.append({"reason": "minimum_lo_coverage", "actual": round(min_coverage, 4), "required": settings.COVERAGE_THRESHOLD})
    if redundancy > redundancy_threshold:
        quality_violations.append({"reason": "redundancy", "actual": redundancy, "maximum": redundancy_threshold})
    courses_by_id = {
        course.id: course
        for course in db.query(Course).filter(Course.id.in_(selected_course_ids or [-1])).all()
    }
    competency_audit = _ict_competency_audit(list(courses_by_id.values()), constraints)
    weak_courses = []
    structural_foundations = []
    semester_misplacements = []
    selected_prerequisite_ids = {
        int(prerequisite_id)
        for items in schedule.values()
        for item in items
        for prerequisite_id in (item.get("prerequisites") or [])
        if prerequisite_id in selected_course_ids
    }
    for semester, items in schedule.items():
        for item in items:
            course_id = item.get("course_id")
            course = courses_by_id.get(course_id)
            if not course or str(course.domain or "").lower() == "general_goso_kz":
                continue
            rows = matches_by_course.get(int(course_id), [])
            expert_score = max(
                (float((row.evidence_json or {}).get("epvo_expert_score") or 0.0) for row in rows),
                default=0.0,
            )
            model_score = max((float(row.score or 0.0) for row in rows), default=0.0)
            max_score = max(model_score, expert_score)
            if max_score < 0.4 and expert_score < 0.5:
                evidence = {
                    "course_id": course.id,
                    "title": course.title,
                    "semester": semester,
                    "model_score": round(model_score, 4),
                    "epvo_expert_score": round(expert_score, 4),
                }
                if (
                    course.id in selected_prerequisite_ids
                    and item.get("selection_method") == "domain_quota_prerequisite_bundle"
                ):
                    structural_foundations.append({
                        **evidence,
                        "reason": "indirect_prerequisite_evidence",
                    })
                else:
                    weak_courses.append({
                        **evidence,
                        "reason": "weak_goal_lo_evidence",
                    })
            recommended = int(item.get("recommended_semester") or course.recommended_semester or 0)
            semantic_minimum = _semantic_min_semester(course.title, num_semesters)
            semantic_maximum = _semantic_max_semester(course.title, num_semesters)
            # In an interdisciplinary IT+health curriculum, a medical
            # foundation may legitimately follow the shared IT foundation;
            # cap it at the midpoint rather than forcing it into semesters
            # 1--3 solely because its title starts with "Основы".
            course_domain_text = str(course.domain or "").casefold()
            course_title_text = str(course.title or "").casefold().strip()
            if (
                any(marker in course_domain_text for marker in ("мед", "здрав", "medicine", "health"))
                and course_title_text.startswith(("основы ", "введение ", "fundamentals", "introduction"))
            ):
                semantic_maximum = max(semantic_maximum, (num_semesters + 1) // 2)
            if item.get("prerequisites"):
                # A real prerequisite chain can justify a later foundation
                # course. A late semester copied from one EPVO programme
                # cannot, by itself, turn an introductory course into an
                # advanced unit; keep this rule aligned with the scheduler.
                semantic_maximum = max(
                    semantic_maximum,
                    min(num_semesters, recommended + 2 if recommended else num_semesters),
                )
            # EPVO's typical semester is a placement preference. It becomes
            # a lower bound only for an explicitly locked source item; this
            # mirrors ``semester_rules.minimum_appropriate_semester`` used
            # by the scheduler and avoids the verifier rejecting a valid
            # prerequisite-ready course solely because another programme
            # taught it later.
            recommended_minimum = (
                max(1, recommended - 1)
                if recommended and item.get("source_semester_required")
                else 1
            )
            title_key = str(course.title or "").casefold().strip()
            explicit_foundation = title_key.startswith(
                ("основы ", "введение ", "fundamentals", "introduction")
            )
            clinical_foundation = any(
                marker in title_key
                for marker in (
                    "хирург", "surgery", "кардио", "гастро", "онколог",
                    "уролог", "невролог", "терапи", "педиатр", "клиническ",
                )
            )
            if explicit_foundation and not clinical_foundation:
                recommended_minimum = 1
            if recommended_minimum > semantic_maximum:
                recommended_minimum = 1
            effective_minimum = max(semantic_minimum, recommended_minimum)
            # Domain language can contain both a foundation marker and a
            # genuinely advanced clinical/technical role ("Основы хирургии").
            # Such signals must produce a valid interval, never min=5/max=3.
            effective_maximum = max(effective_minimum, semantic_maximum)
            if (
                semester < effective_minimum
                or semester > effective_maximum
            ):
                semester_misplacements.append({
                    "course_id": course.id,
                    "title": course.title,
                    "semester": semester,
                    "recommended_semester": recommended,
                    "semantic_minimum_semester": effective_minimum,
                    "semantic_maximum_semester": effective_maximum,
                    "reason": "course_too_early" if semester < effective_minimum else "course_too_late",
                })
    if lo_without_real_course:
        quality_violations.append({
            "reason": "lo_without_real_course",
            "count": len(lo_without_real_course),
            "required_real_score": 0.5,
        })
    if weak_courses:
        quality_violations.append({"reason": "weak_course_goal_lo_evidence", "count": len(weak_courses)})
    if structural_foundations:
        quality_violations.append({
            "reason": "prerequisite_without_direct_lo_evidence",
            "count": len(structural_foundations),
        })
    if semester_misplacements:
        quality_violations.append({"reason": "semester_appropriateness", "count": len(semester_misplacements)})
    if not competency_audit["passed"]:
        quality_violations.append({
            "reason": "missing_core_competency_blocks",
            "missing": competency_audit["missing"],
        })
    bridge_count = sum(
        1
        for items in schedule.values()
        for item in items
        if item.get("bridge_module_id") is not None
    )
    bridge_limit = bridge_module_limit(project_version)
    bridge_overflow = max(0, bridge_count - bridge_limit)
    if bridge_overflow:
        quality_violations.append({
            "reason": "bridge_module_limit_exceeded",
            "count": bridge_count,
            "limit": bridge_limit,
            "overflow": bridge_overflow,
        })
    pedagogical_audit = {
        "passed": (
            not lo_without_real_course
            and not weak_courses
            and not structural_foundations
            and not semester_misplacements
            and competency_audit["passed"]
        ),
        "engine": "SBERT + EPVO expert evidence + prerequisite/semester rules",
        "lo_without_real_course": lo_without_real_course,
        "weak_courses": weak_courses,
        "structural_foundations": structural_foundations,
        "semester_misplacements": semester_misplacements,
        "competency_blocks": competency_audit,
    }
    goso_compliance = evaluate_goso_compliance(schedule, project_version)
    # A curriculum unit without a direct programme-LO link is not merely a
    # warning: it has no auditable educational purpose and must not be active.
    course_lo_violations = len(weak_courses) + len(structural_foundations)
    # A bridge-supported LO is auditable but remains visible in the quality
    # report and bridge-economy score. Only an uncovered LO contributes a hard
    # admission violation; this lets an explicitly assessed generated module
    # close a genuine repository gap without hiding the fallback.
    real_lo_violations = len(lo_without_real_course)
    hard_count = len(prerequisite_violations) + len(load_violations) + len(credit_violations) + len(domain_quota_violations) + len(goso_compliance["violations"]) + course_lo_violations + real_lo_violations + bridge_overflow
    return {"feasible": hard_count == 0, "quality_passed": not quality_violations and goso_compliance["compliant"], "hard_violation_count": hard_count, "course_lo_violations": course_lo_violations, "bridge_module_count": bridge_count, "bridge_module_limit": bridge_limit, "bridge_module_overflow": bridge_overflow, "prerequisite_violations": prerequisite_violations, "semester_load_violations": load_violations, "goso_load_exemptions": sorted(goso_load_exemptions), "regulatory_credits_by_semester": regulatory_credits_by_semester, "credit_violations": credit_violations, "domain_quota_violations": domain_quota_violations, "domain_credits": {"domain1": round(domain_credits[0], 2), "domain2": round(domain_credits[1], 2)}, "domain_quota_base_credits": domain_quota_base_credits, "domain_quota_tolerance_credits": domain_quota_tolerance, "goso_compliance": goso_compliance, "pedagogical_audit": pedagogical_audit, "semester_loads": semester_loads, "nominal_semester_load": round(nominal_load, 2), "allowed_semester_load": {"min": round(min_load, 2), "max": round(max_load, 2)}, "target_credits": target_credits, "total_credits": total_credits, "credit_tolerance": credit_tolerance, "maximum_total_credits": target_credits + credit_tolerance, "min_lo_coverage": round(min_coverage, 4), "average_lo_coverage": round(average_coverage, 4), "coverage_threshold": settings.COVERAGE_THRESHOLD, "coverage_by_lo": coverage_by_lo, "evidence_count": evidence_count, "redundancy": redundancy, "redundancy_threshold": redundancy_threshold, "strict_redundancy_threshold": REDUNDANCY_THRESHOLD, "embedding_mode": embedding_mode, "quality_violations": quality_violations}


def _mean_pairwise_cosine_redundancy(course_ids: List[int], db: Session) -> float:
    """Mean pairwise cosine similarity from T6 (lower is better)."""
    if len(course_ids) < 2:
        return 0.0

    import numpy as np
    from app.kag.knowledge_graph import _build_course_vectors
    from app.models.course import Course

    courses = db.query(Course).filter(Course.id.in_(course_ids)).all()
    vectors = _build_course_vectors(courses, db)
    normalized = []
    for course_id in course_ids:
        vector = vectors.get(course_id)
        if vector is None:
            continue
        norm = np.linalg.norm(vector)
        if norm > 1e-9:
            normalized.append(vector / norm)
    if len(normalized) < 2:
        return 0.0

    similarities = [
        float(np.dot(normalized[i], normalized[j]))
        for i in range(len(normalized))
        for j in range(i + 1, len(normalized))
    ]
    return round(sum(similarities) / len(similarities), 4) if similarities else 0.0
