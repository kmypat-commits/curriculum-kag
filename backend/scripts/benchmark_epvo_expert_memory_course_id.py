"""Diagnostic EPVO memory benchmark keyed by stable course id (no production writes)."""
from __future__ import annotations

import argparse, json
from collections import defaultdict
from pathlib import Path
import numpy as np
from sentence_transformers import SentenceTransformer
from benchmark_epvo_expert_memory_ranking import select_splits, localized, course_text, normalize, metrics, blended

def collect(path: Path, targets: set[str], limit: int):
    memory=defaultdict(dict); programmes=edges=retained=0
    with path.open(encoding="utf-8") as f:
        for line in f:
            p=json.loads(line)
            if p.get("split")!="train": continue
            programmes+=1
            courses={str(c["id"]):c for c in p.get("courses") or [] if str(c["id"]) in targets}
            outcomes={str(o["id"]):localized(o.get("text") or {}) for o in p.get("outcomes") or [] if localized(o.get("text") or {})}
            for cid,lid in p.get("positive_edges") or []:
                cid,lid=str(cid),str(lid)
                if cid not in courses or lid not in outcomes: continue
                key=normalize(outcomes[lid]); memory[cid][key]=outcomes[lid]; edges+=1; retained+=1
                if len(memory[cid])>limit: del memory[cid][max(memory[cid])]
    return {k:list(v.values()) for k,v in memory.items()}, {"train_programmes_scanned":programmes,"course_ids_with_train_memory":len(memory),"edges_seen":edges,"matching_edges_seen":retained}

def score(programmes, model, memory, vectors, batch):
    rows=[]; total=covered=0
    for p in programmes:
        courses={str(c["id"]):c for c in p.get("courses") or []}; outcomes={str(o["id"]):o for o in p.get("outcomes") or []}
        links=defaultdict(set)
        for cid,lid in p.get("positive_edges") or []:
            if str(cid) in courses and str(lid) in outcomes: links[str(lid)].add(str(cid))
        ids=[k for k,c in courses.items() if course_text(c)]; los=[k for k in outcomes if links.get(k) and localized(outcomes[k].get("text") or {})]
        if len(ids)<2 or not los: continue
        cv=model.encode([course_text(courses[k]) for k in ids],batch_size=batch,normalize_embeddings=True,show_progress_bar=False)
        qv=model.encode([localized(outcomes[k].get("text") or {}) for k in los],batch_size=batch,normalize_embeddings=True,show_progress_bar=False)
        base=np.asarray(qv)@np.asarray(cv).T; prior=base.copy(); pos={k:i for i,k in enumerate(ids)}
        for col,cid in enumerate(ids):
            total+=1; ev=memory.get(cid)
            if not ev: continue
            covered+=1; mat=np.asarray([vectors[t] for t in ev]); sim=np.asarray(qv)@mat.T; top=np.sort(sim,axis=1)[:,-min(3,sim.shape[1]):]
            prior[:,col]=0.75*sim.max(axis=1)+0.25*top.mean(axis=1)
        for row,lid in enumerate(los): rows.append((base[row],prior[row],{pos[c] for c in links[lid] if c in pos}))
    return rows,{"candidate_rows":total,"memory_candidate_rows":covered,"memory_candidate_fraction":covered/max(1,total)}

def main():
    a=argparse.ArgumentParser(); a.add_argument("--data",required=True); a.add_argument("--model",required=True); a.add_argument("--output",required=True); a.add_argument("--programmes",type=int,default=258); a.add_argument("--batch-size",type=int,default=48); a.add_argument("--per-course-limit",type=int,default=32); args=a.parse_args()
    path=Path(args.data); selected=select_splits(path,{"validation":args.programmes,"test":args.programmes},"ranking-v1")
    targets={str(c["id"]) for vals in selected.values() for p in vals for c in p.get("courses") or []}
    memory,stats=collect(path,targets,args.per_course_limit); texts=sorted({t for vals in memory.values() for t in vals}); model=SentenceTransformer(args.model,device="cuda",local_files_only=True); enc=model.encode(texts,batch_size=args.batch_size,normalize_embeddings=True,show_progress_bar=True); vectors=dict(zip(texts,enc))
    vr,vc=score(selected["validation"],model,memory,vectors,args.batch_size); choices=[]
    for w in np.linspace(0,1,21):
        m=metrics(blended(vr,round(float(w),2))); choices.append({"weight":round(float(w),2),**m,"objective":m["recall_at_10"]+.05*m["ndcg_at_10"]+.02*m["mrr"]})
    best=max(choices,key=lambda x:(x["objective"],x["recall_at_10"])); tr,tc=score(selected["test"],model,memory,vectors,args.batch_size); b=metrics(blended(tr,0)); f=metrics(blended(tr,best["weight"])); report={"method":"train-only expert memory keyed by stable course id","model":args.model,"memory":stats,"validation_coverage":vc,"test_coverage":tc,"selected_weight":best["weight"],"frozen_test_baseline":b,"frozen_test":f,"frozen_test_delta":{k:f[k]-b[k] for k in f},"production_model_changed":False}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True); Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
