# Changelog

All notable changes to Curriculum-KAG will be documented in this file. The format follows Keep a Changelog and semantic versioning.

## [Unreleased]

### Added

- reproducible 17.08.2026 baseline report: verified backup, A/B/C audit and RU/KK/EN repository audit;
- deterministic variant ranking and atomic bundle-assembly primitives;
- PostgreSQL-backed plan-build progress snapshots, atomic per-version build claims and planner router contract tests;
- Alembic migration `20260817_plan_build_status`, applied automatically before a PostgreSQL backend starts locally or in Docker;
- strict persisted-plan quality audit: missing admission evidence now fails the audit instead of being treated as a pass;
- versioned persisted metrics: API responses flag legacy plan metrics instead of presenting them as current-validator results;
- Plan Builder explains when an older plan must be rebuilt before its quality summary can be trusted.
- Plan Builder loads detailed course-selection evidence on demand, reducing the baseline A/B/C payload for a measured plan from 980 KB to 199 KB.
- a jurisdiction-independent final rejection rule: a plan with a hard violation or an LO lacking real-course evidence can never replace a previous variant.
- partial A/B/C rebuilds now retain unrequested variants while guaranteeing exactly one active variant.
- persisted plans without current admission evidence are explicitly marked for rebuild in Plan Builder instead of being presented as current quality results.
- local frontend proxy now listens on IPv4 and IPv6 loopback, removing the Windows `localhost` IPv6 fallback delay without exposing the service to the network.
- dependency-free read-only core API smoke: checks build status, variants, evaluation and graph with a latency budget; provider-backed AI analysis is explicit opt-in.
- CI gate ensuring Docker and local dependency profiles use identical versions for every shared package.
- disk-cleanup manifest now protects the runtime model and frozen reproducibility candidates before suggesting archive operations.
- CEER public research identity, Dataset Card and Model Card;
- academic publication and release hygiene checks;
- Apache-2.0 source license, security and contribution policies;
- production React container and Caddy routing;
- explicit separation of source code, model weights and dataset artefacts.

### Changed

- course selection split into candidate retrieval, variant strategy and bridge creation modules behind a stable facade;
- planner course policies and admission audit extracted from the monolithic scheduler;
- prerequisite inference and plan metrics extracted into independently testable planner modules;
- deterministic bridge suggestions extracted from the API module;
- syllabus and evidence-bundle endpoints extracted into a dedicated API router without URL changes;
- planner API split into graph, build, coverage and replacement routers behind one stable facade;
- curriculum scheduling split into course selection, semester repair and credit balancing phases;
- reusable PlanBuilder presentation utilities and disclosure component extracted;
- long-running plan-build progress extracted into a reusable frontend component;
- PlanBuilder quality, bridge replacement and LO coverage panels extracted as reusable components;
- public UI references the expert repository/CEER while internal legacy identifiers remain compatible.

### Verified

- backend regression gate: 53/53;
- frontend production build;
- production Compose configuration;
- source encoding and public-release structure.
- local launch health checks and baseline API latency (`/projects`: 19 ms; `/repository/stats`: 73 ms on SQLite).
- read-only local API profiler (`backend/scripts/profile_local_api.py`) for separating browser and backend latency.
- local and Docker dependency manifests now pin the verified bcrypt and python-docx versions.
- CEER Dataset and Model Cards reconciled with frozen artifact counts and ranking metrics.
