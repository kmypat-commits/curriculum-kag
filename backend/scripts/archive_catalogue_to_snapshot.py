"""Archive later EPVO additions while preserving a historical catalogue and usage.

Default is read-only. --apply requires a verified external database backup.
Archived rows retain their exact PostgreSQL types in a separate schema.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys


def retained_course_ids(courses, baseline_codes, protected, prerequisites):
    keep = set(protected)
    keep.update(cid for cid, code in courses if code in baseline_codes or not code.startswith('EPVO-'))
    while True:
        parents = {parent for child, parent in prerequisites if child in keep}
        if parents <= keep:
            return keep
        keep.update(parents)


def course_references(payload, by_code):
    result = set()
    reference_keys = {'course_id', 'course_ids', 'required_course_ids', 'excluded_course_ids',
                      'prerequisites', 'prerequisites_snapshot', 'prerequisite_ids',
                      'baseline_course_ids', 'fixed_course_ids', 'required_courses'}

    def visit(value, reference=False):
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, key in reference_keys)
        elif isinstance(value, list):
            for item in value:
                visit(item, reference)
        elif reference:
            if isinstance(value, int) and not isinstance(value, bool):
                result.add(value)
            elif isinstance(value, str):
                if value in by_code:
                    result.add(by_code[value])
                elif value.isdecimal():
                    result.add(int(value))
    visit(payload)
    return result


PROTECTED_TABLES = ('projects', 'project_versions', 'learning_outcomes', 'plans', 'plan_items',
                    'match_feedback', 'planner_build_drafts', 'university_baseline_imports',
                    'university_baseline_revisions', 'syllabus_drafts', 'bridge_modules')


def protected_snapshot(connection):
    from sqlalchemy import text
    return {name: hashlib.sha256(json.dumps([
        dict(row) for row in connection.execute(text(f'SELECT * FROM public.{name} ORDER BY id')).mappings()
    ], sort_keys=True, default=str, ensure_ascii=False).encode('utf-8')).hexdigest()
            for name in PROTECTED_TABLES}


def collect_plan(connection, baseline):
    from sqlalchemy import text
    with sqlite3.connect(baseline.resolve().as_uri() + '?mode=ro', uri=True) as source:
        codes = {row[0] for row in source.execute('SELECT course_id FROM courses')}
    courses = list(connection.execute(text('SELECT id,course_id FROM courses ORDER BY id')))
    by_code = {code: cid for cid, code in courses}
    protected = {row[0] for row in connection.execute(text(
        'SELECT course_id FROM plan_items WHERE course_id IS NOT NULL UNION SELECT course_id FROM match_feedback'
    ))}
    for query in (
        'SELECT constraints_json FROM projects',
        'SELECT schedule_json FROM planner_build_drafts',
        'SELECT resolved_rows_json FROM university_baseline_revisions',
        'SELECT mapping_json FROM university_baseline_imports',
        'SELECT rows_json FROM university_baseline_imports',
        'SELECT prerequisites_snapshot FROM plan_items',
        'SELECT prerequisites FROM bridge_modules',
        'SELECT content_json FROM syllabus_drafts',
    ):
        for row in connection.execute(text(query)):
            payload = {'prerequisites': row[0]} if 'SELECT prerequisites' in query else row[0]
            protected.update(course_references(payload, by_code))
    # Bridge evidence can reference chunks from an earlier catalogue lookup.
    # Keep the owning course so those citations remain resolvable.
    chunk_ids = set()
    for row in connection.execute(text('SELECT source_chunks_json FROM bridge_modules')):
        def chunks(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {'chunk_id', 'id'} and isinstance(item, int):
                        chunk_ids.add(item)
                    else:
                        chunks(item)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, int):
                        chunk_ids.add(item)
                    else:
                        chunks(item)
        chunks(row[0])
    if chunk_ids:
        for row in connection.execute(text('SELECT id,course_id FROM course_chunks')):
            if row[0] in chunk_ids:
                protected.add(row[1])
    # Mapping values are internal Course.id values, without a course_id key.
    for row in connection.execute(text('SELECT mapping_json FROM university_baseline_imports')):
        protected.update(v for v in (row[0] or {}).values() if isinstance(v, int))
    protected.update(row[0] for row in connection.execute(text(
        "SELECT entity_id FROM syllabus_drafts WHERE kind='course'")))
    prerequisites = list(connection.execute(text('SELECT course_id,prerequisite_id FROM course_prerequisites')))
    keep = retained_course_ids(courses, codes, protected, prerequisites)
    archive = sorted(cid for cid, _ in courses if cid not in keep)
    payload = {'before': len(courses), 'historical': len(codes), 'retained': len(courses) - len(archive),
               'archived': len(archive), 'archive_ids': archive,
               'protected_sha256': protected_snapshot(connection)}
    payload['sha256'] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return payload


def archive(connection, plan, schema):
    from sqlalchemy import text
    assert schema.isidentifier() and schema.startswith('catalogue_archive_')
    connection.execute(text(f'CREATE SCHEMA {schema}'))
    connection.execute(text('CREATE TEMP TABLE archive_course_ids(id integer PRIMARY KEY) ON COMMIT DROP'))
    connection.execute(text('INSERT INTO archive_course_ids(id) VALUES (:id)'),
                       [{'id': cid} for cid in plan['archive_ids']])
    ids = 'SELECT id FROM archive_course_ids'
    conditions = {
        'courses': f'id IN ({ids})',
        'course_chunks': f'course_id IN ({ids})',
        'course_localizations': f'course_id IN ({ids})',
        'course_prerequisites': f'course_id IN ({ids}) OR prerequisite_id IN ({ids})',
        'embeddings': f'chunk_id IN (SELECT id FROM {schema}.course_chunks)',
        'match_scores': f'course_id IN ({ids}) OR chunk_id IN (SELECT id FROM {schema}.course_chunks)',
        'graph_edges': f'source_id IN ({ids}) OR target_id IN ({ids})',
        'epvo_disciplines_normalized': f'approved_course_id IN ({ids})',
    }
    counts = {}
    for table, condition in conditions.items():
        connection.execute(text(f'CREATE TABLE {schema}.{table} AS SELECT * FROM public.{table} WHERE {condition}'))
        counts[table] = connection.execute(text(f'SELECT count(*) FROM {schema}.{table}')).scalar_one()
    assert counts['courses'] == plan['archived']
    # Chunk references may have NO ACTION constraints: remove the archived
    # score rows explicitly before the course -> chunks cascade.
    connection.execute(text(f'DELETE FROM public.match_scores WHERE {conditions["match_scores"]}'))
    connection.execute(text(f'DELETE FROM public.graph_edges WHERE {conditions["graph_edges"]}'))
    connection.execute(text(f'UPDATE public.epvo_disciplines_normalized SET approved_course_id=NULL, status=\'normalized\' WHERE {conditions["epvo_disciplines_normalized"]}'))
    connection.execute(text(f'DELETE FROM public.courses WHERE {conditions["courses"]}'))
    assert connection.execute(text('SELECT count(*) FROM public.courses')).scalar_one() == plan['retained']
    assert protected_snapshot(connection) == plan['protected_sha256']
    for table in ('course_chunks', 'course_localizations'):
        assert connection.execute(text(f'SELECT count(*) FROM public.{table} WHERE {conditions[table]}')).scalar_one() == 0
    return counts


def restore(connection, schema):
    """Restore an archived catalogue transactionally; conflicts abort the restore."""
    from sqlalchemy import text
    assert schema.isidentifier() and schema.startswith('catalogue_archive_')
    overlap = connection.execute(text(f'SELECT count(*) FROM public.courses c JOIN {schema}.courses a '
                                      'ON c.id=a.id OR c.course_id=a.course_id')).scalar_one()
    if overlap:
        raise RuntimeError('Archived course identity already exists; refusing to overwrite')
    reassigned = connection.execute(text(f'SELECT count(*) FROM public.epvo_disciplines_normalized n '
        f'JOIN {schema}.epvo_disciplines_normalized a ON a.id=n.id '
        'WHERE n.approved_course_id IS NOT NULL')).scalar_one()
    if reassigned:
        raise RuntimeError('An archived EPVO mapping was reassigned; refusing to overwrite')
    counts = {}
    for table in ('courses', 'course_chunks', 'course_localizations', 'embeddings',
                  'match_scores', 'course_prerequisites', 'graph_edges'):
        counts[table] = connection.execute(text(f'INSERT INTO public.{table} '
                                               f'SELECT * FROM {schema}.{table}')).rowcount
    connection.execute(text(f'UPDATE public.epvo_disciplines_normalized n SET '
        f'approved_course_id=a.approved_course_id, status=a.status FROM {schema}.epvo_disciplines_normalized a '
        'WHERE n.id=a.id'))
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-sqlite', type=Path)
    parser.add_argument('--archive-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--restore', action='store_true')
    parser.add_argument('--expected-sha256')
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.database import engine
    from sqlalchemy import text
    url = engine.url
    if url.host != 'localhost' or url.port != 5433 or url.database != 'curriculum_kag_shadow':
        raise SystemExit('Unexpected database target')
    folder = args.archive_dir.resolve()
    if args.restore:
        if args.apply:
            parser.error('--restore and --apply are mutually exclusive')
        result = json.loads((folder / 'catalogue-applied.json').read_text(encoding='utf-8'))
        with engine.begin() as connection:
            counts = restore(connection, result['schema'])
        print(json.dumps({'restored': counts}))
        return
    if args.baseline_sqlite is None:
        parser.error('--baseline-sqlite is required unless restoring')
    if not args.apply:
        with engine.connect() as connection:
            connection.execute(text('SET TRANSACTION READ ONLY'))
            payload = collect_plan(connection, args.baseline_sqlite)
        plan_path = folder / f'catalogue-plan-{payload["sha256"][:12]}.json'
        if plan_path.exists():
            assert json.loads(plan_path.read_text(encoding='utf-8')) == payload
        else:
            with plan_path.open('x', encoding='utf-8') as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
        print(json.dumps({k: v for k, v in payload.items() if k != 'archive_ids'}))
        return
    metadata = json.loads((folder / 'database-before.json').read_text(encoding='utf-8'))
    backup = folder / 'database-before.dump'
    with backup.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != metadata['sha256']:
            raise SystemExit('Backup SHA256 mismatch')
    schema = 'catalogue_archive_20261022'
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout='5s'"))
        connection.execute(text('LOCK TABLE public.courses, public.course_chunks, public.embeddings, '
            'public.course_localizations, public.course_prerequisites, public.match_scores, public.graph_edges, '
            'public.epvo_disciplines_normalized, public.planner_build_jobs, public.planner_build_attempts, '
            'public.plan_build_status, ' + ', '.join('public.' + table for table in PROTECTED_TABLES)
            + ' IN SHARE ROW EXCLUSIVE MODE'))
        for table in ('planner_build_jobs', 'plan_build_status'):
            if connection.execute(text(f"SELECT count(*) FROM public.{table} WHERE state IN ('running','queued','cancellation_requested')")).scalar_one():
                raise RuntimeError('Active planner jobs: archive blocked')
        plan = collect_plan(connection, args.baseline_sqlite)
        if not args.expected_sha256 or plan['sha256'] != args.expected_sha256:
            raise RuntimeError('Archive plan changed: review the new plan first')
        counts = archive(connection, plan, schema)
    # Independent committed readback after the archive transaction.
    with engine.connect() as connection:
        assert connection.execute(text('SELECT count(*) FROM public.courses')).scalar_one() == plan['retained']
        assert protected_snapshot(connection) == plan['protected_sha256']
        for table, count in counts.items():
            assert connection.execute(text(f'SELECT count(*) FROM {schema}.{table}')).scalar_one() == count
    result = {'schema': schema, 'before': plan['before'], 'retained': plan['retained'],
              'archived': plan['archived'], 'counts': counts, 'committed_readback': True}
    with (folder / 'catalogue-applied.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
