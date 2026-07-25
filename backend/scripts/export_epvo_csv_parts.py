"""Create compact CSV intermediates for the archival EPVO Excel export."""
from __future__ import annotations
import csv,json
from pathlib import Path

ROOT=Path("experiment-results")
OUT=ROOT/"epvo-excel-intermediate"
OUT.mkdir(parents=True,exist_ok=True)

def txt(v,k): return (v or {}).get(k) or ""

with (OUT/"programs.csv").open("w",newline="",encoding="utf-8-sig") as f:
    w=csv.writer(f);w.writerow(["program_id","university_id","status","split","name_ru","name_kz","name_en","goal_ru","goal_kz","goal_en","credits","outcomes","disciplines","declared_links","expert_scored_links","source_file"])
    with (ROOT/"epvo-expert-labels"/"programs.jsonl").open(encoding="utf-8") as s:
        for line in s:
            r=json.loads(line);w.writerow([r["program_id"],r.get("university_id"),r.get("status"),r.get("split"),txt(r.get("name"),"ru"),txt(r.get("name"),"kz"),txt(r.get("name"),"en"),txt(r.get("goal"),"ru"),txt(r.get("goal"),"kz"),txt(r.get("goal"),"en"),r.get("credits"),r.get("outcome_count"),r.get("discipline_count"),r.get("declared_pair_count"),r.get("scored_pair_count"),r.get("source_file")])

with (OUT/"courses.csv").open("w",newline="",encoding="utf-8-sig") as fc,(OUT/"learning_outcomes.csv").open("w",newline="",encoding="utf-8-sig") as fl:
    wc=csv.writer(fc);wl=csv.writer(fl)
    wc.writerow(["program_id","course_id","title_ru","title_kz","title_en","description_ru","description_kz","description_en","credits","year","term"])
    wl.writerow(["program_id","lo_id","lo_code","text_ru","text_kz","text_en"])
    with (ROOT/"epvo-link-context-dataset"/"programs.jsonl").open(encoding="utf-8") as s:
        for line in s:
            r=json.loads(line);pid=r["program_id"]
            for c in r["courses"]:wc.writerow([pid,c["id"],txt(c.get("title"),"ru"),txt(c.get("title"),"kz"),txt(c.get("title"),"en"),txt(c.get("description"),"ru"),txt(c.get("description"),"kz"),txt(c.get("description"),"en"),c.get("credits"),c.get("year"),c.get("term")])
            for lo in r["outcomes"]:wl.writerow([pid,lo["id"],lo.get("code"),txt(lo.get("text"),"ru"),txt(lo.get("text"),"kz"),txt(lo.get("text"),"en")])

parts=[(OUT/"links_part_1.csv").open("w",newline="",encoding="utf-8-sig"),(OUT/"links_part_2.csv").open("w",newline="",encoding="utf-8-sig")]
writers=[csv.writer(x) for x in parts];header=["program_id","university_id","program_status","split","course_id","lo_id","lo_code","declared_link","expert_score","expert_votes","source_file"]
for w in writers:w.writerow(header)
with (ROOT/"epvo-expert-labels"/"course_lo_pairs.jsonl").open(encoding="utf-8") as s:
    for i,line in enumerate(s):
        r=json.loads(line);writers[0 if i<500000 else 1].writerow([r["program_id"],r.get("university_id"),r.get("program_status"),r.get("split"),r["course_id"],r["lo_id"],r.get("lo_code"),r.get("declared_link"),r.get("expert_score"),r.get("expert_votes"),r.get("source_file")])
for f in parts:f.close()
print(json.dumps({p.name:p.stat().st_size for p in OUT.glob("*.csv")},ensure_ascii=False))
