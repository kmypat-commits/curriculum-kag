from typing import List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import String, cast, func, or_
from app.models.course import Course
from app.models.project import LearningOutcome, ProjectVersion
from app.models.embedding import MatchFeedback, MatchScore
from app.models.epvo import EpvoDisciplineLoLink, EpvoDisciplineNormalized, RawEpvoLearningOutcome
from app.kag.retrieval import retrieve_top_k_courses_hybrid
from app.kag.embedding_service import embedding_service
from app.kag.indexing import index_all_courses
from app.models.embedding import Embedding
from app.config import settings
from app.kag.epvo_two_stage import epvo_two_stage_ranker
from app.services.content_localization import course_localization_map, course_translations
import numpy as np
import math


LARGE_CATALOG_THRESHOLD = 3000


def _expert_level_score(level: str | None, strength: float | None) -> float:
    if strength is not None:
        return max(0.0, min(1.0, float(strength)))
    value = (level or "").casefold()
    if any(token in value for token in ("выс", "high", "strong")):
        return 1.0
    if any(token in value for token in ("сред", "medium", "mid")):
        return 0.65
    if any(token in value for token in ("низ", "low", "weak")):
        return 0.35
    return 0.0


def _epvo_id_from_course(course: Course) -> int | None:
    code = course.course_id or ""
    if not code.startswith("EPVO-"):
        return None
    try:
        return int(code.split("-", 1)[1])
    except ValueError:
        return None


def _raw_lo_text(payload: dict | None) -> str:
    payload = payload or {}
    for key in (
        "learningOutcomeNameRu", "learningOutcomeNameKz", "learningOutcomeNameEn",
        "nameRu", "nameKz", "nameEn", "text", "title",
    ):
        if payload.get(key):
            return str(payload[key])
    return " ".join(str(value) for value in payload.values() if isinstance(value, str))


def _epvo_expert_signal(course: Course, lo: LearningOutcome, db: Session) -> Dict:
    """Map EPVO expert discipline-LO labels to the current project LO.

    EPVO expert labels belong to source programme LOs.  For a new project LO we
    use a conservative text-overlap bridge: expert strength counts only when the
    source LO text is semantically close enough by keywords.
    """
    discipline_id = _epvo_id_from_course(course)
    if discipline_id is None:
        return {"score": 0.0}

    cache = db.info.setdefault("epvo_expert_signal_cache", {})
    cache_key = (discipline_id, lo.id)
    if cache_key in cache:
        return cache[cache_key]

    project_tokens = set(_extract_keywords(lo.lo_text, top_n=16))
    best = {"score": 0.0}
    links = db.query(EpvoDisciplineLoLink).filter(
        EpvoDisciplineLoLink.discipline_id == discipline_id,
    ).limit(200).all()
    for link in links:
        raw_key = (link.program_source_id, link.lo_source_key)
        raw_cache = db.info.setdefault("epvo_raw_lo_text_cache", {})
        if raw_key not in raw_cache:
            raw = db.query(RawEpvoLearningOutcome).filter(
                RawEpvoLearningOutcome.program_source_id == link.program_source_id,
                RawEpvoLearningOutcome.source_key == link.lo_source_key,
            ).first()
            raw_cache[raw_key] = _raw_lo_text(raw.payload_json if raw else {})
        source_text = raw_cache[raw_key]
        source_tokens = set(_extract_keywords(source_text, top_n=16))
        overlap = len(project_tokens & source_tokens) / max(1, min(len(project_tokens), len(source_tokens)))
        if overlap < 0.12:
            continue
        level_score = _expert_level_score(link.expert_level, link.strength)
        score = level_score * min(1.0, overlap * 1.5)
        if score > best["score"]:
            best = {
                "score": round(score, 4),
                "level": link.expert_level,
                "strength": link.strength,
                "source": "epvo_expert",
                "source_lo_text": source_text[:240],
                "source_program_id": link.program_source_id,
                "lo_overlap": round(overlap, 3),
            }
    cache[cache_key] = best
    return best


def calculate_semantic_similarity(course_text: str, lo_text: str) -> float:
    """Cosine similarity between two text strings via the embedding model."""
    course_emb = embedding_service.encode(course_text)
    lo_emb = embedding_service.encode(lo_text)
    denom = np.linalg.norm(course_emb) * np.linalg.norm(lo_emb)
    if denom < 1e-9:
        return 0.0
    return float(np.dot(course_emb, lo_emb) / denom)


def _extract_keywords(text: str, top_n: int = 10) -> List[str]:
    """
    Lightweight keyword extraction: stopword-filtered tokens sorted by length.
    Used as a domain-agnostic alternative to hardcoded word lists.
    """
    stopwords = {
        "и", "в", "на", "с", "по", "для", "к", "а", "или", "но", "the",
        "and", "of", "to", "in", "for", "a", "is", "are", "be", "with",
        "that", "это", "как", "не", "из", "от", "при", "об", "о",
    }
    tokens = [
        t.lower().strip(".,;:!?()[]\"'")
        for t in text.split()
        if len(t) > 3 and t.lower() not in stopwords
    ]
    # Deduplicate while preserving order
    seen: set = set()
    unique = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return sorted(unique, key=len, reverse=True)[:top_n]


def _course_match_text(course: Course, localization: Dict | None = None) -> str:
    parts: List[str] = [course.title]
    if course.description:
        parts.append(course.description)
    translated_description = (
        (localization or {}).get("description_translations")
        if localization is not None
        else course_translations(course.id, "description")
    )
    if translated_description:
        parts.extend(value for value in translated_description.values() if value)
    if course.topics:
        parts.append(" ".join(course.topics) if isinstance(course.topics, list) else str(course.topics))
    if course.learning_outcomes:
        parts.append(" ".join(course.learning_outcomes) if isinstance(course.learning_outcomes, list) else str(course.learning_outcomes))
    return " ".join(parts)


def calculate_match_score(
    course: Course,
    lo: LearningOutcome,
    db: Session,
    localization: Dict | None = None,
) -> Dict:
    """
    Compute M(course, LO) — the KAG match score with evidence trail.

    Components
    ----------
    1. Semantic similarity (embedding cosine)
    2. Dynamic keyword overlap (extracted from LO text)
    3. Domain alignment
    4. Text word-overlap fallback

    Returns ``{"score": float, "evidence": dict}``.
    """
    # Build course text
    course_text = _course_match_text(course, localization)

    # 1. Semantic similarity
    semantic_score = calculate_semantic_similarity(course_text, lo.lo_text)

    # 2. Dynamic keyword boost
    lo_keywords = _extract_keywords(lo.lo_text, top_n=16)
    course_title_lower = course.title.lower()
    course_text_lower = course_text.lower()
    lo_lower = lo.lo_text.lower()

    keyword_hits = sum(
        1 for kw in lo_keywords
        if kw in course_title_lower or kw in course_text_lower
    )
    keyword_boost = min(0.3, keyword_hits * 0.06)
    generic_title_terms = {
        "основы", "системы", "методы", "технологии", "управление", "анализ",
        "введение", "современные", "system", "systems", "methods", "technology",
        "technologies", "management", "analysis", "introduction",
    }
    title_terms = set(_extract_keywords(course.title, top_n=10)) - generic_title_terms
    title_hits = sum(1 for term in title_terms if term in lo_lower) if title_terms else 0
    title_alignment = title_hits / max(1, len(title_terms))
    title_alignment_boost = min(0.15, title_alignment * 0.15) if title_alignment >= 0.5 else 0.0

    # 3. Domain alignment
    domain_boost = 0.0
    if course.domain:
        # Extract domain tokens and check overlap with LO text
        domain_tokens = _extract_keywords(course.domain.replace("_", " "), top_n=5)
        if any(tok in lo_lower for tok in domain_tokens):
            domain_boost = 0.15

    # 4. Simple word-overlap fallback
    lo_words = set(lo_lower.split())
    course_words = set(course_text_lower.split())
    matched = lo_words & course_words
    overlap_score = min(0.2, len(matched) / max(len(lo_words), 1) * 0.4)

    ai_mode = bool(settings.EPVO_AI_ENABLED and embedding_service.model is not None)
    if ai_mode:
        # Calibrated display confidence around the validation-selected decision
        # threshold. Exact professional terminology is complementary evidence:
        # SBERT can under-score short titles such as "Computer Vision" even
        # when the LO repeats the same term. Keep this lexical lift bounded so
        # it cannot turn an unrelated in-domain course into a strong match.
        confidence = 1.0 / (1.0 + math.exp(
            -(semantic_score - settings.EPVO_AI_THRESHOLD) / max(settings.EPVO_AI_TEMPERATURE, 1e-6)
        ))
        lexical_support = min(
            0.20,
            0.70 * keyword_boost + 0.50 * overlap_score + 0.20 * domain_boost + title_alignment_boost,
        )
        final_score = min(1.0, max(0.0, confidence + lexical_support))
    else:
        lexical_support = keyword_boost + domain_boost + overlap_score + title_alignment_boost
        final_score = min(1.0, max(0.0,
            semantic_score + keyword_boost + domain_boost + overlap_score + title_alignment_boost
        ))
    heuristic_score = final_score
    expert_signal = _epvo_expert_signal(course, lo, db)
    expert_score = float(expert_signal.get("score") or 0.0)
    if expert_score > 0:
        # Expert labels from EPVO are supervised evidence.  Keep the heuristic
        # signal, but let a strong expert label lift the course-LO confidence.
        final_score = max(final_score, min(1.0, 0.65 * heuristic_score + 0.35 * expert_score))

    evidence = {
        "semantic_score": round(semantic_score, 3),
        "heuristic_score": round(heuristic_score, 3),
        "epvo_expert_score": round(expert_score, 3),
        "epvo_expert": expert_signal if expert_score > 0 else None,
        "keyword_boost": round(keyword_boost, 3),
        "domain_boost": round(domain_boost, 3),
        "overlap_score": round(overlap_score, 3),
        "lexical_support": round(lexical_support, 3),
        "title_alignment_boost": round(title_alignment_boost, 3),
        "matched_keywords": lo_keywords[:5],
        "course_text_preview": course_text[:200] + "..." if len(course_text) > 200 else course_text,
        "reasoning": [],
        "source": "epvo_sbert_ai_prediction" if ai_mode else "kag_heuristic",
        "ai_prediction": ai_mode,
        "expert_confirmed": False if ai_mode else None,
        "requires_expert_confirmation": ai_mode,
        "decision_threshold": settings.EPVO_AI_THRESHOLD if ai_mode else None,
        "predicted_link": semantic_score >= settings.EPVO_AI_THRESHOLD if ai_mode else None,
    }
    if semantic_score > 0.65:
        evidence["reasoning"].append("High semantic similarity")
    if keyword_boost > 0:
        evidence["reasoning"].append(f"Keyword match boost ({keyword_hits} hits)")
    if domain_boost > 0:
        evidence["reasoning"].append("Domain alignment match")
    if expert_score > 0:
        evidence["reasoning"].append("EPVO expert label supports this course-LO link")

    return {"score": final_score, "evidence": evidence}


def _domain_matches(course: Course, domain_filter: List[str]) -> bool:
    if not domain_filter:
        return True
    domain = (course.domain or "").lower().strip()
    return bool(domain) and any(d in domain or domain in d for d in domain_filter if d)


def _lightweight_candidate_courses(
    lo: LearningOutcome,
    courses: List[Course],
    limit: int,
    localizations: Dict[int, Dict] | None = None,
) -> List[Dict]:
    """Cheap candidate retrieval for large EPVO catalogues.

    Full embedding indexing over thousands of imported EPVO courses can freeze a
    desktop machine.  This prefilter keeps generation responsive: rank by
    overlap between LO keywords and course title/description, then score only
    the strongest candidates with the normal KAG formula.
    """
    lo_keywords = set(_extract_keywords(lo.lo_text, top_n=16))

    def rank(course: Course):
        localization = (localizations or {}).get(course.id)
        translated_description = " ".join(
            (
                (localization or {}).get("description_translations")
                if localization is not None
                else course_translations(course.id, "description")
            or {}).values()
        )
        text = " ".join(filter(None, [course.title, course.description or "", translated_description, course.domain or ""])).lower()
        hits = sum(1 for keyword in lo_keywords if keyword in text)
        exact_title = any(keyword in (course.title or "").lower() for keyword in lo_keywords)
        return (
            hits,
            1 if exact_title else 0,
            -(course.recommended_semester or 99),
            -(course.credits or 0),
        )

    ranked = sorted(courses, key=rank, reverse=True)
    return [{"course_id": course.id, "retrieval_score": float(rank(course)[0])} for course in ranked[:limit]]


def compute_all_matches(project_version_id: int, db: Session, progress_callback: object | None = None) -> Dict:
    """
    Compute course-LO match scores for all LOs in a project version.

    Uses hybrid KAG retrieval (vector + graph expansion) when the
    knowledge graph has been built; falls back to pure vector search.
    Saves results to the MatchScore table and returns statistics.
    """
    project_version = db.query(ProjectVersion).filter(
        ProjectVersion.id == project_version_id
    ).first()
    if not project_version:
        raise ValueError(f"Project version {project_version_id} not found")

    learning_outcomes = project_version.learning_outcomes
    total_los = len(learning_outcomes)
    project = project_version.project
    domain_filter: List[str] = []
    if project.domain1:
        domain_filter.append(project.domain1.lower())
    if project.domain2:
        domain_filter.append(project.domain2.lower())

    constraints = project.constraints_json or {}
    scoped_id_sets: List[set[int]] = []
    scope_pairs = [
        (str(constraints.get("group_code") or ""), str(constraints.get("direction_code") or "")),
    ]
    if str(constraints.get("program_type") or "").lower() in {"interdisciplinary", "joint"}:
        scope_pairs.append((
            str(constraints.get("secondary_group_code") or ""),
            str(constraints.get("secondary_direction_code") or ""),
        ))
    for group_code, direction_code in scope_pairs:
        conditions = []
        if group_code:
            conditions.append(cast(EpvoDisciplineNormalized.group_codes, String).like(f'%"{group_code}"%'))
        if direction_code:
            conditions.append(cast(EpvoDisciplineNormalized.direction_codes, String).like(f'%"{direction_code}"%'))
        if not conditions:
            continue
        scoped_ids = {
            int(row[0])
            for row in db.query(EpvoDisciplineNormalized.approved_course_id).filter(
                EpvoDisciplineNormalized.approved_course_id.isnot(None),
                or_(*conditions),
            ).all()
            if row[0] is not None
        }
        scoped_id_sets.append(scoped_ids)
    scoped_course_ids = {
        course_id
        for scoped_ids in scoped_id_sets
        for course_id in scoped_ids
    }
    repository_course_count = int(db.query(func.count(Course.id)).scalar() or 0)
    course_query = db.query(Course)
    if scoped_course_ids:
        relevant_conditions = [
            Course.id.in_(scoped_course_ids),
            Course.course_id.like("GOSO-KZ-%"),
            Course.course_id.like(f"AI-CONFIRMED-{project_version_id}-%"),
        ]
        # A global Course row can have the domain label of the first programme
        # that imported it. Domain text must therefore never pull an EPVO
        # discipline from another degree level (6B/7M/8D) or group. Exact EPVO
        # scope above is authoritative; domain fallback is only for local,
        # manually curated non-EPVO courses.
        relevant_conditions.extend(
            (~Course.course_id.like("EPVO-%"))
            & func.lower(Course.domain).like(f"%{domain}%")
            for domain in domain_filter if domain
        )
        course_query = course_query.filter(or_(*relevant_conditions))
    all_courses = course_query.all()
    course_by_id = {course.id: course for course in all_courses}
    scoped_course_sets = [
        [course_by_id[course_id] for course_id in scoped_ids if course_id in course_by_id]
        for scoped_ids in scoped_id_sets
    ]
    # EPVO rows are deduplicated into canonical Course records. Their global
    # domain label can originate from another programme, so an exact selected
    # EPVO group/direction must override that stale label.
    project_courses = [
        course for course in all_courses
        if course.id in scoped_course_ids or _domain_matches(course, domain_filter)
    ]
    localizations = course_localization_map(
        db,
        [course.id for course in project_courses],
        include_descriptions=True,
    )
    # A narrow project scope can contain fewer than 3k courses even when the
    # repository itself is huge. Reindexing the entire repository in that case
    # makes every new programme appear frozen before LO1.
    large_catalog_mode = repository_course_count >= LARGE_CATALOG_THRESHOLD
    if not large_catalog_mode:
        active_model = embedding_service.get_model_version()
        active_count = db.query(Embedding).filter(Embedding.model_version == active_model).count()
        total_count = db.query(Embedding).count()
        if active_count == 0 or active_count != total_count:
            index_all_courses(db)

    # Delete stale match scores for this version
    db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version_id
    ).delete()
    db.commit()

    total_matches = 0
    lo_coverage: Dict[str, Dict] = {}
    feedback_by_pair = {}
    for feedback in db.query(MatchFeedback).filter(
        MatchFeedback.project_version_id == project_version_id
    ).order_by(MatchFeedback.created_at.desc()).all():
        feedback_by_pair.setdefault((feedback.course_id, feedback.lo_id), feedback)

    def apply_feedback_score(course_id: int, lo_id: int, score: float, evidence: Dict) -> float:
        feedback = feedback_by_pair.get((course_id, lo_id))
        if not feedback:
            return score
        adjusted = score
        if feedback.verdict == "confirmed":
            adjusted = max(score, feedback.corrected_score if feedback.corrected_score is not None else 0.75)
        elif feedback.verdict == "weak":
            adjusted = min(score, feedback.corrected_score if feedback.corrected_score is not None else 0.45)
        elif feedback.verdict == "incorrect":
            adjusted = feedback.corrected_score if feedback.corrected_score is not None else 0.05
        elif feedback.verdict == "corrected" and feedback.corrected_score is not None:
            adjusted = feedback.corrected_score
        evidence["expert_feedback"] = {
            "verdict": feedback.verdict,
            "corrected_score": feedback.corrected_score,
            "original_score": round(float(score or 0), 4),
            "adjusted_score": round(float(adjusted or 0), 4),
            "feedback_id": feedback.id,
        }
        return max(0.0, min(1.0, float(adjusted)))

    for index, lo in enumerate(learning_outcomes, start=1):
        if progress_callback:
            progress_callback({
                "stage": "scoring",
                "lo_index": index,
                "lo_total": total_los,
                "lo_code": lo.lo_code,
                "progress": 12 + int((index - 1) / max(total_los, 1) * 8),
            })
        if large_catalog_mode:
            top_courses = _lightweight_candidate_courses(
                lo,
                project_courses,
                limit=max(settings.TOP_K_RETRIEVAL, 80),
                localizations=localizations,
            )
            # Guarantee representation of every selected EPVO scope. Without
            # stratification, a large primary catalogue can occupy all lexical
            # top-K positions and the second interdisciplinary area disappears.
            by_course_id = {int(row["course_id"]): row for row in top_courses}
            per_scope_limit = max(30, settings.TOP_K_RETRIEVAL // max(1, len(scoped_course_sets)))
            for scoped_courses in scoped_course_sets:
                for row in _lightweight_candidate_courses(
                    lo, scoped_courses, limit=per_scope_limit, localizations=localizations
                ):
                    by_course_id.setdefault(int(row["course_id"]), row)
            top_courses = list(by_course_id.values())
        else:
            # Hybrid KAG retrieval (vector + graph)
            top_courses = retrieve_top_k_courses_hybrid(
                lo, db, k=settings.TOP_K_RETRIEVAL, domain_filter=domain_filter
            )

        lo_scores: List[float] = []
        pending_matches = []
        for course_data in top_courses:
            course = course_by_id.get(int(course_data["course_id"]))
            if not course:
                continue
            match_result = calculate_match_score(
                course, lo, db, localizations.get(course.id)
            )
            pending_matches.append((course, match_result))

        reranked = epvo_two_stage_ranker.rerank(lo.lo_text, [
            {
                "course_id": course.id,
                "text": _course_match_text(course, localizations.get(course.id)),
                "classifier_score": float(result["score"] or 0),
                "classifier_similarity": float((result["evidence"] or {}).get("semantic_score") or 0),
                "expert_score": float((result["evidence"] or {}).get("epvo_expert_score") or 0),
            }
            for course, result in pending_matches
        ])

        for course, match_result in pending_matches:
            ranking = reranked.get(course.id)
            if ranking:
                match_result["score"] = ranking["score"]
                match_result["evidence"]["two_stage_ranking"] = ranking
                match_result["evidence"]["source"] = "epvo_sbert_classifier_plus_ranker"
            adjusted_score = apply_feedback_score(
                course.id,
                lo.id,
                float(match_result["score"] or 0.0),
                match_result["evidence"],
            )

            match_score = MatchScore(
                project_version_id=project_version_id,
                course_id=course.id,
                lo_id=lo.id,
                score=adjusted_score,
                evidence_json=match_result["evidence"],
            )
            db.add(match_score)
            total_matches += 1
            lo_scores.append(adjusted_score)

        # Probabilistic coverage: 1 - Π(1 - w_c)  (dissertation formula)
        prob_sum = 1.0
        for s in lo_scores:
            prob_sum *= (1.0 - s)
        probabilistic_coverage = 1.0 - prob_sum if lo_scores else 0.0

        lo_coverage[lo.lo_code] = {
            "max_score": probabilistic_coverage,
            "avg_score": sum(lo_scores) / len(lo_scores) if lo_scores else 0.0,
            "num_courses": len(lo_scores),
        }
        if progress_callback:
            progress_callback({
                "stage": "scoring",
                "lo_index": index,
                "lo_total": total_los,
                "lo_code": lo.lo_code,
                "progress": 12 + int(index / max(total_los, 1) * 8),
                "matches": total_matches,
            })

    db.commit()

    return {
        "total_matches": total_matches,
        "total_los": len(learning_outcomes),
        "lo_coverage": lo_coverage,
        "prediction": {
            "source": "epvo_sbert_ai" if settings.EPVO_AI_ENABLED and embedding_service.model is not None else "kag_heuristic",
            "label": "AI prediction" if settings.EPVO_AI_ENABLED and embedding_service.model is not None else "Heuristic estimate",
            "model": embedding_service.get_model_version(),
            "expert_confirmed": False,
            "requires_expert_confirmation": bool(settings.EPVO_AI_ENABLED and embedding_service.model is not None),
            "decision_threshold": settings.EPVO_AI_THRESHOLD if settings.EPVO_AI_ENABLED else None,
            "large_catalog_mode": large_catalog_mode,
            "candidate_courses": len(project_courses),
            "two_stage_ranker": epvo_two_stage_ranker.status(),
        },
    }


