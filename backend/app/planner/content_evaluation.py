"""Local, advisory content review. No network, model loading or academic approval."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from functools import lru_cache
import hashlib
import json
import re
import numpy as np

from app.planner.discipline_identity import discipline_identity

EVALUATOR_VERSION = 'local-content-1.4'
FIELDS = ('description', 'topics', 'learning_outcomes', 'assessment_methods')


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), default=str).encode()).hexdigest()


def normalise(value):
    return ' '.join(str(value or '').casefold().split())


def source_text(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value or '')


def course_record(course):
    return {key: getattr(course, key, None) for key in
            ('id', 'course_id', 'title', 'domain', 'credits', 'language', *FIELDS)}


def _terms(text):
    # Bounded lexical evidence supplements existing semantic matches. It is
    # not a multilingual semantic model and must never create hard constraints.
    stops = {word[:7] for word in ('дисциплина', 'изучение', 'обучение', 'студенты', 'результат', 'развитие',
             'основные', 'формирование', 'программа', 'компетенции', 'the', 'and', 'для',
             'технология', 'методы', 'материалы', 'производство', 'качество', 'обработка',
             'различные', 'профессиональный', 'применять', 'знания', 'процессы', 'продукция',
             'управление', 'решение', 'основы', 'проектировать', 'контроль', 'изделия')}
    return {word[:7] for word in re.findall(r'[^\W\d_]+', normalise(text), re.UNICODE)
            if len(word) >= 4 and word[:7] not in stops}


def _level(title):
    return tuple(re.findall(r'\b(?:[1-9]|i{1,3}|iv|a[12]|b[12]|c[12]|advanced|базовый|продвинутый)\b',
                            normalise(title)))


@lru_cache(maxsize=4096)
def _cached_course(profile_json, course_json, scores_json):
    profile, course, scores = map(json.loads, (profile_json, course_json, scores_json))
    title = str(course.get('title') or '')
    content = {field: source_text(course.get(field)) for field in FIELDS}
    substantive = {field: text for field, text in content.items()
                   if field != 'assessment_methods' and len(normalise(text)) >= 25
                   and len(re.findall(r'[^\W\d_]+', text, re.UNICODE)) >= 3
                   and normalise(text) != normalise(title)}
    profile_text = ' '.join(source_text(profile.get(key)) for key in
                            ('title', 'goal', 'learning_outcomes'))
    regulatory = str(course.get('course_id') or '').upper().startswith('GOSO-KZ-')
    support = any(marker in normalise(title) for marker in
                  ('иностранный язык', 'психология управления', 'общий менеджмент'))
    if any(marker in normalise(profile_text) for marker in
           ('лингвист', 'филолог', 'перевод', 'linguistic', 'translation')):
        support = False
    role = 'regulatory' if regulatory else 'supporting' if support else 'professional'
    evidence = []
    # Generic mission statements (science, development, production) are not
    # professional anchors. Use the named programme profile; unknown synonyms
    # remain uncertain instead of inventing positive evidence from its goal.
    focus_terms = _terms(source_text(profile.get('title')))
    if any(term.startswith(('дерево', 'древес', 'мебел', 'wood', 'furnit', 'timber')) for term in focus_terms):
        focus_terms |= _terms('древесина деревообработка мебель лесопиление пиломатериалы woodworking furniture timber')
    for field, text in substantive.items():
        overlap = sorted(_terms(text) & focus_terms)
        evidence.append({'source_reference': str(course.get('course_id') or course['id']),
                         'source_field': field, 'excerpt': text[:500],
                         'matched_terms': overlap,
                         'content_hash': canonical_hash(course)})
    max_raw = max((float(v) for v in scores.values()), default=0.0)
    lexical = any(item['matched_terms'] for item in evidence)
    status = 'regulatory' if regulatory else 'insufficient_data' if not substantive else (
        'supported' if lexical and not support else
        'supporting' if support else 'needs_review')
    # A concrete regression family with explicit content evidence. Broader
    # mismatches remain reviewable; no hidden taxonomy or exclusion is inferred.
    wood_profile = any(x in normalise(profile_text) for x in ('древес', 'деревообработ', 'wood'))
    wood_content = any(x in normalise(' '.join(substantive.values()))
                       for x in ('древес', 'деревообработ', 'wood'))
    metal_fields = [(field, text) for field, text in substantive.items()
                    if any(x in normalise(text) for x in ('металл', 'стали', 'metallurg'))]
    if wood_profile and metal_fields and not wood_content and not regulatory:
        status = 'profile_mismatch'
        field, text = metal_fields[0]
        evidence = [item for item in evidence if item['source_field'] == field]
    adjustment = .15 if status == 'supported' and role == 'professional' else (
        -.25 if status == 'profile_mismatch' else 0.0)
    return {'course_id': course['id'], 'title': title, 'role': role, 'status': status,
            'evidence': evidence, 'raw_lo_scores': scores,
            'priority_adjustment': adjustment, 'advisory': True}


def assess_course(profile, course, scores=None):
    args = [json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
            for value in (profile, course_record(course), scores or {})]
    # Return a copy: callers cannot poison cached evidence.
    return json.loads(json.dumps(_cached_course(*args), ensure_ascii=False))


def prioritise_candidates(candidates, courses, profile, *, mode):
    if mode != 'prioritise':
        return candidates
    return tuple(replace(c, utility=c.utility + assess_course(
        profile, courses[c.course_id], c.lo_scores)['priority_adjustment'])
        if c.course_id in courses else c for c in candidates)


def evaluate_content(*, profile, courses, schedule, lo_scores=None, core_blocks=None,
                     confirmed_matches=None, prerequisites=None, content_vectors=None):
    courses = sorted(courses, key=lambda c: int(c.id))
    scores, blocks = lo_scores or {}, core_blocks or []
    confirmed, parents = confirmed_matches or {}, prerequisites or {}
    schedule = {int(k): v for k, v in schedule.items()}
    positions = {int(item['course_id']): semester for semester, items in schedule.items()
                 for item in items if item.get('course_id') is not None}
    credits = {int(item['course_id']): int(item.get('credits') or 0)
               for items in schedule.values() for item in items if item.get('course_id') is not None}
    rows = [assess_course(profile, c, scores.get(int(c.id), {})) for c in courses]
    by_id = {row['course_id']: row for row in rows}
    groups = defaultdict(list)
    duplicates = []
    for c in courses:
        if str(c.course_id or '').upper().startswith('GOSO-KZ-'):
            continue
        record = course_record(c)
        text = ' '.join(source_text(record.get(f)) for f in FIELDS[:3])
        if len(re.findall(r'[^\W\d_]+', text, re.UNICODE)) >= 5 and len(normalise(text)) >= 40:
            groups[(normalise(text), normalise(c.language), _level(c.title))].append(int(c.id))
    for ids in groups.values():
        if len(ids) > 1:
            duplicates.append({'course_ids': ids, 'status': 'needs_review',
                               'reason': 'identical_content',
                               'evidence': [by_id[cid]['evidence'] for cid in ids]})
    vectors = {}
    embedding_findings = []
    for cid, record in (content_vectors or {}).items():
        try:
            vector = np.asarray(record['vector'], dtype=float)
            if vector.ndim != 1 or not len(vector) or not np.isfinite(vector).all() or not record.get('model'):
                raise ValueError('invalid vector')
            vectors[cid] = {'model': record['model'], 'vector': vector.tolist()}
        except (KeyError, TypeError, ValueError):
            embedding_findings.append({'course_id': cid, 'reason': 'invalid_embedding'})
    exact_pairs = {tuple(sorted((a, b))) for group in duplicates
                   for a in group['course_ids'] for b in group['course_ids'] if a != b}
    vector_courses = [c for c in courses if c.id in vectors and by_id[c.id]['role'] != 'regulatory']
    for i, a in enumerate(vector_courses):
        for b in vector_courses[i + 1:]:
            if (tuple(sorted((a.id, b.id))) in exact_pairs or _level(a.title) != _level(b.title)
                    or normalise(a.language) != normalise(b.language)
                    or not (_terms(a.title) & _terms(b.title))
                    or vectors[a.id]['model'] != vectors[b.id]['model']):
                continue
            va, vb = (np.asarray(vectors[cid]['vector'], dtype=float) for cid in (a.id, b.id))
            if va.shape != vb.shape or va.ndim != 1 or not np.isfinite(va).all() or not np.isfinite(vb).all():
                continue
            denominator = float(np.linalg.norm(va) * np.linalg.norm(vb))
            similarity = float(va @ vb / denominator) if denominator else 0.0
            if similarity >= .92:
                duplicates.append({'course_ids': [a.id, b.id], 'status': 'needs_review',
                                   'reason': 'similar_content_embedding', 'similarity': round(similarity, 4),
                                   'embedding_model': vectors[a.id]['model'],
                                   'evidence': [by_id[cid]['evidence'] for cid in (a.id, b.id)]})
    coverage = []
    for block in blocks:
        ids = sorted(set(confirmed.get(block['id'], ())) & set(positions))
        total = sum(credits.get(cid, 0) for cid in ids)
        covered = len(ids) >= int(block.get('min_courses') or 1) and total >= int(block.get('min_credits') or 0)
        coverage.append({'block_id': block['id'], 'title': block.get('title'), 'course_ids': ids,
                         'credits': total, 'status': 'covered' if covered else 'unconfirmed',
                         'requirement': block.get('requirement', 'preferred')})
    sequence = []
    for cid, semester in sorted(positions.items()):
        for parent in parents.get(cid, []):
            if parent not in positions or positions[parent] >= semester:
                sequence.append({'course_id': cid, 'prerequisite_id': parent,
                                 'semester': semester, 'prerequisite_semester': positions.get(parent),
                                 'reason': 'missing_prerequisite' if parent not in positions else 'prerequisite_order'})
    # Publication removes display/solver metadata and may reorder rows.
    # Fingerprint the same curricular facts before and after persistence.
    schedule_snapshot = {
        semester: sorted([
            {'course_id': item.get('course_id'),
             'bridge_module_id': item.get('bridge_module_id'),
             'credits': int(item.get('credits') or 0),
             'prerequisites': sorted(item.get('prerequisites') or [])}
            for item in items
        ], key=canonical_hash)
        for semester, items in schedule.items()
    }
    snapshot = {'profile': profile, 'courses': [course_record(c) for c in courses],
                'schedule': schedule_snapshot, 'scores': scores, 'blocks': blocks,
                'confirmed': {key: sorted(value) for key, value in confirmed.items()},
                'prerequisites': parents, 'version': EVALUATOR_VERSION}
    snapshot['content_vectors'] = vectors
    snapshot['embedding_findings'] = embedding_findings
    return {'evaluator_version': EVALUATOR_VERSION, 'snapshot_hash': canonical_hash(snapshot),
            'advisory': True, 'courses': rows, 'core_coverage': coverage,
            'core_definition_missing': not bool(blocks),
            'duplicate_groups': duplicates, 'sequence_findings': sequence,
            'embedding_findings': embedding_findings,
            'indicators': {'reviewed_courses': len(rows),
                           'profile_mismatch_count': sum(r['status'] == 'profile_mismatch' for r in rows),
                           'insufficient_data_count': sum(r['status'] == 'insufficient_data' for r in rows),
                           'needs_review_count': sum(r['status'] == 'needs_review' for r in rows),
                           'supported_professional_count': sum(r['status'] == 'supported' and r['role'] == 'professional' for r in rows),
                           'core_gaps': sum(r['status'] != 'covered' for r in coverage),
                           'duplicate_groups': len(duplicates), 'sequence_findings': len(sequence)}}
