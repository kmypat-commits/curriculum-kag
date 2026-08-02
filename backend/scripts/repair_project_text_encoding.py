"""Repair legacy UTF-8-as-Latin-1 text for one project, preserving an audit copy."""
from pathlib import Path
import argparse, json
from sqlalchemy import create_engine, text

def fix(value):
    if not isinstance(value,str) or not any(x in value for x in ('Ð','Ñ','Р','С','вЂ')): return value
    try:
        candidate=value.encode('latin1').decode('utf8')
    except (UnicodeEncodeError,UnicodeDecodeError): return value
    return candidate if sum(value.count(x) for x in ('Ð','Ñ','Р','С','вЂ')) > sum(candidate.count(x) for x in ('Ð','Ñ','Р','С','вЂ')) else value

def main():
    p=argparse.ArgumentParser(); p.add_argument('--database-url',required=True); p.add_argument('--project-id',type=int,required=True); p.add_argument('--report',default='.runtime/project-text-repair.json'); a=p.parse_args()
    e=create_engine(a.database_url,pool_pre_ping=True); changes=[]
    with e.begin() as db:
        rows=db.execute(text('select id,title,domain1,domain2,goal from projects where id=:id'),{'id':a.project_id}).mappings().first()
        if not rows: raise SystemExit('project not found')
        vals={k:fix(rows[k]) for k in ('title','domain1','domain2','goal')}
        for k in vals:
            if vals[k]!=rows[k]: changes.append({'table':'projects','id':rows['id'],'field':k,'before':rows[k],'after':vals[k]})
        db.execute(text('update projects set title=:title,domain1=:d1,domain2=:d2,goal=:goal where id=:id'),{'title':vals['title'],'d1':vals['domain1'],'d2':vals['domain2'],'goal':vals['goal'],'id':a.project_id})
        lo=db.execute(text('select lo.id,lo.lo_text from learning_outcomes lo join project_versions v on v.id=lo.project_version_id where v.project_id=:id'),{'id':a.project_id}).mappings().all()
        for row in lo:
            new=fix(row['lo_text'])
            if new!=row['lo_text']:
                changes.append({'table':'learning_outcomes','id':row['id'],'field':'lo_text','before':row['lo_text'],'after':new})
                db.execute(text('update learning_outcomes set lo_text=:v where id=:id'),{'v':new,'id':row['id']})
    Path(a.report).parent.mkdir(parents=True,exist_ok=True); Path(a.report).write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({'changes':len(changes),'report':a.report},ensure_ascii=False))
if __name__=='__main__': main()
