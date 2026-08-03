# Frozen results table for TEM Journal

This table is the single publication-facing summary of the current frozen evaluation. Point estimates for the production classifier come from the independent CUDA rerun on the archived `epvo-link-dataset`; uncertainty is programme-level bootstrap (2,000 repetitions, test split: 114 programmes, 6,000 pairs). Historical passport values are retained only as a provenance reference and are not averaged with the rerun.

| System / role | ROC-AUC | PR-AUC | F1 | Precision | Recall | Status |
|---|---:|---:|---:|---:|---:|---|
| Multilingual SBERT baseline | 0.7031 | 0.6946 | 0.6886 | — | — | Reference baseline |
| SBERT fine-tuned on EPVO (historical passport) | 0.7666 | 0.7681 | 0.7188 | 0.6255 | 0.8450 | Production candidate |
| SBERT fine-tuned on EPVO (independent CUDA rerun) | 0.7647 | 0.7673 | 0.7209 | 0.6212 | 0.8587 | Frozen primary estimate |
| Programme-level 95% CI for the CUDA rerun | [0.7378, 0.7908] | [0.7367, 0.7957] | [0.7032, 0.7371] | [0.6051, 0.6378] | [0.8282, 0.8846] | 2,000 bootstrap repetitions |
| Expert-weighted memory reranker | 0.6857 Recall@10 | 0.7975 MRR | 0.6789 nDCG@10 | — | — | Experimental; not enabled in production |

## Interpretation

The independent rerun confirms that EPVO fine-tuning improves ranking/classification over the multilingual SBERT baseline. The expert-weighted memory reranker is reported separately because it optimizes retrieval ordering rather than the binary classifier and remains disabled in production. GNN/LSTM pilots are future-work controls and are not included in the primary efficacy claim.

## Machine-readable sources

- `backend/experiment-results/epvo-sbert-finetuned-40k-ci-frozen/metrics-with-ci.json`
- `backend/experiment-results/epvo-sbert-finetuned-40k-ci-frozen/predictions.jsonl`
- `backend/experiment-results/epvo-link-dataset/programs.jsonl` (archived source snapshot)
