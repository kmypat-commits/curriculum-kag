"""Bulk restore EPVO external expert strengths into normalized PostgreSQL links."""
from __future__ import annotations

import argparse, json, os
from collections import defaultdict
from sqlalchemy import create_engine, text

def score(v):
    try:
        x = float(str(v).replace(',', '.'))
    except (TypeError, ValueError):
        return None
    return x if x in (0.0, 0.5, 1.0) else None

def level(x):
    return 'rejected' if x <= 0 else ('medium' if x < 0.75 else 'strong')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--database-url', default=os.getenv('DATABASE_URL'))
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--output', default='')
    a = ap.parse_args()
    if not a.database_url:
        raise SystemExit('--database-url or DATABASE_URL is required')
    eng = create_engine(a.database_url, pool_pre_ping=True)
    rows = []
    raw_votes = 0
    with eng.connect() as db:
        source_to_ids = defaultdict(list)
        for d in db.execute(text('SELECT id, source_keys FROM epvo_disciplines_normalized')):
            for key in (d.source_keys or []):
                source_to_ids[str(key)].append(int(d.id))
        raw = db.execute(text('SELECT program_source_id, source_key, payload_json FROM raw_epvo_disciplines ORDER BY program_source_id, source_key'))
        for r in raw:
            checks = defaultdict(list)
            for item in (r.payload_json or {}).get('expertCheckResults') or []:
                x = score(item.get('result')); lo = item.get('floId')
                if x is not None and lo is not None:
                    checks[str(lo)].append(x); raw_votes += 1
            for lo, vals in checks.items():
                for did in source_to_ids.get(str(r.source_key), []):
                    rows.append((str(r.program_source_id), did, lo, round(sum(vals)/len(vals), 4)))
        stats = {'raw_votes': raw_votes, 'aggregated_pairs': len(rows), 'dry_run': a.dry_run}
        if not a.dry_run:
            conn = db.connection
            cur = conn.connection.cursor()
            cur.execute('CREATE TEMP TABLE tmp_epvo_expert (program_source_id text, discipline_id bigint, lo_source_key text, strength double precision) ON COMMIT DROP')
            import io
            buf = io.BytesIO(b''.join(_iter_csv(rows)))
            cur.copy_expert('COPY tmp_epvo_expert FROM STDIN WITH (FORMAT csv, DELIMITER E\'\\t\', NULL \'\\N\')', buf)
            cur.execute('CREATE INDEX ON tmp_epvo_expert (program_source_id, discipline_id, lo_source_key)')
            cur.execute("""UPDATE epvo_discipline_lo_links l
                SET strength=t.strength,
                    expert_level=CASE WHEN t.strength<=0 THEN 'rejected' WHEN t.strength<0.75 THEN 'medium' ELSE 'strong' END
                FROM tmp_epvo_expert t
                WHERE l.discipline_id=t.discipline_id AND l.program_source_id=t.program_source_id AND l.lo_source_key=t.lo_source_key""")
            stats['links_updated'] = cur.rowcount
            db.commit()
        else:
            stats['sample'] = rows[:3]
    payload=json.dumps(stats, ensure_ascii=False, indent=2)
    print(payload, flush=True)
    if a.output:
        open(a.output, 'w', encoding='utf-8').write(payload+'\n')

def _iter_csv(rows):
    for p,d,l,v in rows:
        yield (f'{p}\t{d}\t{l}\t{v}\n').encode()

if __name__ == '__main__':
    main()
