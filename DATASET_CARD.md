---
pretty_name: Curriculum Expert Evidence Repository
language:
- ru
- kk
- en
task_categories:
- sentence-similarity
- text-ranking
license: other
---

# Curriculum Expert Evidence Repository (CEER)

CEER is a provenance-preserving research representation of educational-programme structures, multilingual course cards, learning outcomes and graded course–learning-outcome evidence.

## Verified baseline

| Item | Value |
|---|---:|
| Approved multilingual course cards | 26,696 |
| Normalized expert evidence links | 932,483 |
| Source expert evaluations/pairs | 935,151 |
| Languages | Russian, Kazakh, English |
| Expert labels | 0, 0.5, 1 and aggregated intermediate values |
| Split policy | programme-level, non-overlapping train/validation/test |

Exact release counts, SHA-256 checksums and schema version must be generated at export time and take precedence over this baseline.

## Intended uses

- course–learning-outcome retrieval and ranking;
- curriculum-design research;
- multilingual educational NLP;
- reproducible evaluation of expert-evidence models;
- institutional experiments after local legal and academic review.

## Not intended for

- automatic accreditation or regulatory approval;
- evaluation of individual students or teachers;
- unreviewed replacement of academic experts;
- inference about a person or institution beyond the published records.

## Provenance and naming

CEER is a neutral research-artefact name. Each distributable record must retain a `source_system`, `source_record_id`, extraction timestamp, normalization version and checksum where legally permitted. Renaming the research dataset must not erase source provenance.

The source-code Apache-2.0 license does not grant permission to redistribute source-platform records. Until redistribution rights are documented, the public dataset release must contain only a reviewed, non-personal demonstration subset and derived aggregate evidence.

## Required release files

```text
README.md
dataset_infos.json
dataset_passport.json
programmes.parquet
courses.parquet
learning_outcomes.parquet
course_lo_evidence.parquet
prerequisites.parquet
checksums.sha256
LICENSE_DATA.txt
```

## Limitations

Historical expert evidence reflects the programmes, terminology, disciplines and review practices represented in the source period. It does not guarantee current regulatory compliance, pedagogical quality or transfer to an unseen field. Draft machine translations must remain labelled as drafts and must not be presented as expert-verified translations.
