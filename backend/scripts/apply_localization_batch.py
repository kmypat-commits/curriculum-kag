"""Guarded import of explicitly translated source-copy localization drafts."""
import argparse
import hashlib
import json
from pathlib import Path

from sqlalchemy import create_engine, text

FIELDS = ('title', 'description', 'source', 'status')


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def prepare_batch(db, rows):
    changes, skipped, seen = [], [], set()
    for row in rows:
        key = (int(row['course_id']), row['language'])
        if key in seen or key[1] not in ('ru', 'kk', 'en'):
            raise ValueError('invalid_or_duplicate_target')
        seen.add(key)
        source = db.execute(text('SELECT title,description FROM courses WHERE id=:id'), {'id': key[0]}).mappings().first()
        if not source or source['title'] != row['source_title'] or source['description'] != row['source_description']:
            raise ValueError(f'source_changed:{key}')
        if any('\ufffd' in str(source[field] or '') for field in ('title', 'description')):
            skipped.append({'course_id': key[0], 'language': key[1], 'reason': 'damaged_source'})
            continue
        if not all(str(row.get(field) or '').strip() for field in ('title', 'description')):
            raise ValueError(f'empty_translation:{key}')
        old = db.execute(text('SELECT id,course_id,language,title,description,source,status FROM course_localizations WHERE course_id=:cid AND language=:lang'), {'cid': key[0], 'lang': key[1]}).mappings().first()
        if not old or old['status'] != 'draft' or old['source'] != 'automatic_course_draft':
            skipped.append({'course_id': key[0], 'language': key[1], 'reason': 'not_source_copy_draft'})
            continue
        new = dict(old)
        for field in ('title', 'description'):
            if not str(old[field] or '').strip() or old[field] == source[field]:
                new[field] = row[field]
        if all(new[field] == old[field] for field in ('title', 'description')):
            skipped.append({'course_id': key[0], 'language': key[1], 'reason': 'existing_translations'})
            continue
        new.update(source='machine_translation_gpt6_luna', status='needs_review')
        changes.append({'before': dict(old), 'after': new, 'source': dict(source),
                        'source_hash': _digest(dict(source)), 'translator': row.get('translator')})
    return changes, skipped


def apply_prepared(db, changes):
    changed = 0
    for change in changes:
        old, new, source = change['before'], change['after'], change['source']
        params = {'id': old['id'], 'cid': old['course_id'],
                  'source_title': source['title'], 'source_description': source['description'] or ''}
        params.update({f'old_{field}': old[field] or '' for field in FIELDS})
        params.update({f'new_{field}': new[field] for field in FIELDS})
        timestamp = ',updated_at=CURRENT_TIMESTAMP' if db.dialect.name == 'postgresql' else ''
        result = db.execute(text('UPDATE course_localizations SET title=:new_title,description=:new_description,source=:new_source,status=:new_status' + timestamp +
            ' WHERE id=:id AND COALESCE(title,\'\')=:old_title AND COALESCE(description,\'\')=:old_description AND COALESCE(source,\'\')=:old_source AND COALESCE(status,\'\')=:old_status'
            ' AND EXISTS(SELECT 1 FROM courses WHERE id=:cid AND title=:source_title AND COALESCE(description,\'\')=:source_description)'), params)
        if result.rowcount != 1:
            raise ValueError(f'concurrent_change:{old["id"]}')
        changed += 1
    return changed


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--batch', type=Path)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    from app.config import settings
    engine = create_engine(settings.DATABASE_URL)
    with engine.begin() as db:
        if args.restore:
            snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
            changes = [dict(item, before=item['after'], after=item['before']) for item in snapshot['changes']]
            changed = apply_prepared(db, changes)
            print(json.dumps({'restored': changed}))
            return
        if not args.batch:
            parser.error('--batch required for import')
        rows = json.loads(args.batch.read_text(encoding='utf-8'))
        changes, skipped = prepare_batch(db, rows)
        if args.apply:
            snapshot = {'batch_sha256': hashlib.sha256(args.batch.read_bytes()).hexdigest(),
                        'changes': changes, 'skipped': skipped}
            with args.snapshot.open('x', encoding='utf-8') as output:
                json.dump(snapshot, output, ensure_ascii=False, indent=2)
                output.flush()
                import os
                os.fsync(output.fileno())
            changed = apply_prepared(db, changes)
        else:
            changed = 0
    print(json.dumps({'prepared': len(changes), 'updated': changed, 'skipped': len(skipped)}))


if __name__ == '__main__':
    main()
