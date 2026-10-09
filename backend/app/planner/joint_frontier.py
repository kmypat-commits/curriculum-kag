"""Deterministic, atomic admission of real course prerequisite chains.

The database-backed frontier builder uses this policy before presenting any
course as an LO or credit candidate to the joint optimiser.
"""

from __future__ import annotations

from collections.abc import Mapping, Set

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.course import Course, course_prerequisites
from app.models.embedding import MatchScore
from app.models.epvo import EpvoDisciplineNormalized
from app.models.project import ProjectVersion
from app.planner.course_policy import education_level_course_allowed
from app.planner.course_policy import project_domain_terms
from app.planner.core_evidence import verified_matches
from app.planner.core_requirements import effective_requirements
from app.planner.domain_evidence import course_domain_shares, domain_label_matches
from app.planner.epvo_course_links import epvo_code_index, linked_course_id
from app.planner.goso import ensure_goso_items, is_redundant_goso_foundation
from app.planner.joint_contract import Candidate, PlanningProblem, PreferredCoreBlock, RequiredCoreBlock
from app.planner.match_aggregation import semantic_evidence_score
from app.planner.scheduler_utils import title_key
from app.planner.scoped_epvo_semesters import apply_scoped_epvo_semesters
from app.planner.semester_rules import foundation_max_semester, minimum_appropriate_semester
from app.planner.scheduler_domain_rules import has_foreign_professional_title
from app.planner.variant_scope import build_epvo_scope_index
from app.planner.verifier import LOAD_TOLERANCE, MATCH_THRESHOLD, REAL_COURSE_LO_THRESHOLD, TOTAL_CREDIT_TOLERANCE
from app.services.epvo_repository import epvo_row_matches_education_level


def prioritize_required_seeds(ranked_ids, required_ids, *, cap):
    """Reserve bounded frontier search slots for explicit methodist courses."""
    ordered = list(dict.fromkeys([*sorted(required_ids), *ranked_ids]))
    selected = ordered[:max(cap, len(required_ids))]
    return selected, len(ordered) - len(selected)


def reserve_preferred_seeds(block_candidates, ranking, *, budget):
    """Interleave profile blocks without consuming the whole LO frontier."""
    ranked = {
        block_id: sorted(ids, key=lambda cid: (-ranking.get(cid, 0.0), cid))
        for block_id, ids in block_candidates.items() if ids
    }
    order = sorted(ranked, key=lambda block_id: (-ranking.get(ranked[block_id][0], 0.0), block_id))
    chosen, seen = [], set()
    while len(chosen) < budget and any(ranked.values()):
        for block_id in order:
            if not ranked[block_id]:
                continue
            cid = ranked[block_id].pop(0)
            if cid not in seen:
                chosen.append(cid)
                seen.add(cid)
            if len(chosen) >= budget:
                break
    return chosen


def lo_pipeline_counts(
    evidence: Mapping[int, Mapping[str, float]],
    catalogue: Mapping[int, Candidate],
    admitted: tuple[Candidate, ...],
    required_los: tuple[str, ...],
) -> dict[str, dict[str, int | float]]:
    """Count verifier-strength real LO evidence at each frontier boundary."""
    return {
        code: {
            "scored": sum(scores.get(code, 0.0) >= REAL_COURSE_LO_THRESHOLD
                          for scores in evidence.values()),
            "scoped": sum(course.lo_scores.get(code, 0.0) >= REAL_COURSE_LO_THRESHOLD
                          for course in catalogue.values()),
            "admitted": sum(course.lo_scores.get(code, 0.0) >= REAL_COURSE_LO_THRESHOLD
                            for course in admitted),
            "max_scored": round(max(
                (scores.get(code, 0.0) for scores in evidence.values()), default=0.0,
            ), 4),
        }
        for code in required_los
    }



def prerequisite_closure(
    course_id: int,
    prerequisites: Mapping[int, tuple[int, ...]],
    admissible_ids: Set[int],
    fixed_ids: Set[int] = frozenset(),
) -> tuple[int, ...] | None:
    """Return parents-before-child closure, or None for an invalid chain.

    Missing, cyclic, or independently inadmissible parents invalidate the
    *whole* child; silently shortening the chain would violate the verifier.
    """
    ordered: list[int] = []
    done: set[int] = set()
    visiting: set[int] = set()

    def visit(current: int) -> bool:
        if current in fixed_ids:
            return True
        if current in visiting or current not in admissible_ids or current not in prerequisites:
            return False
        if current in done:
            return True
        visiting.add(current)
        for parent in sorted(set(prerequisites[current])):
            if not visit(parent):
                visiting.remove(current)
                return False
        visiting.remove(current)
        done.add(current)
        ordered.append(current)
        return True

    return tuple(ordered) if visit(course_id) else None


def admit_candidate_chains(
    catalogue: Mapping[int, Candidate],
    ranked_ids: tuple[int, ...],
    *,
    duplicate_ids: Set[int],
    limit: int,
    fixed_semesters: Mapping[int, int] | None = None,
) -> tuple[tuple[Candidate, ...], dict[str, int]]:
    """Admit ranked roots atomically with every parent, under a hard cap.

    The caller has already applied programme-domain and education-level
    admission. A removed regulatory duplicate cannot contribute LO evidence.
    """
    if limit < 1:
        raise ValueError("frontier limit must be positive")
    available = set(catalogue).difference(duplicate_ids)
    fixed_semesters = fixed_semesters or {}
    parents = {cid: candidate.prerequisites for cid, candidate in catalogue.items()}
    selected: dict[int, Candidate] = {}
    exclusions = {
        "goso_duplicate": 0,
        "missing_or_inadmissible_prerequisite": 0,
        "unverified_course_evidence": 0,
        "illegal_prerequisite_semester": 0,
        "frontier_capacity": 0,
    }
    for course_id in ranked_ids:
        if course_id in duplicate_ids:
            exclusions["goso_duplicate"] += 1
            continue
        closure = prerequisite_closure(course_id, parents, available, fixed_semesters.keys())
        if closure is None:
            exclusions["missing_or_inadmissible_prerequisite"] += 1
            continue
        if any(
            max(catalogue[member].lo_scores.values(), default=0.0) < MATCH_THRESHOLD
            for member in closure
        ):
            exclusions["unverified_course_evidence"] += 1
            continue
        earliest: dict[int, int] = {}
        for member in closure:
            course = catalogue[member]
            after = max(
                (earliest[parent] if parent in earliest else fixed_semesters[parent]
                 for parent in course.prerequisites),
                default=0,
            )
            legal = [semester for semester in course.allowed_semesters if semester > after]
            if not legal:
                exclusions["illegal_prerequisite_semester"] += 1
                break
            earliest[member] = min(legal)
        if len(earliest) != len(closure):
            continue
        if len(selected.keys() | set(closure)) > limit:
            exclusions["frontier_capacity"] += 1
            continue
        for member in closure:
            selected.setdefault(member, catalogue[member])
    return tuple(selected.values()), exclusions


def build_joint_frontier(
    version: ProjectVersion, db: Session, *, limit: int
) -> PlanningProblem:
    """Retrieve programme-specific evidence and close each admissible chain.

    No rank-boosted MatchScore may masquerade as raw semantic LO evidence.
    ``ensure_goso_items`` follows the existing transaction and does not commit.
    """
    if limit < 1:
        raise ValueError("frontier limit must be positive")
    constraints = version.project.constraints_json or {}
    requirements = effective_requirements(constraints.get("curriculum_requirements"))
    methodist_required_ids = set(requirements["required_course_ids"]) if requirements else set()
    required_blocks = [block for block in requirements["core_blocks"]
                       if block["requirement"] == "required"] if requirements else []
    preferred_blocks = [block for block in requirements["core_blocks"]
                        if block["requirement"] == "preferred"] if requirements else []
    saved_confirmations = constraints.get("curriculum_confirmations") or []
    block_seed_ids = {
        int(record["course_id"])
        for record in saved_confirmations
        if record.get("status") == "confirmed"
        and record.get("project_version_id") == version.id
        and isinstance(record.get("course_id"), int)
        and any(record.get("block_id") == block["id"]
                and record.get("course_id") in block["accepted_course_ids"]
                for block in required_blocks)
    }
    excluded_course_ids = {
        int(value) for value in (constraints.get("excluded_course_ids") or [])
        if str(value).isdigit()
    }
    semesters = int(constraints.get("total_semesters") or 8)
    domains = (str(version.project.domain1 or ""), str(version.project.domain2 or ""))
    admission_domains = project_domain_terms(version, db)
    professional = {
        lo.id: str(lo.lo_code)
        for lo in version.learning_outcomes
        if not str(lo.lo_code or "").startswith("LO-GOSO-")
    }
    evidence: dict[int, dict[str, float]] = {}
    ranking: dict[int, float] = {}
    aggregates: dict[int, dict] = {}
    matches = db.query(MatchScore).filter(
        MatchScore.project_version_id == version.id
    ).order_by(MatchScore.course_id.asc(), MatchScore.lo_id.asc()).all()
    for match in matches:
        code = professional.get(match.lo_id)
        if not code or match.course_id is None:
            continue
        cid = int(match.course_id)
        expert = float((match.evidence_json or {}).get("epvo_expert_score") or 0)
        raw = max(semantic_evidence_score(match), expert)
        score_map = evidence.setdefault(cid, {})
        score_map[code] = max(score_map.get(code, 0.0), raw)
        ranking[cid] = max(ranking.get(cid, 0.0), float(match.score or 0), raw)
        aggregate = aggregates.setdefault(cid, {
            "max": 0.0, "expert": 0.0, "professional_lo_codes": set(),
            "lo_scores": {},
        })
        aggregate["max"] = max(aggregate["max"], float(match.score or 0))
        aggregate["expert"] = max(aggregate["expert"], expert)
        if raw >= MATCH_THRESHOLD:
            aggregate["professional_lo_codes"].add(code)
        aggregate["lo_scores"][code] = score_map[code]

    # Select a balanced seed from every LO before the global ranking. The
    # atomic admission step may still require extra room for whole chains.
    ranked_ids: list[int] = []
    seen: set[int] = set()
    by_lo: dict[str, list[int]] = {}
    for code in sorted(set(professional.values())):
        by_lo[code] = sorted(
            (cid for cid, scores in evidence.items() if scores.get(code, 0) >= MATCH_THRESHOLD),
            key=lambda cid: (-evidence[cid][code], -ranking[cid], cid),
        )[:limit]
    for position in range(limit):
        for code in sorted(by_lo):
            if position >= len(by_lo[code]):
                continue
            cid = by_lo[code][position]
            if cid not in seen:
                ranked_ids.append(cid)
                seen.add(cid)
    for cid in sorted(ranking, key=lambda key: (-ranking[key], key)):
        if cid not in seen:
            ranked_ids.append(cid)
            seen.add(cid)
    preferred_candidates = {
        block["id"]: {
            record["course_id"] for record in saved_confirmations
            if record.get("status") == "confirmed"
            and record.get("project_version_id") == version.id
            and isinstance(record.get("course_id"), int)
            and record.get("block_id") == block["id"]
            and record["course_id"] in block["accepted_course_ids"]
        }
        for block in preferred_blocks
    }
    preferred_seed_ids = reserve_preferred_seeds(
        preferred_candidates, ranking, budget=max(1, limit // 2),
    ) if preferred_blocks else []
    seed_cap = max(limit * 4, limit + len(professional))
    ranked_ids, omitted_seed_count = prioritize_required_seeds(
        [*preferred_seed_ids, *ranked_ids], methodist_required_ids | block_seed_ids,
        cap=seed_cap,
    )

    # Load only ranked IDs and their recursive parent closure. No full Course
    # catalogue scan; parent edges come directly from the association table.
    loaded: dict[int, Course] = {}
    raw_parents: dict[int, tuple[int, ...]] = {}
    pending = set(ranked_ids)
    queried: set[int] = set()
    while pending:
        batch = pending.difference(queried)
        if not batch:
            break
        queried.update(batch)
        rows = db.query(Course).filter(Course.id.in_(sorted(batch))).all()
        loaded.update((int(course.id), course) for course in rows)
        edges = db.execute(
            course_prerequisites.select().where(
                course_prerequisites.c.course_id.in_(sorted(batch))
            )
        ).fetchall()
        collected: dict[int, set[int]] = {cid: set() for cid in batch}
        for row in edges:
            collected[int(row.course_id)].add(int(row.prerequisite_id))
        raw_parents.update((cid, tuple(sorted(values))) for cid, values in collected.items())
        pending = {
            parent for values in collected.values() for parent in values
            if parent not in queried
        }

    scope = build_epvo_scope_index(
        db, version=version, constraints=constraints, aggregates=aggregates,
        courses=loaded, title_key=title_key,
    )
    epvo_index = epvo_code_index(loaded)
    known_epvo_source: set[int] = set()
    level_eligible_source: set[int] = set()
    if loaded:
        source_rows = db.query(EpvoDisciplineNormalized).filter(or_(
            EpvoDisciplineNormalized.approved_course_id.in_(tuple(loaded)),
            EpvoDisciplineNormalized.id.in_(tuple(epvo_index) or (-1,)),
        )).all()
        for row in source_rows:
            linked = linked_course_id(row, epvo_index)
            if linked is None:
                continue
            known_epvo_source.add(int(linked))
            if epvo_row_matches_education_level(row, constraints.get("education_level")):
                level_eligible_source.add(int(linked))
    fixed_items = ensure_goso_items(version, db)
    fixed_schedule = {semester: [] for semester in range(1, semesters + 1)}
    for item in fixed_items:
        semester = int(item.get("recommended_semester") or 1)
        if semester not in fixed_schedule:
            raise ValueError("regulatory item outside programme semesters")
        fixed_schedule[semester].append(item)
    required_ids = {int(item["course_id"]) for item in fixed_items}
    has_legal_goso = any(
        "основы права" in str(item.get("title") or "").casefold()
        for item in fixed_items
    )
    is_kz = str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() == "KZ"
    scoped_programme = any(str(constraints.get(key) or "").strip() for key in (
        "group_code", "direction_code", "secondary_group_code",
        "secondary_direction_code",
    ))
    scoped_items = {
        int(item["course_id"]): item
        for item in apply_scoped_epvo_semesters(
            [{"course_id": cid, "recommended_semester": course.recommended_semester}
             for cid, course in sorted(loaded.items())], version, db,
        )
    }
    catalogue: dict[int, Candidate] = {}
    duplicate_ids: set[int] = set(required_ids)
    exclusions = {"out_of_domain_or_level": 0, "no_legal_semester": 0,
                  "excluded_by_methodist": 0,
                  "foreign_professional_context": 0}
    for cid in sorted(loaded):
        if cid in excluded_course_ids:
            exclusions["excluded_by_methodist"] += 1
            continue
        course = loaded[cid]
        item = {
            "course_id": cid, "title": str(course.title or ""),
            "domain": str(course.domain or ""), "credits": int(course.credits or 0),
            "recommended_semester": scoped_items[cid].get("recommended_semester"),
            "prerequisites": list(raw_parents.get(cid, ())),
            "type": course.cycle_component or "mandatory",
            "selection_method": "joint_real_course",
            "admission_score": round(max(evidence.get(cid, {}).values(), default=0.0), 4),
            "admission_los": sorted(
                code for code, score in evidence.get(cid, {}).items()
                if score >= MATCH_THRESHOLD
            ),
        }
        if scoped_items[cid].get("_scoped_epvo_semester"):
            item["_scoped_epvo_semester"] = True
        title = item["title"].casefold().strip()
        if (
            int(item.get("recommended_semester") or 0) == 1
            and title.startswith(("введение ", "основы ", "introduction ", "fundamentals "))
        ):
            item["_scoped_epvo_semester"] = True
            item["source_semester_required"] = True
        if is_redundant_goso_foundation(
            item, is_kz=is_kz, has_legal_goso=has_legal_goso,
            required_ids=required_ids,
        ):
            duplicate_ids.add(cid)
        if has_foreign_professional_title(course, admission_domains):
            exclusions["foreign_professional_context"] += 1
            continue
        if not education_level_course_allowed(course, constraints.get("education_level")):
            exclusions["out_of_domain_or_level"] += 1
            continue
        if cid in known_epvo_source and cid not in level_eligible_source:
            exclusions["out_of_domain_or_level"] += 1
            continue
        label_ok = any(domain_label_matches(course.domain, [domain]) for domain in domains if domain)
        scope_ok = cid in scope.level_scope_allowed_ids
        if not (label_ok or scope_ok):
            exclusions["out_of_domain_or_level"] += 1
            continue
        if scoped_programme and not scope_ok and max(evidence.get(cid, {}).values(), default=0) < 0.55:
            exclusions["out_of_domain_or_level"] += 1
            continue
        lower = minimum_appropriate_semester(item, semesters)
        upper = min(
            semesters, foundation_max_semester(item["title"], semesters),
            int(item.get("latest_semester") or semesters),
        )
        if raw_parents.get(cid) and item.get("recommended_semester"):
            upper = max(upper, min(semesters, int(item["recommended_semester"]) + 2))
        allowed = tuple(range(lower, upper + 1))
        if not allowed or item["credits"] <= 0:
            exclusions["no_legal_semester"] += 1
            continue
        shares = course_domain_shares(
            item_domain=item["domain"], canonical_domain=course.domain,
            project_domains=domains,
            scoped_shares=scope.domain_shares_by_course.get(cid),
        )
        catalogue[cid] = Candidate(
            course_id=cid, item=item, allowed_semesters=allowed,
            prerequisites=raw_parents.get(cid, ()), lo_scores=evidence.get(cid, {}),
            domain_shares=shares, utility=ranking.get(cid, 0.0),
        )
    from app.config import settings
    from app.planner.content_evaluation import prioritise_candidates
    from app.services.content_evaluation import profile_for_version
    mode = constraints.get('content_evaluation_mode', settings.CONTENT_EVALUATION_MODE)
    updated = prioritise_candidates(tuple(catalogue.values()), loaded,
                                    profile_for_version(version), mode=mode)
    catalogue = {candidate.course_id: candidate for candidate in updated}
    if mode == 'prioritise':
        ranked_ids = sorted(ranked_ids, key=lambda cid: (
            -catalogue[cid].utility if cid in catalogue else -ranking.get(cid, 0.0), cid))
    candidates, chain_exclusions = admit_candidate_chains(
        catalogue, tuple(ranked_ids), duplicate_ids=duplicate_ids, limit=limit,
        fixed_semesters={
            int(item["course_id"]): semester
            for semester, items in fixed_schedule.items()
            for item in items
        },
    )
    exclusions.update(chain_exclusions)
    exclusions["seed_truncated"] = omitted_seed_count
    exclusions["lo_evidence_pipeline"] = lo_pipeline_counts(
        evidence, catalogue, candidates, tuple(sorted(set(professional.values()))),
    )
    confirmed = verified_matches(
        requirements["core_blocks"] if requirements else [], saved_confirmations,
        loaded, project_version_id=version.id,
    ) if requirements else {}
    usable_ids = {candidate.course_id for candidate in candidates} | {
        int(item["course_id"]) for items in fixed_schedule.values()
        for item in items if item.get("course_id") is not None
    }
    core_blocks = tuple(
        RequiredCoreBlock(
            block_id=block["id"],
            course_ids=tuple(sorted(confirmed.get(block["id"], set()) & usable_ids)),
            min_courses=block["min_courses"], min_credits=block["min_credits"],
        )
        for block in required_blocks
    )
    preferred_core_blocks = tuple(
        PreferredCoreBlock(
            block_id=block["id"],
            course_ids=tuple(sorted(confirmed.get(block["id"], set()) & usable_ids)),
            min_courses=block["min_courses"], min_credits=block["min_credits"],
        )
        for block in preferred_blocks
    )
    exclusions["preferred_seed_omitted"] = max(
        0, len(set().union(*preferred_candidates.values())) - len(preferred_seed_ids),
    ) if preferred_candidates else 0
    from app.planner.credit_policy import total_credit_tolerance
    tolerance = total_credit_tolerance(constraints, legacy_default=TOTAL_CREDIT_TOLERANCE)
    target = int(constraints.get("total_credits") or 240)
    fixed_credits = sum(int(item.get("credits") or 0) for item in fixed_items)
    quota_base = max(0, target - fixed_credits)
    quota_tolerance = max(0.0, float(constraints.get("domain_quota_tolerance_credits", 3) or 0))
    interdisciplinary = str(constraints.get("program_type") or "standard").lower() in {
        "interdisciplinary", "joint",
    }
    percentages = (
        float(constraints.get("min_domain1_percent") or 0),
        float(constraints.get("min_domain2_percent") or 0) if interdisciplinary else 0.0,
    )
    nominal = float(constraints.get("max_credits_per_semester", target / max(semesters, 1)))
    return PlanningProblem(
        candidates=candidates, fixed_schedule=fixed_schedule,
        required_los=tuple(sorted(set(professional.values()))),
        target_credits=target, credit_tolerance=tolerance,
        min_load=max(0.0, nominal - LOAD_TOLERANCE),
        max_load=nominal + LOAD_TOLERANCE,
        domain_minima=tuple(max(0.0, quota_base * percent / 100 - quota_tolerance)
                             for percent in percentages),
        exclusions=exclusions,
        frontier_truncated=(
            chain_exclusions["frontier_capacity"] > 0 or omitted_seed_count > 0
        ),
        required_course_ids=tuple(sorted(methodist_required_ids)),
        required_core_blocks=core_blocks,
        preferred_core_blocks=preferred_core_blocks,
    )
