"""Evaluate a graded, train-only EPVO expert-memory reranker."""
from __future__ import annotations

import argparse, hashlib, json, math
from collections import defaultdict
from pathlib import Path
import numpy as np
from sentence_transformers import SentenceTransformer


def txt(value: dict) -> str:
    return value.get("ru") or value.get("kz") or value.get("en") or ""


def pick(path: Path, split: str, n: int) -> list[str]:
    ids = sorted({str(json.loads(x)["program_id"]) for x in path.open(encoding="utf-8") if json.loads(x).get("split") == split}, key=lambda p: hashlib.sha256(f"weighted-memory:{split}:{p}".encode()).hexdigest())
    return ids[:n]


def load(path: Path, selected: set[str] | None = None):
    data = defaultdict(lambda: {"courses": {}, "los": {}, "rel": defaultdict(dict)})
    with path.open(encoding="utf-8") as f:
        for line in f:
            r=json.loads(line); p=str(r["program_id"])
            if selected is not None and p not in selected: continue
            if r.get("expert_score") is None: continue
            c=str(r["course_id"]); lo=str(r["lo_id"]); value=float(r["expert_score"])
            data[p]["courses"][c]=txt(r.get("course_title") or {})+". "+txt(r.get("course_description") or {})
            data[p]["los"][lo]=txt(r.get("lo_text") or {})
            data[p]["rel"][lo][c]=value
    return data


def memory(path: Path, train_ids: set[str]):
    m=defaultdict(dict)
    with path.open(encoding="utf-8") as f:
        for line in f:
            r=json.loads(line); p=str(r["program_id"])
            if p not in train_ids or r.get("expert_score") is None or float(r["expert_score"])<0.5: continue
            c=str(r["course_id"]); lo=txt(r.get("lo_text") or {})
            if lo: m[c][lo]=max(float(r["expert_score"]),m[c].get(lo,0.0))
    return {c:list(v.items()) for c,v in m.items()}


def rows_for(data, model, mem, vectors):
    rows=[]
    for p,b in data.items():
        ids=list(b["courses"]); los=[x for x in b["los"] if b["rel"].get(x)]
        if len(ids)<2 or not los: continue
        cv=model.encode([b["courses"][x] for x in ids],batch_size=48,normalize_embeddings=True,show_progress_bar=False); qv=model.encode([b["los"][x] for x in los],batch_size=48,normalize_embeddings=True,show_progress_bar=False)
        base=np.asarray(qv)@np.asarray(cv).T; prior=base.copy()
        for j,c in enumerate(ids):
            ev=mem.get(c)
            if not ev: continue
            mat=np.asarray([vectors[t] for t,_ in ev]); weights=np.asarray([v for _,v in ev]);
            prior[:,j]=((np.asarray(qv)@mat.T)*weights).max(axis=1)
        for i,lo in enumerate(los):
            rel={c:v for c,v in b["rel"][lo].items() if v>=0.5};
            if rel:
                positions={course:index for index,course in enumerate(ids)}
                rows.append((base[i],prior[i],{positions[c] for c in rel if c in positions}))
    return rows


def score(rows, w):
    vals=defaultdict(list)
    for base,prior,rel in rows:
        rank=np.argsort(-((1-w)*base+w*prior));
        vals["r5"].append(sum(int(k) in rel for k in rank[:5])/len(rel)); vals["r10"].append(sum(int(k) in rel for k in rank[:10])/len(rel)); first=next((x+1 for x,k in enumerate(rank) if int(k) in rel),None); vals["mrr"].append(1/first if first else 0)
        dcg=sum((1 if int(k) in rel else 0)/math.log2(x+2) for x,k in enumerate(rank[:10])); ideal=sum(1/math.log2(x+2) for x in range(min(10,len(rel)))); vals["ndcg"].append(dcg/ideal if ideal else 0)
    return {k:float(np.mean(v)) for k,v in vals.items()}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data',default='.runtime/epvo-weighted-postgres/course_lo_pairs.jsonl');ap.add_argument('--model',required=True);ap.add_argument('--output',required=True);ap.add_argument('--programmes',type=int,default=80);ap.add_argument('--device',default='cuda');a=ap.parse_args();path=Path(a.data);train_ids=set(pick(path,'train',100000)); val_ids=set(pick(path,'validation',a.programmes)); test_ids=set(pick(path,'test',a.programmes)); train=load(path,train_ids); val=load(path,val_ids); test=load(path,test_ids); mem=memory(path,train_ids); texts=sorted({t for v in mem.values() for t,_ in v}); model=SentenceTransformer(a.model,device=a.device,local_files_only=True); enc=model.encode(texts,batch_size=48,normalize_embeddings=True,show_progress_bar=True); vectors=dict(zip(texts,enc)); choices=[]
    val_rows=rows_for(val,model,mem,vectors); test_rows=rows_for(test,model,mem,vectors); choices=[]
    for w in np.linspace(0,1,21):
        m=score(val_rows,float(w)); choices.append({'weight':round(float(w),2),**m,'objective':m['r10']+.05*m['ndcg']+.02*m['mrr']})
    best=max(choices,key=lambda x:(x['objective'],x['r10']))['weight']; base=score(test_rows,0); final=score(test_rows,best); out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True); report={'method':'train-only graded EPVO expert memory keyed by course id','model':a.model,'memory_courses':len(mem),'selected_weight':best,'validation_choices':choices,'test_baseline':base,'test_reranked':final,'delta':{k:final[k]-base[k] for k in final},'production_model_changed':False};out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
