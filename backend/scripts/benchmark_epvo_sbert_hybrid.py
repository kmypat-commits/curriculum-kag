"""Evaluate SBERT component similarities plus a leakage-safe local calibrator."""
from __future__ import annotations

import argparse, json, random, re
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, average_precision_score, f1_score, precision_score, recall_score, roc_auc_score

def txt(x): return x.get("ru") or x.get("kz") or x.get("en") or ""
def tokens(x): return set(re.findall(r"\w+", x.casefold()))
def jac(a,b):
    a,b=tokens(a),tokens(b); return len(a&b)/max(1,len(a|b))

def collect(path, split, limit):
    rows=[]
    with path.open(encoding="utf-8") as s:
        for line in s:
            p=json.loads(line)
            if p.get("split")!=split: continue
            cs={str(x["id"]):x for x in p["courses"]}; os={str(x["id"]):x for x in p["outcomes"]}; es={(str(a),str(b)) for a,b in p["positive_edges"]}
            by={}
            for c,o in es: by.setdefault(c,set()).add(o)
            rng=random.Random(f"{p['program_id']}:hybrid:42")
            for c,pos in by.items():
                neg=[o for o in os if o not in pos]
                if c not in cs or not neg: continue
                for o,y in ((rng.choice(sorted(pos)),1),(rng.choice(neg),0)):
                    course=cs[c]; rows.append((txt(course["title"]),txt(course["description"]),txt(os[o]["text"]),y,float(course.get("credits") or 0)))
                if len(rows)>=limit:return rows
    return rows

def features(model,rows,batch):
    titles=model.encode([r[0] for r in rows],batch_size=batch,normalize_embeddings=True,show_progress_bar=True)
    descs=model.encode([r[1] for r in rows],batch_size=batch,normalize_embeddings=True,show_progress_bar=True)
    outs=model.encode([r[2] for r in rows],batch_size=batch,normalize_embeddings=True,show_progress_bar=True)
    tc=np.sum(titles*outs,axis=1); dc=np.sum(descs*outs,axis=1)
    extra=np.asarray([[jac(r[0],r[2]),jac(r[1],r[2]),len(r[0]),len(r[1]),len(r[2]),r[4]] for r in rows],dtype=np.float32)
    return np.column_stack((tc,dc,np.maximum(tc,dc),extra)),np.asarray([r[3] for r in rows])

def report(y,p):
    z=p>=.5
    return {"examples":len(y),"roc_auc":float(roc_auc_score(y,p)),"pr_auc":float(average_precision_score(y,p)),"accuracy":float(accuracy_score(y,z)),"precision":float(precision_score(y,z)),"recall":float(recall_score(y,z)),"f1":float(f1_score(y,z))}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--input",default="experiment-results/epvo-link-dataset/programs.jsonl");ap.add_argument("--model",default="models/paraphrase-multilingual-mpnet-base-v2");ap.add_argument("--output",default="experiment-results/epvo-sbert-hybrid");ap.add_argument("--limit",type=int,default=3000);ap.add_argument("--batch-size",type=int,default=24);a=ap.parse_args()
    source=Path(a.input);out=Path(a.output);out.mkdir(parents=True,exist_ok=True);m=SentenceTransformer(a.model,local_files_only=True,device="cpu")
    data={s:features(m,collect(source,s,a.limit),a.batch_size) for s in ("train","validation","test")}
    clf=HistGradientBoostingClassifier(max_iter=180,max_leaf_nodes=15,l2_regularization=1.0,random_state=42).fit(*data["train"])
    result={"created_at":datetime.now(timezone.utc).isoformat(),"model":a.model,"device":"cpu","features":["title_cosine","description_cosine","max_cosine","word_overlap","lengths","credits"],"validation":report(data["validation"][1],clf.predict_proba(data["validation"][0])[:,1]),"test":report(data["test"][1],clf.predict_proba(data["test"][0])[:,1])}
    (out/"metrics.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
if __name__=="__main__":main()
