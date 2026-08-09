# Curriculum-KAG

**Evidence-constrained curriculum design for classical and interdisciplinary higher-education programmes.**

Curriculum-KAG converts a programme idea, education level, subject fields and learning outcomes into one or three explainable curriculum alternatives. It combines Knowledge-Augmented Generation (KAG), multilingual Sentence-BERT retrieval, expert evidence, prerequisite graphs, credit and semester constraints, and independent verification.

The system is not a thin wrapper around a generative API. Its core planning and verification pipeline works deterministically; an external LLM is optional and is used only for bounded suggestions and explanations.

Русская документация: [QUICKSTART.md](QUICKSTART.md) · [USER_GUIDE_RU.md](USER_GUIDE_RU.md)

## Research foundation

The public research dataset is called **Curriculum Expert Evidence Repository (CEER)**. CEER is a provenance-preserving research representation of curriculum records and historical expert course–learning-outcome evidence. The name separates the research artefact from any source platform or public authority.

The reproducible baseline contains:

- 21,525+ approved multilingual course cards;
- 932,483 normalized course–learning-outcome evidence links;
- Russian, Kazakh and English localization layers;
- programme-level train/validation/test partitions;
- graded expert evidence rather than a single synthetic binary label.

Source provenance is retained in the Dataset Card. Publication of code does **not** imply that every source record may be redistributed. The full dataset and trained model are versioned separately from the application.

## What the system does

- creates bachelor’s, master’s and doctoral curricula;
- supports conventional and two-field interdisciplinary programmes;
- proposes one plan or distinct A/B/C alternatives;
- selects courses against programme learning outcomes;
- respects education level, field, programme group and course provenance;
- balances exact programme credits and semester workload;
- builds and verifies prerequisite relationships;
- protects applicable SCES/GOSO RK regulatory components;
- exposes evidence and selection rationale for expert review;
- records expert confirmation, weak association or rejection;
- visualizes learning trajectories and course connections.

## Architecture

```text
React UI
   │
FastAPI application
   ├── KAG retrieval: SBERT + lexical evidence
   ├── constrained curriculum planner + repair pipeline
   ├── independent plan verifier
   ├── prerequisite and learning-outcome graph
   └── optional bounded LLM assistance
   │
PostgreSQL 16 + pgvector
   ├── application data
   ├── CEER normalized evidence
   └── expert feedback and audit trail
```

## Quick start on Windows

Requirements: Docker Desktop, PowerShell, Python 3.12 and Node.js 18+.

```powershell
git clone https://github.com/kmypat-commits/curriculum-kag.git
cd curriculum-kag
Copy-Item .env.example .env
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -Database postgres
```

Open <http://localhost:3001>. Health diagnostics are available at <http://localhost:8000/health>.

The source repository does not contain the full database or model weights. Until public artefact URLs are released, use the demo profile or provide locally authorized artefacts according to [docs/PUBLIC_RELEASE_ARCHITECTURE_RU.md](docs/PUBLIC_RELEASE_ARCHITECTURE_RU.md).

## Verification

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\test.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\smoke-test.ps1
```

The test gate checks source encoding, planner invariants, localization, course–LO evidence, prerequisites, GOSO isolation and structured AI fallbacks.

## Public artefacts

The academic release is intentionally split into independent, citable artefacts:

1. **GitHub repository** — source code, migrations, tests and documentation.
2. **Hugging Face model repository** — production SBERT weights and Model Card.
3. **Hugging Face dataset repository** — distributable CEER tables and Dataset Card.
4. **Hugging Face Docker Space** — demonstration application.
5. **PostgreSQL deployment** — mutable institutional data and user projects.

See [PUBLICATION_CHECKLIST.md](PUBLICATION_CHECKLIST.md) before publishing any release.

## Responsible use

Curriculum-KAG is a decision-support system. It does not replace academic councils, programme developers, professional experts, regulators or accreditation bodies. Generated plans must be reviewed against the institution’s current legal, professional and educational requirements.

## License

Application source code is licensed under the [Apache License 2.0](LICENSE). Model weights, datasets and third-party materials may have separate licenses stated in their own cards. No rights to redistribute source-platform records are granted by the source-code license.

## Citation

The formal citation and DOI will be added after the accompanying article and public artefacts are deposited. Until then, cite the repository version and Git commit hash used in the experiment.
