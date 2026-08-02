"""Fast, auditable repair of U+FFFD descriptions using the legacy SQLite backup."""
from __future__ import annotations
import argparse, json, sqlite3
from pathlib import Path
from sqlalchemy import create_engine, text

def main():
    p=argparse.ArgumentParser(); p.add_argument('--database-url', required=True); p.add_argument('--backup', default='.runtime/restore-source/backend/curriculum_kag.db'); p.add_argument('--report', default='.runtime/localization-recovery-report.json'); a=p.parse_args()
    backup=sqlite3.connect(a.backup)
    source={str(r[0]): str(r[1] or '').replace('\ufffd','').strip() for r in backup.execute("select course_id, description from courses") if r[1] and '\ufffd' not in str(r[1])}
    source.update({f'EPVO-{key}': value for key, value in list(source.items())})
    engine=create_engine(a.database_url, pool_pre_ping=True)
    repaired=0; unresolved=0; base_repaired=0; before=[]
    with engine.begin() as db:
        rows=db.execute(text("select l.id,l.course_id,l.language,l.title,l.description,c.course_id as code from course_localizations l join courses c on c.id=l.course_id where l.source in ('encoding_repair_needs_review','legacy_backup_recovery') or l.title like :m or l.description like :m"), {'m':'%\ufffd%'}).mappings().all()
        for r in rows:
            before.append(dict(r))
            desc=source.get(str(r['code']))
            if not desc and str(r['code']).startswith('EPVO-'):
                normalized=db.execute(text("select content_json from epvo_disciplines_normalized where id=:id"), {'id':str(r['code']).split('-',1)[1]}).scalar()
                payload=normalized or {}
                desc=payload.get(f"description_{r['language']}") or payload.get('description')
                if desc and '\ufffd' in str(desc): desc=None
            if desc:
                db.execute(text("update course_localizations set description=:d, status='needs_review', source='legacy_backup_recovery', updated_at=now() where id=:id"), {'d':desc,'id':r['id']}); repaired+=1
            else:
                title=str(r['title'] or '').replace('\ufffd','').strip()
                templates={'ru':f'Дисциплина «{title}»: содержание и результаты обучения требуют экспертной проверки.', 'kk':f'«{title}» пәні: мазмұны мен оқу нәтижелері сараптамалық тексеруді қажет етеді.', 'en':f'Course “{title}”: content and learning outcomes require expert review.'}
                db.execute(text("update course_localizations set title=:t, description=:d, status='needs_review', source='encoding_repair_needs_review', updated_at=now() where id=:id"), {'t':title,'d':templates.get(r['language'],templates['en']),'id':r['id']}); unresolved+=1
        base=db.execute(text("select id,course_id,description from courses where description like :m"), {'m':'%\ufffd%'}).mappings().all()
        for r in base:
            if str(r['course_id']) in source:
                db.execute(text("update courses set description=:d where id=:id"), {'d':source[str(r['course_id'])], 'id':r['id']}); base_repaired+=1
    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).write_text(json.dumps({'corrupt_rows':len(before),'repaired_from_backup':repaired,'cleaned_unresolved':unresolved,'base_repaired':base_repaired,'before':before}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'corrupt_rows':len(before),'repaired_from_backup':repaired,'cleaned_unresolved':unresolved,'base_repaired':base_repaired}, ensure_ascii=False))
    return 0
if __name__=='__main__': raise SystemExit(main())
