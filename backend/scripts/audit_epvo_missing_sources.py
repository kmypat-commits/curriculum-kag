from sqlalchemy import create_engine, text
import json, os

e=create_engine(os.environ['DATABASE_URL'])
with e.connect() as c:
 rows=c.execute(text("""
 select id,approved_course_id,title_ru,title_kk,title_en,source_keys,content_json
 from epvo_disciplines_normalized
 where length(btrim(coalesce(content_json->>'description_ru','')))=0
    or length(btrim(coalesce(content_json->>'description_kk','')))=0
    or length(btrim(coalesce(content_json->>'description_en','')))=0
    or title_kk is null or length(btrim(coalesce(title_kk,'')))=0
    or title_en is null or length(btrim(coalesce(title_en,'')))=0
 """)).mappings().all()
 summary={'rows':len(rows),'raw_rows':0,'available':{lang:0 for lang in ('ru','kk','en')},'missing':{lang:0 for lang in ('ru','kk','en')}}
 for r in rows:
  keys=[str(x) for x in (r['source_keys'] or [])]
  raw=[]
  if keys:
   raw=c.execute(text("select source_key,payload_json from raw_epvo_disciplines where source_key=any(:keys)"),{'keys':keys}).mappings().all()
  avail={lang:0 for lang in ('ru','kk','en')}
  for x in raw:
   p=x['payload_json'] or {}
   for lang,name in [('ru','nameRu'),('kk','nameKz'),('en','nameEn')]:
    if str(p.get(name) or '').strip(): avail[lang]+=1
  summary['raw_rows']+=len(raw)
  for lang in avail:
   summary['available'][lang]+=sum(1 for x in raw if str((x['payload_json'] or {}).get({'ru':'briefinforu','kk':'briefinfo','en':'briefinfoen'}[lang]) or '').strip())
   if not str((r['content_json'] or {}).get('description_'+lang) or '').strip(): summary['missing'][lang]+=1
 print(summary)
