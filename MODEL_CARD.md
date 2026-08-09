---
library_name: sentence-transformers
base_model: sentence-transformers/paraphrase-multilingual-mpnet-base-v2
language:
- ru
- kk
- en
pipeline_tag: sentence-similarity
license: apache-2.0
---

# Curriculum-KAG CEER SBERT 40k

This model is the production candidate used to score semantic relationships between a course and a programme learning outcome. It is one evidence source inside Curriculum-KAG, not an autonomous curriculum generator.

## Training

- base encoder: `paraphrase-multilingual-mpnet-base-v2`;
- embedding dimension: 768;
- domain fine-tuning: 40,000 course–learning-outcome pairs;
- labels: graded expert evidence;
- split: by complete programme to reduce direct leakage;
- seed: 42;
- operational threshold: 0.3449310730397701.

## Frozen test metrics

| Model | ROC-AUC | PR-AUC | F1 |
|---|---:|---:|---:|
| Base multilingual SBERT | 0.7031 | 0.6946 | 0.6886 |
| CEER SBERT 40k | 0.7666 | 0.7681 | 0.7188 |

Ranking audit: Recall@10 0.6700, MRR 0.7906, nDCG@10 0.6654 and HitRate@10 0.9704 on the documented frozen audit.

## Correct interpretation

The score estimates semantic evidence for a course–learning-outcome relationship. It is not the percentage of a learning outcome taught by one course. Curriculum-KAG combines this score with expert evidence, education level, field, credits, semester constraints, prerequisites and regulatory rules.

## Limitations

The model can inherit historical terminology and expert disagreement. It may over-rank lexically similar but professionally unrelated courses. Production use therefore requires contextual guards, the independent verifier and human review. The model must not be used as the sole basis for accreditation or programme approval.
