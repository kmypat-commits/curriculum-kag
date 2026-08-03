# TEM Journal submission checklist

Compact upload bundle: `TEM_submission_package_2026-08.zip`.

## Manuscript files

- [x] Official TEM DOCX template used.
- [x] Full-author manuscript prepared: `Curriculum_KAG_TEM_manuscript_official_template.docx`.
- [x] Anonymous manuscript prepared for double-blind review: `Curriculum_KAG_TEM_manuscript_anonymous.docx`.
- [x] Abstract is 99 words and within TEM's 50–100-word range.
- [x] Five keywords are used.
- [x] Acknowledgement, data availability, ethics, funding, conflict-of-interest, authorship, and AI-disclosure statements are present.
- [ ] Final visual inspection in Word or LibreOffice.
- [ ] Final English language edit by a human proficient editor.
- [ ] Final plagiarism/originality check.

## Scientific evidence

- [x] Programme-level split with seed 42 documented.
- [x] Base SBERT and fine-tuned SBERT metrics documented.
- [x] Expert-weighted reranker metrics documented as experimental.
- [x] Production/experimental/future-work boundaries stated.
- [x] EPVO expert scale and provenance described.
- [x] External reference audit labelled as structural, not blinded efficacy evidence.
- [x] Preliminary read-only structural evaluation on seven current programmes (six quality-eligible, one diagnostic case).
- [x] Fresh transactional regeneration audit on the same seven programmes with rollback and distinct schedule fingerprints.
- [ ] Larger cleaned programme-level evaluation suitable as a primary efficacy claim.
- [x] Programme-level bootstrap 95% confidence intervals for the primary model metrics (2,000 repetitions, 114 test programmes).
- [x] Final cleaned comparison table generated from one frozen report: `TEM_FROZEN_RESULTS_TABLE_EN.md`.

## Files to include as supplementary material

- `TEM_SUPPLEMENTARY_MATERIALS_EN.md`;
- Dataset Passport and checksum manifest;
- `TEM_CHECKSUM_MANIFEST.json` and `tem_package_audit.json`;
- `TEM_BLINDED_REVIEW_PROTOCOL_EN.md` (protocol for the remaining independent validation);
- Model Card for `epvo-sbert-finetuned-40k`;
- frozen benchmark JSON files;
- control-programme audit reports;
- reproducibility scripts and environment lockfile.

## Submission declarations

- [ ] Confirm that no manuscript version is under simultaneous consideration elsewhere.
- [ ] Confirm all author names, affiliations, and corresponding-author details.
- [ ] Confirm permission for every reused figure, table, or external text fragment.
- [ ] Confirm current APC and payment details directly on the TEM Journal website.
- [ ] Upload the full-author file and anonymized review file according to the portal's current instructions.
