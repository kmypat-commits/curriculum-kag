# Independent blinded review protocol for Curriculum-KAG

This protocol is prepared for the remaining external validation step. It is intentionally separate from the computational benchmark: the reviewer must judge the curriculum content without seeing AI scores, EPVO scores, model names, or the planner's ranking rationale.

## Sampling

1. Freeze a new EPVO snapshot and record its SHA-256 checksum.
2. Generate one plan per programme for at least 30 programmes that were not used in model training, threshold selection, or the previous seven-programme audit.
3. Stratify the sample by education level (bachelor, master, doctorate), domain, and programme type (Kazakhstan GOSO and international profile).
4. Assign an opaque review identifier and remove institution names, model scores, bridge labels, and provenance fields from the reviewer copy.
5. Preserve the original generated plan and the blinded copy so that disagreements can be traced after the review is locked.

## Reviewer rubric

Each reviewer independently scores every plan on a 1–5 scale:

| Dimension | Question |
|---|---|
| LO alignment | Does each selected course substantively support at least one stated learning outcome? |
| Level appropriateness | Is the course suitable for the programme's bachelor/master/doctorate level? |
| Sequence | Are prerequisites and semester placement academically sensible? |
| Domain relevance | Do the courses match the selected direction and interdisciplinary scope? |
| Workload | Are credits and semester loads realistic? |
| Regulatory completeness | Are mandatory national components present and protected when applicable? |
| Overall acceptability | Would the reviewer approve the plan as a starting point for formal curriculum development? |

Reviewers must also mark binary defects: missing LO coverage, duplicate courses, an impossible prerequisite, an incorrect education level, a regulatory omission, or a clearly irrelevant course. Free-text rationale is required for every score of 1 or 2.

## Analysis plan

- Report mean and median score with bootstrap 95% confidence intervals at the programme level.
- Report the proportion of plans without each binary defect.
- Compute Cohen's kappa for binary defects and weighted kappa or Krippendorff's alpha for ordinal scores.
- Compare the blinded human score with the automated structural audit, but do not treat correlation as proof of validity.
- Pre-register exclusion rules; do not remove a difficult programme after seeing its score.
- Keep the reranker disabled during this validation so the production candidate and experimental branch remain distinguishable.

## Acceptance rule

The study should report results rather than use a hidden pass/fail threshold. A practical promotion decision may require: (i) no regulatory omissions in Kazakhstan plans, (ii) at least 90% of plans without a hard structural defect, and (iii) a median overall acceptability of at least 4/5 with reviewer agreement reported. Any promotion of the reranker must be based on this independent result and a new frozen benchmark, not on the historical ranking gain alone.
