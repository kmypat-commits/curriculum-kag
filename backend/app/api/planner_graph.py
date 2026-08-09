from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.bridge_module import BridgeModule
from app.models.course import Course, CourseChunk, course_prerequisites
from app.models.embedding import MatchFeedback, MatchScore
from app.models.epvo import EpvoDisciplineNormalized
from app.models.user import User
from app.services.auth import get_current_user
from app.services.content_localization import course_localization_map
from app.kag.bridge_generator import call_llm


router = APIRouter()

@router.get("/version/{project_version_id}/graph")
async def get_plan_graph(
    project_version_id: int,
    variant: str | None = None,
    include_semantic: bool = Query(False, description="Включить тяжёлый семантический слой связей"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the selected curriculum as an explainable prerequisite DAG."""
    from app.models.plan import Plan, PlanItem

    query = db.query(Plan).filter(Plan.project_version_id == project_version_id)
    if variant:
        query = query.filter(Plan.variant_type == variant.upper())
    plan = query.order_by(Plan.is_active.desc(), Plan.id.desc()).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Сначала сформируйте варианты учебного плана")
    version = plan.project_version
    constraints = version.project.constraints_json or {}
    primary_group = str(constraints.get("group_code") or "")
    primary_direction = str(constraints.get("direction_code") or "")
    secondary_group = str(constraints.get("secondary_group_code") or "")
    secondary_direction = str(constraints.get("secondary_direction_code") or "")
    domain_quota = {
        (version.project.domain1 or "").lower().strip(): int(constraints.get("min_domain1_percent") or 0),
        (version.project.domain2 or "").lower().strip(): int(constraints.get("min_domain2_percent") or 0),
    }

    items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
    item_by_course_id = {item.course_id: item for item in items if item.course_id is not None}
    course_ids_in_plan = {item.course_id for item in items if item.course_id is not None}
    postrequisites = {course_id: [] for course_id in course_ids_in_plan}
    for item in items:
        for prerequisite_id in item.prerequisites_snapshot or []:
            if prerequisite_id in postrequisites and item.course_id is not None:
                postrequisites[prerequisite_id].append(item.course_id)

    # Load graph entities and evidence in batches.  Previously this endpoint
    # issued several SQL queries per course and per LO, so simply opening the
    # graph could take seconds even while no generation was running.
    related_course_ids = set(course_ids_in_plan)
    for item in items:
        related_course_ids.update(item.prerequisites_snapshot or [])
    course_by_id = {
        course.id: course
        for course in db.query(Course).filter(Course.id.in_(related_course_ids or {-1})).all()
    }
    localization_by_course = course_localization_map(db, course_by_id.keys())
    bridge_ids_in_plan = {
        int(item.bridge_module_id) for item in items if item.bridge_module_id is not None
    }
    bridge_by_id = {
        bridge.id: bridge
        for bridge in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids_in_plan or {-1})).all()
    }
    epvo_ids = set()
    for course in course_by_id.values():
        if str(course.course_id or "").startswith("EPVO-"):
            try:
                epvo_ids.add(int(str(course.course_id).split("-", 1)[1]))
            except ValueError:
                pass
    epvo_by_id = {
        row.id: row
        for row in db.query(EpvoDisciplineNormalized).filter(
            EpvoDisciplineNormalized.id.in_(epvo_ids or {-1})
        ).all()
    }
    match_rows = db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version_id,
        MatchScore.course_id.in_(course_ids_in_plan or {-1}),
        MatchScore.score >= 0.4,
    ).order_by(MatchScore.score.desc(), MatchScore.id.asc()).all()
    matches_by_course = {}
    match_by_pair = {}
    for match in match_rows:
        matches_by_course.setdefault(int(match.course_id), []).append(match)
        match_by_pair.setdefault((int(match.course_id), int(match.lo_id)), match)
    chunk_ids = {int(match.chunk_id) for match in match_rows if match.chunk_id}
    chunk_by_id = {
        chunk.id: chunk
        for chunk in db.query(CourseChunk).filter(CourseChunk.id.in_(chunk_ids or {-1})).all()
    }
    feedback_by_pair = {}
    feedback_rows = db.query(MatchFeedback).filter(
        MatchFeedback.project_version_id == project_version_id,
        MatchFeedback.course_id.in_(course_ids_in_plan or {-1}),
    ).order_by(MatchFeedback.created_at.asc(), MatchFeedback.id.asc()).all()
    for feedback in feedback_rows:
        feedback_by_pair[(int(feedback.course_id), int(feedback.lo_id))] = feedback

    nodes, node_ids = [], set()
    for item in items:
        if item.course_id is not None:
            course = course_by_id.get(item.course_id)
            if not course:
                continue
            node_id = f"course-{course.id}"
            prerequisite_courses = [
                course_by_id[course_id]
                for course_id in (item.prerequisites_snapshot or [])
                if course_id in course_by_id
            ]
            postrequisite_courses = [
                course_by_id[course_id]
                for course_id in postrequisites.get(course.id, [])
                if course_id in course_by_id
            ]
            epvo_scope = None
            if (course.course_id or "").startswith("EPVO-"):
                try:
                    epvo_id = int(course.course_id.split("-", 1)[1])
                except ValueError:
                    epvo_id = None
                row = epvo_by_id.get(epvo_id) if epvo_id else None
                if row:
                    groups = row.group_codes or []
                    directions = row.direction_codes or []
                    epvo_scope = {
                        "discipline_id": row.id,
                        "groups": groups[:8],
                        "directions": directions[:8],
                        "matched_group": primary_group if primary_group in groups else secondary_group if secondary_group in groups else None,
                        "matched_direction": primary_direction if primary_direction in directions else secondary_direction if secondary_direction in directions else None,
                        "typical_semester": row.typical_semester,
                        "typical_credits": row.typical_credits,
                        "source_program_count": len(row.source_programs or []),
                    }
            nodes.append({
                "id": node_id, "entity_id": course.id, "kind": "course",
                "code": course.course_id, "title": course.title,
                "title_translations": localization_by_course.get(course.id, {}).get("title_translations", {}),
                "description_translations": localization_by_course.get(course.id, {}).get("description_translations", {}),
                "translation_status": localization_by_course.get(course.id, {}).get("translation_status"),
                "semester": item.semester, "credits": item.credits,
                "domain": course.domain, "component": item.course_type,
                "description": course.description,
                "learning_outcomes": course.learning_outcomes or [],
                "topics": course.topics or [],
                "assessment_methods": course.assessment_methods or [],
                "prerequisite_codes": [f"{pre.course_id}: {pre.title}" for pre in prerequisite_courses],
                "postrequisite_codes": [f"{post.course_id}: {post.title}" for post in postrequisite_courses],
                "recommended_semester": course.recommended_semester,
                "epvo_scope": epvo_scope,
                "curriculum_role": (
                    "foundation" if item.semester <= 2 and not item.prerequisites_snapshot
                    else "integrator" if postrequisites.get(course.id)
                    else "specialization"
                ),
            })
        else:
            bridge = bridge_by_id.get(item.bridge_module_id)
            if not bridge:
                continue
            node_id = f"bridge-{bridge.id}"
            nodes.append({
                "id": node_id, "entity_id": bridge.id, "kind": "bridge",
                "code": bridge.course_id, "title": bridge.title,
                "semester": item.semester, "credits": item.credits,
                "domain": "interdisciplinary", "component": item.course_type,
                "description": bridge.description,
                "learning_outcomes": bridge.learning_outcomes or [],
                "topics": bridge.topics or [],
                "assessment_methods": bridge.assessment_methods or [],
            })
        node_ids.add(node_id)

    edges = []
    adjacency = {node_id: [] for node_id in node_ids}
    course_to_node = {node["entity_id"]: node["id"] for node in nodes if node["kind"] == "course"}
    selected_course_ids = set(course_to_node)
    catalogue_pairs = {
        (int(row.course_id), int(row.prerequisite_id))
        for row in db.execute(
            course_prerequisites.select().where(
                course_prerequisites.c.course_id.in_(selected_course_ids or {-1}),
                course_prerequisites.c.prerequisite_id.in_(selected_course_ids or {-1}),
            )
        ).fetchall()
    }
    for item in items:
        target = course_to_node.get(item.course_id)
        if not target:
            continue
        for prerequisite_id in item.prerequisites_snapshot or []:
            source = course_to_node.get(prerequisite_id)
            if not source:
                continue
            origin = (
                "catalogue"
                if (int(item.course_id), int(prerequisite_id)) in catalogue_pairs
                else "plan_inferred"
            )
            edges.append({
                "id": f"{source}-{target}",
                "source": source,
                "target": target,
                "relation": "prerequisite",
                "origin": origin,
                "explanation": (
                    "Подтверждённая связь репозитория дисциплин."
                    if origin == "catalogue"
                    else "Связь выведена внутри плана по предметной близости и более раннему семестру."
                ),
                "explanation_translations": (
                    {
                        "ru": "Подтверждённая связь репозитория дисциплин.",
                        "kk": "Пәндер репозиторийіндегі расталған байланыс.",
                        "en": "Confirmed course-repository relation.",
                    }
                    if origin == "catalogue"
                    else {
                        "ru": "Связь выведена внутри плана по предметной близости и более раннему семестру.",
                        "kk": "Байланыс пәндік жақындық пен ертерек семестр негізінде жоспар ішінде шығарылды.",
                        "en": "Plan-local relation inferred from subject proximity and an earlier semester.",
                    }
                ),
            })
            adjacency[source].append(target)

    # Add deeper evidence-based competency flow without pretending that these
    # are formal prerequisites.  Two courses are connected when an earlier
    # course and a later course both provide strong evidence for the same
    # programme LO.  Limit incoming support edges to keep the graph readable.
    lo_by_node = {node["id"]: {} for node in nodes}
    lo_codes = {lo.id: lo.lo_code for lo in version.learning_outcomes}
    lo_texts = {lo.id: lo.lo_text for lo in version.learning_outcomes}
    for node in nodes:
        if node["kind"] == "course":
            rows = matches_by_course.get(int(node["entity_id"]), [])
            for row in rows:
                code = lo_codes.get(row.lo_id)
                if code:
                    lo_by_node[node["id"]][code] = max(
                        lo_by_node[node["id"]].get(code, 0.0),
                        float(row.score),
                    )
        else:
            bridge = bridge_by_id.get(node["entity_id"])
            for code in (bridge.target_los or []) if bridge else []:
                lo_by_node[node["id"]][code] = 0.75

    for node in nodes:
        evidence = lo_by_node.get(node["id"], {})
        code_to_id = {value: key for key, value in lo_codes.items()}
        lo_details = []
        for code, score in sorted(evidence.items(), key=lambda item: item[1], reverse=True):
            lo_id = code_to_id.get(code)
            detail = {
                "lo_id": lo_id,
                "lo_code": code,
                "lo_text": lo_texts.get(lo_id, ""),
                "score": round(score, 3),
                "source": "ai_prediction" if node["kind"] == "course" else "bridge_target",
                "evidence": {},
                "expert_feedback": None,
            }
            if node["kind"] == "course" and lo_id:
                pair = (int(node["entity_id"]), int(lo_id))
                match = match_by_pair.get(pair)
                if match:
                    detail["evidence"] = match.evidence_json or {}
                    if (detail["evidence"] or {}).get("epvo_expert_score", 0) > 0:
                        detail["source"] = "epvo_expert"
                    if match.chunk_id:
                        chunk = chunk_by_id.get(match.chunk_id)
                        if chunk:
                            detail["chunk"] = {
                                "type": chunk.chunk_type,
                                "text": (chunk.chunk_text or "")[:260],
                            }
                    feedback = feedback_by_pair.get(pair)
                    if feedback:
                        detail["expert_feedback"] = {
                            "verdict": feedback.verdict,
                            "corrected_score": feedback.corrected_score,
                            "comment": feedback.comment,
                        }
            lo_details.append(detail)
        node["lo_evidence"] = lo_details
        node["selection_reason"] = (
            "Закрывает результаты программы и поддерживает последовательность пререквизитов"
            if evidence else "Включена для кредитного баланса и предметной целостности"
        )
        node["selection_reason_translations"] = (
            {"ru": node["selection_reason"], "kk": "Бағдарлама нәтижелерін жабады және пререквизиттер реттілігін қолдайды", "en": "Covers programme outcomes and supports prerequisite sequence"}
            if evidence else {"ru": node["selection_reason"], "kk": "Кредит балансы және пәндік тұтастық үшін қосылды", "en": "Included for credit balance and domain integrity"}
        )
        top_expert = next((item for item in lo_details if item.get("source") == "epvo_expert"), None)
        domain_key = (node.get("domain") or "").lower().strip()
        quota = next((percent for key, percent in domain_quota.items() if key and (key in domain_key or domain_key in key)), 0)
        epvo_scope = node.get("epvo_scope") or {}
        semester = node['semester']
        rec_sem = node.get('recommended_semester')
        rec_sem_ru = rec_sem or 'не указан'
        rec_sem_kk = rec_sem or 'көрсетілмеген'
        rec_sem_en = rec_sem or 'not specified'
        domain = node.get('domain')
        domain_ru = domain or 'не указан'
        domain_kk = domain or 'көрсетілмеген'
        domain_en = domain or 'not specified'
        node["why_selected"] = {
            "main_reason": node["selection_reason"],
            "role": node.get("curriculum_role") or ("bridge" if node["kind"] == "bridge" else "course"),
            "semester_reason": f"Размещена в семестре {semester} с учётом пререквизитов, нагрузки и рекомендуемого семестра {rec_sem_ru}.",
            "semester_reason_translations": {
                "ru": f"Размещена в семестре {semester} с учётом пререквизитов, нагрузки и рекомендуемого семестра {rec_sem_ru}.",
                "kk": f"{semester}-семестрге пререквизиттер, жүктеме және ұсынылатын семестр {rec_sem_kk} ескеріліп орналастырылды.",
                "en": f"Placed in semester {semester} considering prerequisites, load, and recommended semester {rec_sem_en}.",
            },
            "domain_reason": f"Домен: {domain_ru}; минимальная квота области: {quota}%.",
            "domain_reason_translations": {
                "ru": f"Домен: {domain_ru}; минимальная квота области: {quota}%.",
                "kk": f"Домен: {domain_kk}; саланың ең төменгі квотасы: {quota}%.",
                "en": f"Domain: {domain_en}; minimum domain quota: {quota}%.",
            },
            "epvo_reason": (
                f"ЕПВО: группа {epvo_scope.get('matched_group') or '—'}, направление {epvo_scope.get('matched_direction') or '—'}; "
                f"типовой семестр {epvo_scope.get('typical_semester') or '—'}, источников программ {epvo_scope.get('source_program_count') or 0}."
                if epvo_scope else "Не является дисциплиной из нормализованного слоя ЕПВО."
            ),
            "epvo_reason_translations": (
                {
                    "ru": f"ЕПВО: группа {epvo_scope.get('matched_group') or '—'}, направление {epvo_scope.get('matched_direction') or '—'}; типовой семестр {epvo_scope.get('typical_semester') or '—'}, источников программ {epvo_scope.get('source_program_count') or 0}.",
                    "kk": f"ЕПВО: тобы {epvo_scope.get('matched_group') or '—'}, бағыты {epvo_scope.get('matched_direction') or '—'}; үлгілік семестр {epvo_scope.get('typical_semester') or '—'}, бағдарлама көздері {epvo_scope.get('source_program_count') or 0}.",
                    "en": f"EPVO: group {epvo_scope.get('matched_group') or '—'}, direction {epvo_scope.get('matched_direction') or '—'}; typical semester {epvo_scope.get('typical_semester') or '—'}, source programmes {epvo_scope.get('source_program_count') or 0}.",
                }
                if epvo_scope else {
                    "ru": "Не является дисциплиной из нормализованного слоя ЕПВО.",
                    "kk": "ЕПВО нормаланған қабатының пәні емес.",
                    "en": "Not an EPVO normalized-layer course.",
                }
            ),
            "expert_reason": (
                f"Экспертная поддержка ЕПВО для {top_expert.get('lo_code')}: {round((top_expert.get('evidence') or {}).get('epvo_expert_score', 0) * 100)}%."
                if top_expert else "Экспертная поддержка ЕПВО для текущих LO не найдена."
            ),
            "expert_reason_translations": (
                {
                    "ru": f"Экспертная поддержка ЕПВО для {top_expert.get('lo_code')}: {round((top_expert.get('evidence') or {}).get('epvo_expert_score', 0) * 100)}%.",
                    "kk": f"ЕПВО сараптамалық қолдауы {top_expert.get('lo_code')}: {round((top_expert.get('evidence') or {}).get('epvo_expert_score', 0) * 100)}%.",
                    "en": f"EPVO expert support for {top_expert.get('lo_code')}: {round((top_expert.get('evidence') or {}).get('epvo_expert_score', 0) * 100)}%.",
                }
                if top_expert else {
                    "ru": "Экспертная поддержка ЕПВО для текущих LO не найдена.",
                    "kk": "Ағымдағы LO үшін ЕПВО сараптамалық қолдауы табылмады.",
                    "en": "EPVO expert support for current LOs not found.",
                }
            ),
            "lo_count": len(lo_details),
            "top_lo": lo_details[0] if lo_details else None,
            "prerequisites": node.get("prerequisite_codes", []),
            "postrequisites": node.get("postrequisite_codes", []),
        }

    node_by_id = {node["id"]: node for node in nodes}
    formal_pairs = {(edge["source"], edge["target"]) for edge in edges}
    competency_edges = []
    for target in nodes:
        candidates = []
        target_los = lo_by_node.get(target["id"], {})
        if not target_los:
            continue
        for source in nodes:
            if source["semester"] >= target["semester"]:
                continue
            if (source["id"], target["id"]) in formal_pairs:
                continue
            shared = sorted(set(lo_by_node.get(source["id"], {})) & set(target_los))
            if not shared:
                continue
            confidence = sum(
                min(lo_by_node[source["id"]][code], target_los[code])
                for code in shared
            ) / len(shared)
            semester_distance = target["semester"] - source["semester"]
            candidates.append((len(shared), confidence, -semester_distance, source, shared))
        candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        for _, confidence, _, source, shared in candidates[:2]:
            competency_edges.append({
                "id": f"competency-{source['id']}-{target['id']}",
                "source": source["id"],
                "target": target["id"],
                "relation": "competency_flow",
                "shared_los": shared,
                "confidence": round(confidence, 3),
                "semester_distance": target["semester"] - source["semester"],
            })
    edges.extend(competency_edges)

    semantic_edges = []
    if include_semantic:
        # Fill sparse evidence graphs with a separate semantic-progression layer.
        # This remains explicitly inferred and never participates in prerequisite
        # validation. It answers "which later course develops this material?".
        import numpy as np
        from app.kag.embedding_service import embedding_service
        texts = []
        for node in nodes:
            texts.append(" ".join([
                str(node.get("title") or ""),
                str(node.get("description") or ""),
                " ".join(str(item) for item in node.get("learning_outcomes") or []),
                " ".join(str(item) for item in node.get("topics") or []),
            ]))
        vectors = embedding_service.encode_batch(texts)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        normalized_vectors = vectors / np.maximum(norms, 1e-9)
        node_index = {node["id"]: index for index, node in enumerate(nodes)}
        occupied_pairs = formal_pairs | {
            (edge["source"], edge["target"]) for edge in competency_edges
        }
        for target in nodes:
            target_index = node_index[target["id"]]
            candidates = []
            for source in nodes:
                if source["semester"] >= target["semester"]:
                    continue
                pair = (source["id"], target["id"])
                if pair in occupied_pairs:
                    continue
                score = float(np.dot(
                    normalized_vectors[node_index[source["id"]]],
                    normalized_vectors[target_index],
                ))
                if score < 0.12:
                    continue
                distance = target["semester"] - source["semester"]
                candidates.append((score, -distance, source))
            candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            for score, _, source in candidates[:2]:
                semantic_edges.append({
                    "id": f"semantic-{source['id']}-{target['id']}",
                    "source": source["id"], "target": target["id"],
                    "relation": "semantic_progression",
                    "confidence": round(score, 3),
                    "semester_distance": target["semester"] - source["semester"],
                })
        edges.extend(semantic_edges)

    state, cycle_nodes = {}, set()
    def visit(node_id, path):
        if state.get(node_id) == 1:
            cycle_nodes.update(path[path.index(node_id):] if node_id in path else [node_id])
            return
        if state.get(node_id) == 2:
            return
        state[node_id] = 1
        for child in adjacency.get(node_id, []):
            visit(child, path + [node_id])
        state[node_id] = 2
    for node_id in node_ids:
        visit(node_id, [])

    by_semester = {}
    for node in nodes:
        by_semester.setdefault(str(node["semester"]), {"courses": 0, "credits": 0})
        by_semester[str(node["semester"])]["courses"] += 1
        by_semester[str(node["semester"])]["credits"] += int(node["credits"] or 0)

    return {
        "project_version_id": project_version_id, "plan_id": plan.id,
        "variant_type": plan.variant_type, "is_active": plan.is_active == 1,
        "nodes": nodes, "edges": edges, "cycle_nodes": sorted(cycle_nodes),
        "has_cycles": bool(cycle_nodes), "semester_summary": by_semester,
        "formal_edge_count": len(formal_pairs),
        "competency_edge_count": len(competency_edges),
        "semantic_edge_count": len(semantic_edges),
        "semantic_edges_enabled": include_semantic,
    }


@router.get("/version/{project_version_id}/semester-competencies")
async def get_semester_competencies(
    project_version_id: int,
    variant: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return cumulative, evidence-backed competencies after each semester."""
    from app.models.plan import Plan, PlanItem
    from app.models.project import LearningOutcome

    query = db.query(Plan).filter(Plan.project_version_id == project_version_id)
    if variant:
        query = query.filter(Plan.variant_type == variant.upper())
    plan = query.order_by(Plan.is_active.desc(), Plan.id.desc()).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Сначала сформируйте варианты учебного плана")

    items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).order_by(PlanItem.semester).all()
    # Resolve all course rows once.  The unlock calculation below used to
    # reference the graph endpoint's local maps, which do not exist in this
    # endpoint and caused every graph page to fail with HTTP 500.
    course_ids = {int(item.course_id) for item in items if item.course_id is not None}
    course_by_id = {
        course.id: course
        for course in db.query(Course).filter(Course.id.in_(course_ids or {-1})).all()
    }
    localization_by_course = course_localization_map(db, course_by_id.keys())
    program_los = {
        lo.id: lo for lo in db.query(LearningOutcome).filter(
            LearningOutcome.project_version_id == project_version_id
        ).all()
    }
    semesters = []
    cumulative_course_outcomes, cumulative_lo_codes = [], set()
    max_semester = max((item.semester for item in items), default=0)
    for semester in range(1, max_semester + 1):
        semester_items = [item for item in items if item.semester == semester]
        completed_courses, new_course_outcomes = [], []
        new_lo_evidence = {}
        for item in semester_items:
            if item.course_id is not None:
                course = db.query(Course).filter(Course.id == item.course_id).first()
                if not course:
                    continue
                completed_courses.append({"code": course.course_id, "title": course.title, "credits": item.credits})
                for outcome in course.learning_outcomes or []:
                    clean = str(outcome).strip()
                    if clean and clean not in cumulative_course_outcomes and clean not in new_course_outcomes:
                        new_course_outcomes.append(clean)
                matches = db.query(MatchScore).filter(
                    MatchScore.project_version_id == project_version_id,
                    MatchScore.course_id == course.id,
                    MatchScore.score >= 0.4,
                ).all()
                for match in matches:
                    lo = program_los.get(match.lo_id)
                    if lo:
                        evidence = new_lo_evidence.setdefault(lo.lo_code, {
                            "lo_code": lo.lo_code, "lo_text": lo.lo_text,
                            "evidence": [], "max_score": 0.0,
                        })
                        evidence["evidence"].append({"course_code": course.course_id, "course_title": course.title, "score": round(float(match.score), 3)})
                        evidence["max_score"] = max(evidence["max_score"], round(float(match.score), 3))
            else:
                bridge = db.query(BridgeModule).filter(BridgeModule.id == item.bridge_module_id).first()
                if not bridge:
                    continue
                completed_courses.append({"code": bridge.course_id, "title": bridge.title, "credits": item.credits})
                for outcome in bridge.learning_outcomes or []:
                    clean = str(outcome).strip()
                    if clean and clean not in cumulative_course_outcomes and clean not in new_course_outcomes:
                        new_course_outcomes.append(clean)
                for lo in program_los.values():
                    if lo.lo_code in (bridge.target_los or []):
                        evidence = new_lo_evidence.setdefault(lo.lo_code, {
                            "lo_code": lo.lo_code, "lo_text": lo.lo_text,
                            "evidence": [], "max_score": 0.75,
                        })
                        evidence["evidence"].append({"course_code": bridge.course_id, "course_title": bridge.title, "score": 0.75})

        cumulative_course_outcomes.extend(new_course_outcomes)
        cumulative_lo_codes.update(new_lo_evidence)
        semesters.append({
            "semester": semester,
            "credits": sum(int(item.credits or 0) for item in semester_items),
            "completed_courses": completed_courses,
            "new_course_outcomes": new_course_outcomes,
            "program_lo_evidence": sorted(new_lo_evidence.values(), key=lambda item: item["lo_code"]),
            "cumulative_course_outcomes": cumulative_course_outcomes.copy(),
            "cumulative_program_los": sorted(cumulative_lo_codes),
            "next_unlocked_courses": [],
        })

    course_semester = {item.course_id: item.semester for item in items if item.course_id is not None}
    for record in semesters:
        current = record["semester"]
        unlocked = []
        for item in items:
            if item.semester != current + 1 or item.course_id is None:
                continue
            prerequisite_ids = item.prerequisites_snapshot or []
            if all(course_semester.get(pid, current + 1) <= current for pid in prerequisite_ids):
                course = course_by_id.get(int(item.course_id))
                if course:
                    unlocked.append({
                        "code": course.course_id,
                        "title": course.title,
                        "title_translations": localization_by_course.get(
                            int(course.id), {}
                        ).get("title_translations", {}),
                    })
        record["next_unlocked_courses"] = unlocked

    return {"plan_id": plan.id, "variant_type": plan.variant_type, "semesters": semesters}


@router.post("/version/{project_version_id}/semester-insight")
async def generate_semester_insight(
    project_version_id: int,
    semester: int = Body(..., ge=1, le=20),
    variant: str = Body("A"),
    language: str = Body("ru"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Explain in plain language what a student can do after one semester."""
    import json
    from app.models.plan import Plan, PlanItem

    plan = db.query(Plan).filter(
        Plan.project_version_id == project_version_id,
        Plan.variant_type == variant.upper(),
    ).order_by(Plan.is_active.desc(), Plan.id.desc()).first()
    if not plan:
        raise HTTPException(status_code=404, detail="План не найден")
    items = db.query(PlanItem).filter(
        PlanItem.plan_id == plan.id, PlanItem.semester == semester
    ).all()
    if not items:
        raise HTTPException(status_code=404, detail="В выбранном семестре нет дисциплин")
    course_ids = [item.course_id for item in items if item.course_id]
    bridge_ids = [item.bridge_module_id for item in items if item.bridge_module_id]
    courses = {row.id: row for row in db.query(Course).filter(Course.id.in_(course_ids or [-1])).all()}
    bridges = {row.id: row for row in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids or [-1])).all()}
    lo_by_id = {row.id: row for row in plan.project_version.learning_outcomes}
    matches = db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version_id,
        MatchScore.course_id.in_(course_ids or [-1]),
        MatchScore.score >= 0.4,
    ).order_by(MatchScore.score.desc()).all()
    lo_rows = []
    seen_los = set()
    for match in matches:
        lo = lo_by_id.get(match.lo_id)
        if lo and lo.lo_code not in seen_los:
            seen_los.add(lo.lo_code)
            lo_rows.append({"code": lo.lo_code, "text": lo.lo_text, "score": round(float(match.score), 3)})
    course_titles = [courses[item.course_id].title for item in items if item.course_id in courses]
    course_titles.extend(bridges[item.bridge_module_id].title for item in items if item.bridge_module_id in bridges)
    fallback_skills = [row["text"] for row in lo_rows[:4]]
    if not fallback_skills:
        fallback_skills = [
            str(value).strip()
            for course in courses.values()
            for value in (course.learning_outcomes or [])
            if str(value).strip()
        ][:4]
    prompt = f"""Return JSON with keys summary (one short paragraph) and skills (3-5 short items).
Language: {language}. Degree programme: {plan.project_version.project.title}.
Semester: {semester}. Courses: {json.dumps(course_titles, ensure_ascii=False)}.
Evidence-backed programme outcomes: {json.dumps(lo_rows[:8], ensure_ascii=False)}.
Do not invent skills not supported by the courses or outcomes."""
    raw = call_llm(prompt, {
        "domain1": plan.project_version.project.domain1,
        "domain2": plan.project_version.project.domain2,
        "gap_los": [],
    })
    source = "local_evidence"
    summary = (
        f"После {semester}-го семестра студент объединяет знания дисциплин «"
        + "», «".join(course_titles[:4])
        + "» и применяет их для подтверждённых результатов программы."
    )
    skills = fallback_skills
    try:
        parsed = json.loads(raw)
        if isinstance(parsed.get("summary"), str) and isinstance(parsed.get("skills"), list):
            summary = parsed["summary"].strip()
            skills = [str(value).strip() for value in parsed["skills"] if str(value).strip()][:5]
            source = "ai"
    except (TypeError, json.JSONDecodeError):
        pass
    return {
        "plan_id": plan.id,
        "variant": plan.variant_type,
        "semester": semester,
        "summary": summary,
        "skills": skills,
        "evidence_los": lo_rows[:8],
        "source": source,
    }
