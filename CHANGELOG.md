# Changelog

All notable changes to Curriculum-KAG will be documented in this file. The format follows Keep a Changelog and semantic versioning.

## [Unreleased]

### Added

- CEER public research identity, Dataset Card and Model Card;
- academic publication and release hygiene checks;
- Apache-2.0 source license, security and contribution policies;
- production React container and Caddy routing;
- explicit separation of source code, model weights and dataset artefacts.

### Changed

- planner course policies and admission audit extracted from the monolithic scheduler;
- prerequisite inference and plan metrics extracted into independently testable planner modules;
- deterministic bridge suggestions extracted from the API module;
- syllabus and evidence-bundle endpoints extracted into a dedicated API router without URL changes;
- reusable PlanBuilder presentation utilities and disclosure component extracted;
- long-running plan-build progress extracted into a reusable frontend component;
- public UI references the expert repository/CEER while internal legacy identifiers remain compatible.

### Verified

- backend regression gate: 38/38;
- frontend production build;
- production Compose configuration;
- source encoding and public-release structure.
