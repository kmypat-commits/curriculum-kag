# Modular architecture

Curriculum-KAG separates HTTP orchestration, curriculum optimisation and UI presentation so that each scientific and product concern can be tested independently.

## Planner API

The public `/planner` contract is composed in `backend/app/api/planner.py` from feature routers:

- `planner_graph.py` — prerequisite graph, semester competencies and AI semester insight;
- `planner_build.py` — transactional plan generation, progress, recomputation and activation;
- `planner_coverage.py` — variants, LO evidence and evaluation reports;
- `planner_replacements.py` — bridge/course replacement and expert decisions;
- `planner_syllabus.py` — syllabus drafts, export and evidence bundles;
- `planner_state.py` — durable progress state and atomic per-version build claim.

Existing URLs remain unchanged. Build progress is persisted in PostgreSQL, with a
small in-process fallback only for local recovery. A row lock prevents two API
workers from starting the same plan build; polling resumes after a restart.

## Curriculum planner

Course selection is split behind the stable `course_selection.py` facade:
`candidate_retrieval.py` retrieves and filters scoped courses,
`variant_admission.py` applies the pure education-level/domain/evidence gate,
`variant_ranking.py` owns deterministic candidate ordering,
`variant_prerequisites.py` filters evidenced earlier edges and computes depth,
`variant_assembly.py` owns prerequisite bundles, `variant_strategy.py` builds
deterministic A/B/C variants, and
`bridge_creation.py` owns bridge and credit-gap construction.

Plan-build progress is persisted in PostgreSQL table `plan_build_status`, so a
polling client can resume after an API restart without committing the caller's
plan transaction. Alembic migration `20260817_plan_build_status` creates the
table and its lookup index; `start.ps1` and Docker run `alembic upgrade head`
before they start the backend.

`backend/app/planner/scheduler.py` is now the orchestration facade. Its computational phases are:

- `course_selection.py` — constrained candidate selection, variants A/B/C and bridge creation;
- `semester_repair.py` — compatibility facade for semester-repair responsibilities;
- `semester_load_repair.py` — credit/load balancing and bounded bridge adjustments;
- `semester_domain_repair.py` — domain quota repair;
- `semester_appropriateness.py` — pedagogical semester suitability;
- `semester_admission_repair.py` — final evidence, education-level, prerequisite and late-course admission repair;
- `credit_balancing.py` — semester loads, total-credit repair and bounded bridge balancing;
- `prerequisite_inference.py` — plan-local prerequisite inference;
- `plan_metrics.py` — final verification and research-facing metrics.

Private compatibility aliases remain exported by `scheduler.py` for existing audit scripts and regression tests.

## Frontend

`PlanBuilder.jsx` remains the stateful page controller. Presentation is split into:

- `PlanQualityPanel.jsx` — plan verification and expert review controls;
- `BridgeReplacementPanel.jsx` — real-course and AI bridge replacement workflow;
- `LoCoveragePanel.jsx` — explainable LO-to-course evidence;
- `PlanBuildProgress.jsx` — long-running build progress.

This is a transitional container/presentation design. A later phase may move API state into dedicated React hooks without changing these panel contracts.

## Verification gates

Every structural extraction must pass:

1. Python compile/import checks;
2. backend regression suite;
3. frontend production build;
4. OpenAPI route-preservation check;
5. PostgreSQL runtime smoke-test.

`backend/tests/test_planner_router_contracts.py` protects the composed route
contract for build, coverage, graph, replacement, and syllabus routers.
It also covers ranking/assembly/prerequisite primitives and protects the duplicate-build fallback: a temporary status-store outage
must not permit a second build for the same version in one worker.

For an initial non-generative latency baseline, run
`backend/scripts/profile_local_api.py` after authentication. It measures health,
project list and repository statistics, and reports the backend `Server-Timing`
header separately from browser rendering time.

`/planner/{version}/variants` deliberately excludes detailed course–LO
explanations and in-plan prerequisite lists by default. The Plan Builder
requests them only when the user enables detailed selection reasons. This keeps
the initial A/B/C response small without removing explainability.

Persisted plan metrics carry `metrics_schema_version`. API consumers receive
`metrics_current`; a false value means the plan must be previewed or refreshed
with `recalculate_plan_metrics.py` before its quality summary is relied upon.

For an authenticated HTTP check against a dedicated PostgreSQL database, run
`backend/tests/run_postgres_endpoint_contracts.py` with
`CURRICULUM_KAG_TEST_DATABASE_URL` set to a database name ending in `_test`.
