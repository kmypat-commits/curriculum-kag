# Supplementary materials for TEM Journal manuscript

## S1. Reproducibility manifest

The manuscript reports only artefacts that can be regenerated from the repository and the authorized EPVO-derived data layer.

| Item | Repository location | Role |
|---|---|---|
| Expert provenance and scale | `docs/EPVO_EXPERT_PROVENANCE_2026_08_03_RU.md` | Explains 0 / 0.5 / 1 judgements and aggregation |
| Ranking experiment | `docs/EPVO_RANKING_EXPERIMENT_2026_08_03_RU.md` | Frozen baseline and expert-memory comparison |
| Weighted-memory benchmark | `backend/experiment-results/epvo-weighted-memory-benchmark/metrics-archive-weighted-v2.json` | Machine-readable ranking metrics |
| Expert restoration report | `backend/.runtime/restore-expert-strength-bulk-apply-final.json` | Transactional update count and source votes |
| Expert-aware importer | `backend/scripts/load_epvo_normalized.py` | Reproducible extraction of expertCheckResults |
| Weighted reranker benchmark | `backend/scripts/benchmark_epvo_weighted_memory.py` | Validation-selected, train-only memory protocol |
| KZ control audit | `backend/.runtime/control-bachelor-kz.json` | Protected GOSO control programme |
| International control audit | `backend/.runtime/control-bachelor-international-v3.json` | Non-GOSO international constraint profile |

## S2. Dataset summary

- 12,215 EPVO programmes;
- 408,638 raw course records;
- 124,521 raw learning outcomes;
- 191,292 normalized course entities;
- 932,483 normalized course–LO links;
- 798,951 links restored from matching expert observations in the active shadow database;
- raw expert votes: 0 = 9,993; 0.5 = 294,877; 1 = 571,972.

The raw layer is retained without mutation. Derived tables are separated from approved generation candidates. Raw registry data and large model weights are not redistributed in this supplementary package without authorization.

## S3. Split and evaluation protocol

Splits are made by programme, not by individual row, with seed 42. The classification test contains 6,000 independent course–LO pairs. The ranking benchmark selects memory weights on validation and freezes them before the test run. No production flag is changed by the benchmark.

## S4. Reported results

| Experiment | ROC-AUC | PR-AUC | F1 | Recall@10 | MRR | nDCG@10 |
|---|---:|---:|---:|---:|---:|---:|
| Base multilingual SBERT | 0.7031 | 0.6946 | 0.6886 | — | — | — |
| Fine-tuned SBERT 40k | 0.7666 | 0.7681 | 0.7188 | — | — | — |
| Multi-positive SBERT | — | — | — | 0.6734 | 0.7866 | 0.6629 |
| Expert-weighted memory (experimental) | — | — | — | 0.6857 | 0.7975 | 0.6789 |

The reranker improvement is +1.24 percentage points in Recall@10, +1.09 in MRR, and +1.60 in nDCG@10. It remains an experimental candidate until a larger independent programme-level evaluation is completed.

### Classification bootstrap rerun

Using the archived `epvo-link-dataset` split, a programme-level bootstrap with 2,000 repetitions and 114 test programmes produced: ROC-AUC 0.7647 (95% CI 0.7378–0.7908), PR-AUC 0.7673 (0.7367–0.7957), F1 0.7209 (0.7032–0.7371), precision 0.6212 (0.6051–0.6378), and recall 0.8587 (0.8282–0.8846). The machine-readable files are `backend/experiment-results/epvo-sbert-finetuned-40k-ci-frozen/metrics-with-ci.json` and `predictions.jsonl`. The previously archived point estimate 0.7666 is retained as the historical benchmark record; the rerun is reported separately rather than averaged with it.

## S5. Control-plan verification

The saved Kazakhstan and international control audits produced feasible A/B/C plans with zero hard violations. The international audit intentionally does not claim GOSO compliance. The checks include total credits, semester loads, prerequisite order, domain scope, LO coverage, protected components, duplicates, and transactional commit status.

## S6. Model and software card

- Base representation: multilingual SBERT;
- fine-tuned checkpoint: `epvo-sbert-finetuned-40k`;
- training/evaluation seed: 42;
- production planner: deterministic constrained planner with repair heuristics;
- experimental ranking stage: expert-weighted memory;
- GNN/LSTM: controlled pilots, not production components;
- external LLM: optional proposal/explanation layer, not an authority for plan approval.

## S7. Limitations and required follow-up

The independent evaluation must be repeated on a larger set of newly created programmes. Confidence intervals should be reported for the primary metrics. Interface localization defects and legacy UI problems are engineering limitations and must not be presented as educational efficacy evidence. Academic experts remain responsible for the final approval of every programme.

## S8. Preliminary external-reference comparison

The current structural comparison against complete EPVO reference curricula contains seven projects: six quality-eligible cases and one negative control. The quality-eligible aggregate currently reports mean EPVO provenance 0.8046, provenance excluding protected regulatory components 0.9930, and raw semester alignment within ±1 of 0.6326. It also reports 8,857 invalid or non-comparable typical-semester rows. These values are diagnostic only: the comparison is not blinded expert evaluation and is not yet suitable as the main efficacy claim. The manuscript should report this audit as a limitation until a cleaned, larger, independent programme set is frozen.

## S9. New-programme frozen audit

A separate read-only run was executed on seven current programmes (project IDs 138–142, 116, and 117). Six passed the structural quality-eligible filter; project 117 was retained as a diagnostic unsuccessful case. The aggregate reports EPVO provenance 0.7770 (bootstrap 95% CI [0.7334, 0.8535]), provenance excluding protected regulatory components 0.9961, raw semester alignment within ±1 of 0.4671, and semantic/prerequisite-adjusted alignment of 0.5944. For the six quality-eligible programmes the corresponding values are 0.7850, 0.9955, 0.4592, and 0.5935. The new run contains 1,149 non-comparable typical-semester observations.

This is a structural comparison with complete EPVO reference curricula, not a blinded content evaluation. It supports the provenance claim while exposing the remaining semester-evidence limitation. The machine-readable report is `backend/experiment-results/external-epvo-plan-validation/report-new-20260803.json`.

## S10. Fresh transactional planner audit

The same seven programmes were regenerated with the current planner using `commit=false`; all temporary plan rows were rolled back after measurement. Six of seven cases passed the quality-eligible filter, while one was retained as a negative control with one hard violation. The aggregate reports mean provenance 0.7821, provenance excluding regulatory components 1.0000, raw semester alignment 0.4653, and semantic/prerequisite-adjusted alignment 0.5522. All seven fresh outputs had distinct schedule fingerprints. This report is `backend/experiment-results/external-epvo-plan-validation/fresh-report-20260803.json`.

## S11. Independent blinded review protocol

`TEM_BLINDED_REVIEW_PROTOCOL_EN.md` defines the sampling, anonymization, reviewer rubric, agreement statistics, and promotion rule for the remaining independent evaluation on newly generated programmes. It must be executed as a separate study before the experimental reranker is considered for production.
