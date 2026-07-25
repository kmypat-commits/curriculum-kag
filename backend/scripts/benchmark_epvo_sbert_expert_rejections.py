"""Benchmark SBERT using only explicit expert rejections as negative labels."""
from __future__ import annotations
import argparse,json,random
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics import accuracy_score,average_precision_score,f1_score,precision_score,recall_score,roc_auc_score

def text(x): return x.get("ru") or x.get("kz") or x.get("en") or ""
def load(path,seed=42):
    data={s:{0:[],1:[]} for s in ("validation","test")}; rng=random.Random(seed)
    with path.open(encoding="utf-8") as f:
        for line in f:
            r=json.loads(line); s=r.get("split"); score=r.get("expert_score")
            if s not in data or score is None: continue
            y=0 if float(score)<.25 else 1
            row=(text(r["course_title"])+". "+text(r["course_description"]),text(r["lo_text"]),y)
            data[s][y].append(row)
    result={}
    for s,groups in data.items():
        n=min(len(groups[0]),len(groups[1])); rng.shuffle(groups[0]);rng.shuffle(groups[1]); rows=groups[0][:n]+groups[1][:n];rng.shuffle(rows);result[s]=rows
    return result
def report(y,p,t):
    z=p>=t
    return {"examples":len(y),"roc_auc":float(roc_auc_score(y,p)),"pr_auc":float(average_precision_score(y,p)),"threshold":float(t),"accuracy":float(accuracy_score(y,z)),"precision":float(precision_score(y,z)),"recall":float(recall_score(y,z)),"f1":float(f1_score(y,z))}
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--input",default="experiment-results/epvo-expert-labels/course_lo_pairs.jsonl");ap.add_argument("--model",default="models/paraphrase-multilingual-mpnet-base-v2");ap.add_argument("--output",default="experiment-results/epvo-sbert-expert-rejections");ap.add_argument("--batch-size",type=int,default=24);a=ap.parse_args()
    rows=load(Path(a.input));m=SentenceTransformer(a.model,local_files_only=True,device="cpu");stored={}
    for s,items in rows.items():
        c=m.encode([x[0] for x in items],batch_size=a.batch_size,normalize_embeddings=True,show_progress_bar=True);o=m.encode([x[1] for x in items],batch_size=a.batch_size,normalize_embeddings=True,show_progress_bar=True);stored[s]=(np.asarray([x[2] for x in items]),np.sum(c*o,axis=1))
    vy,vp=stored["validation"]; thresholds=np.linspace(float(vp.min()),float(vp.max()),301);t=max(thresholds,key=lambda x:f1_score(vy,vp>=x))
    result={"created_at":datetime.now(timezone.utc).isoformat(),"model":a.model,"negative_definition":"explicit expert score < 0.25 only","validation":report(*stored["validation"],t),"test":report(*stored["test"],t)};out=Path(a.output);out.mkdir(parents=True,exist_ok=True);(out/"metrics.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
if __name__=="__main__":main()
