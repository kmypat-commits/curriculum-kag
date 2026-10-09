"""Database adapter for local content evaluation of actual persisted schedules."""
from sqlalchemy.orm import selectinload

from app.models.course import Course, CourseChunk
from app.models.embedding import MatchScore, Embedding
import json
from app.planner.content_evaluation import evaluate_content, normalise
from app.planner.core_evidence import verified_matches
from app.planner.core_requirements import effective_requirements
from app.planner.match_aggregation import semantic_evidence_score


def profile_for_version(version):
    return {'title': version.project.title, 'goal': version.project.goal,
            'learning_outcomes': {lo.lo_code: lo.lo_text for lo in version.learning_outcomes
                                  if not str(lo.lo_code).startswith('LO-GOSO-')}}


def evaluate_schedule(version, db, schedule):
    ids = {int(item['course_id']) for items in schedule.values() for item in items
           if item.get('course_id') is not None}
    courses = db.query(Course).options(selectinload(Course.prerequisites)).filter(
        Course.id.in_(sorted(ids))).all() if ids else []
    codes = {lo.id: lo.lo_code for lo in version.learning_outcomes}
    scores = {}
    if ids:
        for match in db.query(MatchScore).filter(MatchScore.project_version_id == version.id,
                                                MatchScore.course_id.in_(sorted(ids))).all():
            if match.lo_id in codes and not str(codes[match.lo_id]).startswith('LO-GOSO-'):
                by_code = scores.setdefault(match.course_id, {})
                code = codes[match.lo_id]
                by_code[code] = max(by_code.get(code, 0.0), semantic_evidence_score(match))
    constraints = version.project.constraints_json or {}
    requirements = effective_requirements(constraints.get('curriculum_requirements'))
    blocks = requirements['core_blocks'] if requirements else []
    confirmed = verified_matches(blocks, constraints.get('curriculum_confirmations') or [],
                                 {c.id: c for c in courses}, project_version_id=version.id)
    parents = {c.id: [p.id for p in c.prerequisites] for c in courses}
    by_id = {c.id: c for c in courses}
    vectors = {}
    if ids:
        embedded = db.query(CourseChunk, Embedding).join(Embedding, Embedding.chunk_id == CourseChunk.id).filter(
            CourseChunk.course_id.in_(sorted(ids)), CourseChunk.chunk_type == 'description',
        ).order_by(CourseChunk.id).all()
        for chunk, embedding in embedded:
            if not chunk.chunk_text or normalise(chunk.chunk_text) not in normalise(by_id[chunk.course_id].description):
                continue  # Old embeddings must not evaluate edited descriptions.
            vector = embedding.vector
            if isinstance(vector, str):
                try: vector = json.loads(vector)
                except ValueError: pass  # Evaluator records malformed optional vectors.
            if vector is not None:
                vectors.setdefault(chunk.course_id, {'model': embedding.model_version,
                                                     'vector': vector})
    result = evaluate_content(profile=profile_for_version(version), courses=courses,
                              schedule=schedule, lo_scores=scores, core_blocks=blocks,
                              confirmed_matches=confirmed, prerequisites=parents, content_vectors=vectors)
    for record in constraints.get('curriculum_confirmations') or []:
        if record.get('course_id') in confirmed.get(record.get('block_id'), set()):
            for row in result['courses']:
                if row['course_id'] == record['course_id']:
                    row['evidence'].append({'source_reference': record['source_reference'],
                                            'source_field': record['source_field'],
                                            'excerpt': record['source_excerpt'],
                                            'content_hash': record['content_hash'],
                                            'confirmed_by_methodist': True})
    result['missing_course_ids'] = sorted(ids - {c.id for c in courses})
    return result


def persisted_schedule(plan, items):
    schedule = {}
    for item in items:
        schedule.setdefault(item.semester, []).append({
            'course_id': item.course_id, 'bridge_module_id': item.bridge_module_id,
            'credits': item.credits, 'prerequisites': item.prerequisites_snapshot or []})
    return schedule
