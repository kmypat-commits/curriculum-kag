"""Diagnostic blend of title- and stable-course-id EPVO expert memory."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
from sentence_transformers import SentenceTransformer
from benchmark_epvo_expert_memory_ranking import select_splits, target_titles, collect_train_memory, score_split, localized, metrics
from benchmark_epvo_expert_memory_course_id import collect as collect_id, score as score_id

def main():
    p=argparse.ArgumentParser(); p.add_argument('--data',required=True); p.add_argument('--model',required=True); p.add_argument('--output',required=True); p.add_argument('--programmes',type=int,default=258); p.add_argument('--batch-size',type=int,default=48); p.add_argument('--per-course-limit',type=int,default=32); a=p.parse_args()
    path=Path(a.data); selected=select_splits(path,{'validation':a.programmes,'test':a.programmes},'ranking-v1')
    titles=target_titles(selected); title_mem,title_stats=collect_train_memory(path,titles,a.per_course_limit); ids={str(c['id']) for vals in selected.values() for pr in vals for c in pr.get('courses') or []}; id_mem,id_stats=collect_id(path,ids,a.per_course_limit)
    model=SentenceTransformer(a.model,device='cuda',local_files_only=True)
    title_texts=sorted({t for v in title_mem.values() for t in v}); id_texts=sorted({t for v in id_mem.values() for t in v})
    tv=model.encode(title_texts,batch_size=a.batch_size,normalize_embeddings=True,show_progress_bar=False); iv=model.encode(id_texts,batch_size=a.batch_size,normalize_embeddings=True,show_progress_bar=False)
    tvec=dict(zip(title_texts,tv)); ivec=dict(zip(id_texts,iv)); tr,tc=score_split(selected['validation'],model,title_mem,tvec,a.batch_size); ir,ic=score_id(selected['validation'],model,id_mem,ivec,a.batch_size)
    choices=[]
    for wt in np.linspace(0,1,11):
        for wi in np.linspace(0,1-float(wt),11):
            rows=[((1-float(wt)-float(wi))*b+float(wt)*tp+float(wi)*ip,r) for (b,tp,r),(bb,ip,r2) in zip(tr,ir) if r==r2]
            m=metrics(rows); choices.append({'title_weight':round(float(wt),2),'id_weight':round(float(wi),2),'objective':m['recall_at_10']+.05*m['ndcg_at_10']+.02*m['mrr'],**m})
    best=max(choices,key=lambda x:(x['objective'],x['recall_at_10']))
    tr,tc=score_split(selected['test'],model,title_mem,tvec,a.batch_size); ir,ic=score_id(selected['test'],model,id_mem,ivec,a.batch_size)
    def run(wt,wi): return metrics([((1-wt-wi)*b+wt*tp+wi*ip,r) for (b,tp,r),(bb,ip,r2) in zip(tr,ir) if r==r2])
    base=run(0,0); frozen=run(best['title_weight'],best['id_weight'])
    report={'method':'train-only dual EPVO expert memory: canonical title + stable course id','model':a.model,'title_memory':title_stats,'id_memory':id_stats,'validation_coverage':{'title':tc,'id':ic},'selected_weights':{'title':best['title_weight'],'id':best['id_weight']},'frozen_test_baseline':base,'frozen_test':frozen,'frozen_test_delta':{k:frozen[k]-base[k] for k in frozen},'production_model_changed':False}
    Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
