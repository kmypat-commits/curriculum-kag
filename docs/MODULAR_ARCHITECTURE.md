# Modular architecture

Curriculum-KAG separates HTTP orchestration, curriculum optimisation and UI presentation so that each scientific and product concern can be tested independently.

## Planner API

The public `/planner` contract is composed in `backend/app/api/planner.py` from feature routers:

- `planner_graph.py` — prerequisite graph, semester competencies and AI semester insight;
- `planner_build.py` — transactional plan generation, progress, recomputation and activation;
- `planner_coverage.py` — variants, LO evidence and evaluation reports;
- `planner_replacements.py` — bridge/course replacement and expert decisions;
- `planner_syllabus.py` — syllabus drafts, export and evidence bundles;
- `planner_state.py` — transitional single-worker build progress state.

Existing URLs remain unchanged. Build progress is intentionally isolated behind `planner_state.py` so it can later be moved to PostgreSQL or Redis without changing endpoint code.

## Curriculum planner

`backend/app/planner/scheduler.py` is now the orchestration facade. Its computational phases are:

- `course_selection.py` — constrained candidate selection, variants A/B/C and bridge creation;
- `semester_repair.py` — semester placement, domain/admission repair and schedule construction;
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
