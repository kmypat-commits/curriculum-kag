"""Frozen benchmark of SBERT plus train-only EPVO expert-weighted memory.

The memory is built only from train programmes. Evidence with expert score 1
is preferred over 0.5; rejected (0) evidence is never used. The test split is
unchanged and selected independently by the existing ranking-v1 policy.
"""
from __future__ import annotations
import argparse, hashlib, heapq, json, math, re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from sentence_transformers import SentenceTransformer

TOKEN_RE = re.compile(r"\s+")

def loc(v):
    if not isinstance(v, dict): return ""
    return next((str(v.get(k) or "").strip() for k in ("ru","kz","en") if v.get(k)), "")
def norm(v): return TOKEN_RE.sub(" ", str(v or "").casefold()).strip()
def title(c): return norm(loc(c.get("title") or {}))
def text_course(c): return " | ".join(x for x in (loc(c.get("title") or {}),loc(c.get("description") or {})) if x)
def scope(p): return norm(loc(p.get("program_group") or {})) or norm(loc(p.get("training_direction") or {}))

def select(path, split, limit, seed):
    rows=[]; serial=0
    with path.open(encoding="utf8") as f:
        for line in f:
            p=json.loads(line)
            if p.get("split")!=split: continue
            serial+=1; rank=int(hashlib.sha256(f"{seed}:{split}:{p.get('program_id')}".encode()).hexdigest(),16)
            item=(-rank,serial,p)
            if len(rows)<limit: heapq.heappush(rows,item)
            elif rank < -rows[0][0]: heapq.heapreplace(rows,item)
    return [x[2] for x in sorted(rows,key=lambda x:-x[0])]

def add(bucket, key, evidence, score, limit):
    if not key or not evidence: return
    h=hashlib.sha1(norm(evidence).encode()).hexdigest()
    previous=bucket[key].get(h)
    if previous is None or score>previous[0]: bucket[key][h]=(score,evidence)
    if len(bucket[key])>limit:
        worst=min(bucket[key], key=lambda x:(bucket[key][x][0],x))
        del bucket[key][worst]

def collect(weighted_path, weighted_programmes_path, limit):
    programme_scope={}
    with weighted_programmes_path.open(encoding="utf8") as f:
        for line in f:
            p=json.loads(line); programme_scope[str(p.get("program_id"))]=norm(loc(p.get("program_group") or {})) or norm(loc(p.get("training_direction") or {}))
    global_raw=defaultdict(dict); scoped_raw=defaultdict(dict); counts=defaultdict(int)
    with weighted_path.open(encoding="utf8") as f:
        for line in f:
            r=json.loads(line)
            if r.get("split")!="train": continue
            s=r.get("expert_score")
            if s is None or float(s)<0.5: continue
            c=norm(loc(r.get("course_title") or {})); lo=loc(r.get("lo_text") or {})
            if not c or not lo: continue
            s=float(s); add(global_raw,c,lo,s,limit)
            sc=programme_scope.get(str(r.get("program_id")))
            if sc: add(scoped_raw,(sc,c),lo,s,limit)
            counts[f"score_{s}"]+=1
    global_mem={k:[v for v in sorted(vals.values(), key=lambda x:-x[0])] for k,vals in global_raw.items()}
    scoped_mem={k:[v for v in vals.values()] for k,vals in scoped_raw.items()}
    return global_mem,scoped_mem,dict(counts)

def aggregate(q,evidence,vectors):
    if not evidence: return None
    scores=np.asarray([x[0] for x in evidence],dtype=float)
    texts=[x[1] for x in evidence]
    sim=q@np.asarray([vectors[x] for x in texts]).T
    weights=scores / max(float(scores.sum()),1e-9)
    weighted=(sim*weights.reshape(1,-1)).sum(axis=1)
    top=np.sort(sim,axis=1)[:,-min(3,sim.shape[1]):]
    return .55*sim.max(axis=1)+.25*top.mean(axis=1)+.20*weighted

def score_split(programmes,model,gmem,smem,vectors,batch):
    rows=[]; coverage=defaultdict(int)
    for p in programmes:
        courses={str(x["id"]):x for x in p.get("courses") or []}; outcomes={str(x["id"]):x for x in p.get("outcomes") or []}
        links=defaultdict(set)
        for cid,lid in p.get("positive_edges") or []:
            if str(cid) in courses and str(lid) in outcomes: links[str(lid)].add(str(cid))
        cids=[k for k,c in courses.items() if text_course(c)]; lids=[k for k in outcomes if links.get(k) and loc(outcomes[k].get("text") or {})]
        if len(cids)<2 or not lids: continue
        cv=np.asarray(model.encode([text_course(courses[k]) for k in cids],batch_size=batch,normalize_embeddings=True,show_progress_bar=False)); qv=np.asarray(model.encode([loc(outcomes[k].get("text") or {}) for k in lids],batch_size=batch,normalize_embeddings=True,show_progress_bar=False)); base=qv@cv.T
        gm=base.copy(); sm=base.copy(); sc=scope(p)
        for j,cid in enumerate(cids):
            key=title(courses[cid]); ge=gmem.get(key); se=smem.get((sc,key))
            if ge:
                gm[:,j]=aggregate(qv,ge,vectors); coverage['global_rows']+=1
            if se:
                sm[:,j]=aggregate(qv,se,vectors); coverage['scoped_rows']+=1
            coverage['candidate_rows']+=1
        pos={k:i for i,k in enumerate(cids)}
        for i,lid in enumerate(lids): rows.append((base[i],gm[i],sm[i],{pos[x] for x in links[lid] if x in pos}))
    coverage['global_fraction']=coverage['global_rows']/max(1,coverage['candidate_rows']); coverage['scoped_fraction']=coverage['scoped_rows']/max(1,coverage['candidate_rows'])
    return rows,dict(coverage)

def metrics(rows,gw,sw):
    vals=defaultdict(list)
    for base,g,s,rel in rows:
        rank=np.argsort(-((1-gw-sw)*base+gw*g+sw*s))
        for k in (5,10): vals[f'recall_at_{k}'].append(sum(int(x) in rel for x in rank[:k])/len(rel))
        first=next((i+1 for i,x in enumerate(rank) if int(x) in rel),None); vals['mrr'].append(1/first if first else 0)
        dcg=sum((1 if int(x) in rel else 0)/math.log2(i+2) for i,x in enumerate(rank[:10])); ideal=sum(1/math.log2(i+2) for i in range(min(len(rel),10))); vals['ndcg_at_10'].append(dcg/ideal if ideal else 0)
    return {k:float(np.mean(v)) for k,v in vals.items()}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--data',default='.runtime/epvo-ranking-postgres-clean-v2/programs.jsonl'); ap.add_argument('--weighted',default='.runtime/epvo-weighted-postgres/course_lo_pairs.jsonl'); ap.add_argument('--weighted-programmes',default='.runtime/epvo-weighted-postgres/programs.jsonl'); ap.add_argument('--model',default='models/epvo-sbert-multipositive-listwise-4k'); ap.add_argument('--output',default='experiment-results/epvo-weighted-memory-benchmark/metrics.json'); ap.add_argument('--programmes',type=int,default=120); ap.add_argument('--per-key-limit',type=int,default=32); ap.add_argument('--batch-size',type=int,default=24); ap.add_argument('--device',default='cuda'); args=ap.parse_args()
    data=Path(args.data); model=SentenceTransformer(args.model,device=args.device,local_files_only=True); model.eval()
    train=select(data,'train',args.programmes,'ranking-v1'); val=select(data,'validation',args.programmes,'ranking-v1'); test=select(data,'test',args.programmes,'ranking-v1')
    gmem,smem,counts=collect(Path(args.weighted),Path(args.weighted_programmes),args.per_key_limit)
    ev=sorted(set(x[1] for d in (gmem,smem) for vals in d.values() for x in vals));
    matrix=np.asarray(model.encode(ev,batch_size=args.batch_size,normalize_embeddings=True,show_progress_bar=False)); vectors=dict(zip(ev,matrix))
    vr,vc=score_split(val,model,gmem,smem,vectors,args.batch_size); tr,tc=score_split(test,model,gmem,smem,vectors,args.batch_size)
    grid=[]
    for gw in np.linspace(0,.3,7):
        for sw in np.linspace(0,.5,11):
            if gw+sw<=.8: grid.append((gw,sw,metrics(vr,gw,sw)))
    selected=max(grid,key=lambda x:(x[2]['recall_at_10']+.04*x[2]['ndcg_at_10']+.02*x[2]['mrr'],x[2]['recall_at_10']))
    baseline=metrics(tr,0,0); hybrid=metrics(tr,selected[0],selected[1]); report={'created_at':datetime.now(timezone.utc).isoformat(),'method':'SBERT plus train-only expert-weighted EPVO memory','model':args.model,'split_policy':'programme-level frozen split','expert_counts':counts,'memory':{'global_keys':len(gmem),'scoped_keys':len(smem),'evidence':len(ev),'per_key_limit':args.per_key_limit},'validation_coverage':vc,'test_coverage':tc,'selected_global_weight':selected[0],'selected_scoped_weight':selected[1],'validation_selected':selected[2],'frozen_test_baseline':baseline,'frozen_test_hybrid':hybrid,'frozen_test_delta':{k:hybrid[k]-baseline[k] for k in hybrid},'production_model_changed':False}
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8'); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
