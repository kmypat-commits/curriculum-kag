# Unified Curriculum Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assemble a verified curriculum by selecting whole real-course prerequisite chains and assigning semesters in one feasibility model, without late repairs silently invalidating LO coverage.

**Architecture:** Keep existing retrieval, MatchScore/EPVO provenance, ГОСО rules and independent verifier. Build a deterministic candidate frontier, solve course selection and semester placement jointly with SciPy MILP, and publish only after the current independent boundary audit and verifier accept the actual result. A bounded frontier or timeout is an explicit non-publication state, never a claim of global infeasibility.

**Tech Stack:** Python, SQLAlchemy/PostgreSQL, NumPy, SciPy `milp`, pytest; existing `backend/scripts/audit_quality_cohort.py` and independent curriculum checks.

**Spec:** `docs/superpowers/specs/2026-09-25-unified-curriculum-planner-design.md`

## Global Constraints

- Keep the frozen inputs in `D:\curriculum-kag\output\tem-revision-20260922\real-cohort-inputs-v2\manifest.json` and their SHA256 unchanged; first run offset 0/count 20/variant A, then offset 20/count 40 only after independent 20/20 acceptance.
- Do not change verifier thresholds, ГОСО definitions, catalogue evidence, semester windows, domain quotas or input identities to improve the pass count.
- The last first-20 report is 16 passed/4 failed (`21992`, `15705`, `20787`, `14547`); a new report must have a new filename and preserve the old report.
- Preserve the previously active plan on timeout, infeasibility, verifier disagreement, or any exception. Do not claim independent expert evaluation from an internal gate.
- Catalogue candidates and prerequisite chains are real, admissible course records; no fictitious discipline fills an LO or a credit gap in this cohort.
- Variant A is the default; optional B/C use the same hard constraints. Solver order and output evidence must be reproducible.

## Review Focus

1. A high-scoring general foundation removed by ГОСО must not be the sole source of LO coverage: Task 2's duplicate-before-coverage test.
2. An otherwise strong course whose prerequisite is missing or too late must be selected with its whole admissible chain or rejected: Tasks 2–3's chain tests.
3. A selected set that cannot fit semester windows must be replaced by a feasible alternative, not scheduled outside the windows: Task 3's alternative-set test.
4. A timeout or truncated frontier must leave the active plan unchanged and must not be labelled globally infeasible: Task 4's status/publication tests.
5. Internal 20/20 without exact input identity, file/canonical hashes, valid credits and prerequisite order must not unlock the next 40: Task 5's independent audit test.

## File map and interfaces

- Create `backend/app/planner/joint_contract.py`: frozen dataclasses `Candidate`, `PlanningProblem`, `PlanningResult` and a typed `PlanningFailure(RuntimeError)` with `status` and `details`. No database calls.
- Create `backend/app/planner/joint_frontier.py`: `build_joint_frontier(version, db, *, limit: int) -> PlanningProblem`; reuse existing admission, ГОСО, semester and MatchScore evidence policies. Return explicit exclusion diagnostics.
- Create `backend/app/planner/joint_solver.py`: `solve_joint(problem: PlanningProblem, *, time_limit_seconds: float, forbidden_sets: tuple[frozenset[int], ...] = ()) -> PlanningResult`; raise `PlanningFailure` on no result. No database calls or persistence.
- Create `backend/app/planner/joint_planner.py`: `build_verified_joint_schedule(version, db, variant_type, forbidden_sets=()) -> tuple[dict[int, list[dict]], dict]`; widen the frontier, call the solver and independent verifier, record timing/evidence; raise `PlanningFailure` on no verified solution.
- Modify `backend/app/planner/scheduler.py` and `backend/app/api/planner_build.py`: route normal generation through the joint planner and existing publication boundary; pass A's selected IDs as the diversity reference for B/C, and map typed failures to honest job status. Retain legacy selection only for explicit diagnostic comparison, not silent fallback.
- Modify `backend/app/planner/goso.py` and, where needed, `backend/app/planner/verifier.py` to share pure duplicate/domain-credit policy rather than maintaining conflicting definitions.
- Extend `backend/scripts/audit_real_cohort_evidence.py` with a general slice audit while retaining the existing 50+30 `audit` entrypoint for historical results.
- Add `backend/tests/test_joint_frontier.py`, `backend/tests/test_joint_solver.py`, `backend/tests/test_joint_planner_publication.py`, and `backend/tests/test_real_cohort_slices.py`.

### Task 1: Shared verifier parity contract

**Files:** Modify `backend/app/planner/verifier.py`, `backend/app/planner/goso.py`; create `backend/app/planner/joint_contract.py`; test `backend/tests/test_joint_frontier.py`.

**Interfaces:** Produce `Candidate(course_id, item, allowed_semesters, prerequisites, lo_scores, domain_shares, utility)`, `PlanningProblem(candidates, fixed_schedule, required_los, target_credits, credit_tolerance, min_load, max_load, domain_minima, exclusions, frontier_truncated)`, and `PlanningFailure(status, details)` as a typed exception. `PlanningProblem.candidates_by_id` is a read-only ID index. `domain_shares` and duplicate decisions must match the existing verifier/ГОСО semantics exactly.

- [ ] **Step 1: Write a failing parity test.** In `test_joint_frontier.py`, build an in-memory programme with two exact-scope EPVO courses and one broad-domain course; assert that the helper's per-course domain shares and the verifier's `domain_credits` agree for the same schedule. Assert that the general anti-corruption card is classified as redundant whenever the mandatory legal ГОСО card is present. The production change that should break this test is a difference between the shared policy and the verifier/ГОСО path.

```python
def test_duplicate_foundation_is_excluded_before_lo_accounting():
    from app.planner.goso import is_redundant_goso_foundation
    assert is_redundant_goso_foundation(
        {"course_id": 2422, "title": "Основы антикоррупционной культуры, безопасности жизнедеятельности и экологии"},
        is_kz=True, has_legal_goso=True, required_ids=set(),
    )
```

- [ ] **Step 2: Verify red.** Run `backend/venv/Scripts/python.exe -m pytest backend/tests/test_joint_frontier.py -q` from the repository root. Expected: failure because the named shared policy helper is absent; no production edit before this result.
- [ ] **Step 3: Implement the shared pure helpers.** Define the data contract in `joint_contract.py` as below. Extract the existing `merge_goso_items` duplicate predicate into `is_redundant_goso_foundation(item, *, is_kz, has_legal_goso, required_ids)` and call it both from ГОСО merge and the frontier. Extract the verifier's scoped-domain calculation into a pure helper taking course/item labels plus the primary/secondary scope strengths, and use that helper in the verifier and frontier. Keep existing tests green and preserve the same numerical contributions.

```python
@dataclass(frozen=True)
class Candidate:
    course_id: int
    item: dict
    allowed_semesters: tuple[int, ...]
    prerequisites: tuple[int, ...]
    lo_scores: dict[str, float]
    domain_shares: tuple[float, float]
    utility: float

@dataclass(frozen=True)
class PlanningProblem:
    candidates: tuple[Candidate, ...]
    fixed_schedule: dict[int, list[dict]]
    required_los: tuple[str, ...]
    target_credits: int
    credit_tolerance: int
    min_load: float
    max_load: float
    domain_minima: tuple[float, float]
    exclusions: dict[str, int]
    frontier_truncated: bool

    @property
    def candidates_by_id(self) -> dict[int, Candidate]:
        return {c.course_id: c for c in self.candidates}

class PlanningFailure(RuntimeError):
    def __init__(self, status: str, details: dict):
        super().__init__(status)
        self.status, self.details = status, details
```
- [ ] **Step 4: Verify green and regression.** Run the new tests and `backend/tests/test_goso_components.py`, `backend/tests/test_independent_curriculum_checks.py`; compare domain quota values on stored 21992/other diagnostic schedules before and after the extraction. Commit only these helpers and tests.

### Task 2: Deterministic admissible frontier

**Files:** Create `backend/app/planner/joint_frontier.py`; modify `backend/app/planner/joint_contract.py`; test `backend/tests/test_joint_frontier.py`.

**Interfaces:** Consume `ProjectVersion`, SQLAlchemy session, existing `Course`, `MatchScore`, EPVO source rows and the shared Task 1 policy. Produce `PlanningProblem` plus exclusion counts; never fabricate or mutate catalogue records.

- [ ] **Step 1: Write a failing frontier test.** Use the same fixed candidate IDs and ON1 evidence pattern as programme 21992: 2422 has raw score `0.78` but duplicates ГОСО, 33472 has raw score `0.568` and parents 31489/33539. Assert 2422 is absent, 33472 is retained only together with both parents and their recursive prerequisites, and boosted `MatchScore.score=1.0` with raw `0.453` does not count toward the `0.5` real-course threshold. Add a cycle and an out-of-level prerequisite input: both must be excluded with an exact reason, not silently shortened.

```python
assert 2422 not in {c.course_id for c in problem.candidates}
assert {33472, 31489, 33539}.issubset({c.course_id for c in problem.candidates})
assert problem.exclusions["missing_or_inadmissible_prerequisite"] == 0
assert problem.candidates_by_id[33472].lo_scores["ON1"] == 0.568
```

- [ ] **Step 2: Verify red.** Run `backend/venv/Scripts/python.exe -m pytest backend/tests/test_joint_frontier.py -q`; the asserted 21992-shaped candidate behaviour must fail against the absent joint frontier.
- [ ] **Step 3: Implement frontier assembly.** Query scored IDs plus bounded top in-scope alternatives per LO, sort by exact group/direction scope, raw/expert score and stable `course_id`, then close each candidate's prerequisite DAG using `variant_assembly.build_prerequisite_bundle`. Exclude a whole candidate when any parent is missing, cyclic, out of education level, domain-inadmissible, or has no legal semester before its child. Apply ГОСО duplicate filtering before computing coverage. Build allowed semesters with `minimum_appropriate_semester` and `foundation_max_semester`; preserve explicit source locks. Include fixed ГОСО rows and calculate domain shares with Task 1 policy. Make limit/widening explicit, e.g. 120, 240, 480, recording whether the frontier was truncated.
- [ ] **Step 4: Verify green and commit.** Run Task 2 tests plus existing `backend/tests/test_selected_lo_evidence.py` and the full backend pytest suite. Commit frontier and tests. Do not infer global infeasibility from a truncated frontier.

### Task 3: Joint course and semester MILP

**Files:** Create `backend/app/planner/joint_solver.py`; test `backend/tests/test_joint_solver.py`.

**Interfaces:** Consume only the Task 1 `PlanningProblem`, produce `PlanningResult(schedule, selected_course_ids, objective, solver_seconds)` or raise `PlanningFailure(status, details)`. No ORM, external IO or persistence.

- [ ] **Step 1: Write a failing feasible-alternative test.** Fixed ГОСО loads are 20+20 across two semesters, each term must total 30 and programme total 60. Candidate 1 is 10 credits/term 1/ON1, candidate 2 is 10 credits/term 2/ON2; candidate 3 is 10 credits/term 2/ON1 but requires candidate 4 in term 1, so selecting 2+3+4 exceeds the remaining 20-credit envelope. Assert the solver chooses 1+2, both LO covered, and returns loads 30+30. Add tests that an unselected parent rejects its child, a reversed prerequisite edge is impossible, a locked foundation never moves late, and a permitted domain share reaches the exact verifier quota.

```python
result = solve_joint(problem, time_limit_seconds=5)
assert isinstance(result, PlanningResult)
assert result.selected_course_ids == frozenset({1, 2})
assert [sum(int(i["credits"]) for i in result.schedule[s]) for s in (1, 2)] == [30, 30]
```

- [ ] **Step 2: Verify red.** Run `backend/venv/Scripts/python.exe -m pytest backend/tests/test_joint_solver.py -q`; it must fail because the joint solver is absent.
- [ ] **Step 3: Implement the feasibility model.** Define binary `x[c]` and `y[c,s]`, add `sum_s y[c,s] = x[c]`, prerequisite selection `x[child] <= x[parent]` and strict order `y[child,s] <= sum_{t<s} y[parent,t]`, fixed ГОСО credits, total and term credit bounds, per-LO real evidence coverage, domain-credit minima, and selected competency/bridge policy. Reject a candidate with no allowed semester before solving. Use SciPy `milp` with deterministic variable ordering; separate hard constraints from the preference objective. Map a time-limit result to `solver_timeout`, `status=2` to `infeasible_with_frontier`, and preserve the solver message; a non-time status-1 limit gets `solver_limit`, not a false infeasibility claim. Enforce a variant-B/C difference constraint against prior selected IDs only after A exists. Never round a fractional solution into publication.

```python
# Each sparse row is (coefficient-by-variable-index, lower, upper).
for child in problem.candidates:
    for parent_id in child.prerequisites:
        rows.append(({x[child.course_id]: 1.0, x[parent_id]: -1.0}, -np.inf, 0.0))
        for semester in child.allowed_semesters:
            coefficient = {y[child.course_id, semester]: 1.0}
            for earlier in problem.candidates_by_id[parent_id].allowed_semesters:
                if earlier < semester:
                    coefficient[y[parent_id, earlier]] = -1.0
            rows.append((coefficient, -np.inf, 0.0))
```

- [ ] **Step 4: Verify green, limits, and commit.** Add tests for timeout, no feasible selected set, deterministic repeated solve, and a candidate with no legal semester. Run all `test_joint_solver.py` tests and full backend pytest. Record exact SciPy status handling and commit.

### Task 4: Single publication boundary and failure diagnostics

**Files:** Create `backend/app/planner/joint_planner.py`; modify `backend/app/planner/scheduler.py`, `backend/app/api/planner_build.py`; test `backend/tests/test_joint_planner_publication.py`.

**Interfaces:** `build_verified_joint_schedule(version, db, variant_type, forbidden_sets=())` calls Task 2 frontier and Task 3 solver; returns a verified schedule plus metrics or raises `PlanningFailure`. `build_curriculum_plan` keeps existing parameters and adds an optional diversity reference; it calls `persist_plan_result` only for a successful verified result. The API passes A's selected IDs when B/C were requested and maps typed failures to job diagnostics.

- [ ] **Step 1: Write failing integration tests.** With a stored active plan, force `solver_timeout`, `no_solution_in_bounded_frontier`, and `verifier_rejected` and assert the active plan ID/items do not change and each distinct status is retained in job diagnostics. Add a successful case that checks `verify_curriculum_plan(...)["feasible"]` and `quality_passed` before persistence. Add a test proving variant A is generated alone by default and B/C only on request.

```python
before = active_plan_fingerprint(db, project_version_id)
with pytest.raises(PlanningFailure) as exc:
    build_curriculum_plan(project_version_id, db, "A", commit=True)
assert exc.value.status == "solver_timeout"
assert active_plan_fingerprint(db, project_version_id) == before
```

- [ ] **Step 2: Verify red.** Run `backend/venv/Scripts/python.exe -m pytest backend/tests/test_joint_planner_publication.py -q`; expected failure is the absent status/route, not a broken fixture.
- [ ] **Step 3: Integrate without a silent legacy fallback.** Use a single new route for normal A/B/C builds. Widen 120→240→480 only when the prior frontier was truncated and solver returned no solution; carry forward exact exclusion diagnostics. Call `audit_final_schedule_boundary`, `verify_curriculum_plan`, `calculate_plan_metrics`, and `build_selection_evidence_snapshot` on the unchanged solver schedule. Extract the current publication tail into one helper if needed so the old path is not copied and allowed to drift. On verifier disagreement, record the rejected fingerprint; retry with a deterministic exclusion cut up to a documented bound, then raise `PlanningFailure("verifier_rejected", details)`. Persist only after both gates pass. In `planner_build.py`, pass A's selected course IDs as a reference for optional B/C rather than passing A's schedule as a selected-course override. Catch `PlanningFailure` separately from generic exceptions, roll back, and expose its safe status/details to the build job. Keep the old active plan on every non-success, preserve `commit=False` semantics, and record frontier/input hash and timing.
- [ ] **Step 4: Verify and commit.** Run focused publication/router/job tests and full backend pytest; compare the old and new publication evidence fields. Commit integration with tests. Do not start the cohort while any old contract test is red.

### Task 5: Frozen cohort and independent release gate

**Files:** Modify `backend/scripts/audit_real_cohort_evidence.py`; test `backend/tests/test_real_cohort_slices.py`; write run evidence under ignored `.runtime/` with new names.

**Interfaces:** Add `audit_slices(reports: list[tuple[int, int, dict]], frozen: dict) -> dict` where tuples are `(offset, count, report)`. Preserve the existing `audit(first, second, frozen)` 50+30 wrapper for historical reports. Use `independent_curriculum_checks.check_variant` for actual structural assertions.

- [ ] **Step 1: Write failing independent-gate tests.** A synthetic 20-case report with 20 internal passes but one mismatched input SHA256, one repeated ID, one 25-credit term, or one reversed prerequisite must fail the release gate. Two clean disjoint slices `(0,20)` and `(20,40)` must pass identity checking. The 40 slice alone must not be marked releasable.

```python
result = audit_slices([(0, 20, first_report)], frozen)
assert result["release_40_allowed"] is False
assert any(row["reason"] == "input_hash_mismatch" for row in result["findings"])
```

- [ ] **Step 2: Verify red.** Run `backend/venv/Scripts/python.exe -m pytest backend/tests/test_real_cohort_slices.py -q`; the new slice API should be absent.
- [ ] **Step 3: Implement strict slice audit.** Match `report["reports"]` in order to `frozen["prepared"][offset:offset+count]`; verify every expected program ID, raw-file SHA256, canonical input SHA256, uniqueness and disjointness, actual total/semester credits, prerequisite order and independent variant structure. `release_40_allowed` is true only for a complete, zero-finding 20/20 first slice. Historical 50+30 audit results must remain byte-for-byte semantically comparable.
- [ ] **Step 4: Verify green and commit.** Run new slice tests and existing audit/independent checker tests, then full backend pytest. Commit the audit change.
- [ ] **Step 5: Run the four focused cases.** Reuse unchanged input files for `21992`, `15705`, `20787`, `14547` with `backend/scripts/audit_cross_level_generation.py --input-json ... --variants A --output .runtime/<new-name>.json`. Preserve each report. At a failure, stop, diagnose the general constraint/candidate cause, add a red regression, fix, rerun focused cases, and do not advance.
- [ ] **Step 6: Re-run the exact first 20 from the start.** Run `backend/scripts/audit_quality_cohort.py --real-input-manifest D:\curriculum-kag\output\tem-revision-20260922\real-cohort-inputs-v2\manifest.json --case-offset 0 --count 20 --variants A --output .runtime/<new-20-run>.json` with the existing Python environment and a new path. Check runner identity before launch; do not overwrite or resume a failed old report. If any case fails, preserve reports and repeat the fix-and-rerun cycle from all 20 inputs.
- [ ] **Step 7: Independently audit the first 20.** Use the Task 5 slice audit and inspect exact IDs, file/canonical SHA256, actual total and term credits, prerequisite edges and hard/quality gates. Do not call internal 20/20 independent academic evaluation.
- [ ] **Step 8: Only after the prior gate, run 40.** Use the same frozen manifest with `--case-offset 20 --count 40 --variants A` and a new output; independently audit `(0,20)` plus `(20,40)` before reporting combined figures. Failed real cases remain failed; no input replacement or gate weakening.

## Self-review and follow-on

The tasks cover the spec's candidate identity/closure, regulatory fixed block, joint feasibility, objective/variants, publication, status/performance evidence, and frozen-cohort sequence. Run `git diff --check`, full backend pytest and focused four-case reports before any success statement. This plan intentionally stops at reproducible engineering evidence. Revising the TEM Word manuscript and reviewer responses is a subsequent document task and may use only verified cohort numbers, with rendered visual QA; it cannot assert independent expert review without expert records.
