"""Train a leakage-safe expert decision head over frozen local SBERT vectors."""
from __future__ import annotations
import argparse,json,random
from datetime import datetime,timezone
from pathlib import Path
import joblib,numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score,average_precision_score,f1_score,precision_score,recall_score,roc_auc_score

def text(x):return x.get("ru") or x.get("kz") or x.get("en") or ""
def collect(path):
    groups={s:{0:[],1:[]} for s in ("train","validation","test")};rng=random.Random(42)
    with path.open(encoding="utf-8") as f:
        for line in f:
            r=json.loads(line);s=r.get("split");v=r.get("expert_score")
            if s not in groups or v is None:continue
            y=0 if float(v)<.25 else 1;groups[s][y].append((text(r["course_title"])+". "+text(r["course_description"]),text(r["lo_text"]),y))
    out={}
    for s,g in groups.items():
        n=min(len(g[0]),len(g[1]));rng.shuffle(g[0]);rng.shuffle(g[1]);rows=g[0][:n]+g[1][:n];rng.shuffle(rows);out[s]=rows
    return out
def encode(model,rows,batch):
    a=model.encode([x[0] for x in rows],batch_size=batch,normalize_embeddings=True,show_progress_bar=True);b=model.encode([x[1] for x in rows],batch_size=batch,normalize_embeddings=True,show_progress_bar=True)
    cosine=np.sum(a*b,axis=1,keepdims=True);x=np.column_stack((np.abs(a-b),a*b,cosine));y=np.asarray([r[2] for r in rows]);return x,y
def report(y,p):
    z=p>=.5;return {"examples":len(y),"roc_auc":float(roc_auc_score(y,p)),"pr_auc":float(average_precision_score(y,p)),"accuracy":float(accuracy_score(y,z)),"precision":float(precision_score(y,z)),"recall":float(recall_score(y,z)),"f1":float(f1_score(y,z))}
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--input",default="experiment-results/epvo-expert-labels/course_lo_pairs.jsonl");ap.add_argument("--model",default="models/paraphrase-multilingual-mpnet-base-v2");ap.add_argument("--output",default="experiment-results/epvo-sbert-expert-head");ap.add_argument("--batch-size",type=int,default=24);a=ap.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    rows=collect(Path(a.input));model=SentenceTransformer(a.model,local_files_only=True,device="cpu");data={s:encode(model,r,a.batch_size) for s,r in rows.items()}
    best=None
    for c in (.05,.2,1.0,5.0):
        clf=LogisticRegression(C=c,max_iter=1000,class_weight="balanced",random_state=42).fit(*data["train"]);p=clf.predict_proba(data["validation"][0])[:,1];score=roc_auc_score(data["validation"][1],p)
        if best is None or score>best[0]:best=(score,c,clf)
    _,c,clf=best;result={"created_at":datetime.now(timezone.utc).isoformat(),"model":a.model,"head":"logistic on abs-difference, product and cosine","selected_C":c,"negative_definition":"explicit expert score < 0.25","validation":report(data["validation"][1],clf.predict_proba(data["validation"][0])[:,1]),"test":report(data["test"][1],clf.predict_proba(data["test"][0])[:,1])}
    joblib.dump(clf,out/"expert_head.joblib",compress=3);(out/"metrics.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
if __name__=="__main__":main()
