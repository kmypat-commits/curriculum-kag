# University baseline import implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect B/C to an explicitly mapped, methodist-confirmed immutable university source plan, never to generated A.

**Architecture:** Parse uploads into a non-publishable import draft. Explicit row mappings produce append-only confirmed revisions. Generation captures a revision ID/hash atomically before queueing and passes its resolved course IDs to the existing solver.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, PostgreSQL, Python csv/openpyxl, React, pytest/Vitest.

**Spec:** docs/ABC_STRATEGY_CONTRACT_20261013_RU.md; capture design approved directly by user13October.

## Global constraints

- Preserve published plans, protected catalogue fields, article, start.ps1 and active runtime bundle.
- No Course creation, fuzzy-name equivalence, prerequisite changes or weakening structural gates.
- A works without baseline; B/C return baseline_missing without a confirmed revision.
- Original bytes SHA256, canonical mapping SHA256, user, timestamp, project/version and content hashes are retained.
- A confirmed revision cannot be overwritten; a new import creates a new revision, explicitly selected for subsequent jobs.
- No live migrations or restarts while jobs are active. Test migration and restoration on isolated DB first.

## Review focus

1. Spreadsheet formulas, malformed archives and oversized uploads are rejected before saving a draft.
2. Repeated/ambiguous codes never silently select an arbitrary Course.id.
3. Catalogue edits between preview and confirmation cause mapping_stale, not silent remapping.
4. Another project's revision cannot be read, confirmed or used for a job.
5. Worker retries use the captured immutable revision, not the newest revision.

## Task1: source parsing and explicit mapping contract

Create backend/app/services/university_baseline_import.py and backend/tests/test_university_baseline_import.py.

Interfaces: parse_source(data:bytes, filename:str)->list[dict]; validate_mapping(rows:list[dict], mappings:dict[int,int], catalogue:dict[int,dict])->list[dict]; canonical_hash(rows:list[dict])->str.
Rows carry source_row, original_code, original_title, credits. Resolved rows additionally carry course_id and content_sha256. Repeated source lines are retained in provenance; solver IDs are deduplicated only after confirmation.

- [ ] Write RED cases for UTF8 CSV/XLSX equivalent values, missing columns, nonpositive/nonfinite credits, empty file, >10MiB, >5000rows, formulas, duplicate row mapping, nonexistent IDs and unresolved mappings.
```python
def test_unresolved_mapping_cannot_confirm():
    with pytest.raises(ValueError, match='mapping_unresolved'):
        validate_mapping([{'source_row': 2, 'original_code': 'X', 'original_title': 'Course', 'credits': 5}], {}, {})
```
- [ ] Run backend/venv/Scripts/python.exe -m pytest backend/tests/test_university_baseline_import.py -q; verify assertion failure before implementation.
- [ ] Implement parsing without evaluating formulas (XLSX data_only=False); reject formula cells, accept only code/title/credits column mapping explicitly supplied by caller. Exact codes provide suggestions, never confirmation.
- [ ] Verify GREEN and full backend suite with a unique TEMP directory; commit only this service and tests.

## Task2: durable drafts and append-only confirmed revisions

Create backend/app/models/university_baseline.py, backend/app/services/university_baseline.py, backend/tests/test_university_baseline_store.py and backend/migrations/versions/20261013_0012_university_baselines.py; register model in backend/app/models/__init__.py.

Tables: university_baseline_imports(id,project_version_id,created_by,source_name,source_sha256,source_bytes,rows_json,mapping_json,status,created_at); university_baseline_revisions(id,project_version_id,import_id,revision_number,confirmed_by,confirmed_at,source_sha256,canonical_sha256,resolved_rows_json). Unique(project_version_id,revision_number), Unique(import_id). Confirmed revisions have no update/delete API.

Interfaces: confirm_import(db, import_id:int, user_id:int)->revision; load_revision(db, project_version_id:int, revision_id:int)->revision. Confirmation rechecks current course hashes and complete mapping inside one transaction; uses project-version locking for revision allocation. Repeated same confirmation returns the same revision.

- [ ] RED tests: concurrent confirmation produces one revision; old revisions unchanged after new import; stale course hash rejects; empty composition rejects; rollback preserves prior revision.
```python
def test_catalogue_change_rejects_confirmation(baseline_fixture):
    baseline_fixture.change_course_description()
    with pytest.raises(ValueError, match='mapping_stale'):
        confirm_import(baseline_fixture.db, baseline_fixture.import_id, baseline_fixture.user_id)
```
- [ ] Implement tables/service and migration following current migration safety patterns; down_revision=20260914_planner_build_drafts.
- [ ] Run focused/full backend and isolated PostgreSQL upgrade, concurrent confirmation and rollback tests. Do not migrate live in this task; commit after verified results.

## Task3: owner API and generation snapshot integration

Create backend/app/api/planner_baseline.py, backend/app/schemas/university_baseline.py, backend/tests/test_university_baseline_api.py. Modify backend/app/api/planner.py, planner_build.py, planner_state.py and backend/app/planner/joint_planner.py at the existing build boundary, not solver constraints.

Routes under /planner/{project_version_id}/baseline: POST/import (file+column mapping), PATCH/imports/{id}/mapping (explicit source_row/course_id), POST/imports/{id}/confirm, GET/revisions, GET/revisions/{id}. Generation accepts baseline_revision_id; a job stores baseline_revision_id+canonical_sha256 in its immutable input snapshot.

- [ ] RED ownership tests reuse require_project_version_access: foreign import/revision returns404; unauthenticated401; confirm incomplete409; revision modification405.
- [ ] RED integration tests: B/C missing baseline rejects before enqueue/publication; captured revision stays identical across retry; A ignores no implicit baseline; required nonbaseline IDs stay mandatory.
```python
def test_b_does_not_enqueue_without_baseline(owner_client, version_id):
    response = owner_client.post(f'/planner/{version_id}/build', json={'variant_type': 'B'})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'baseline_missing'
```
- [ ] Implement owner checks for every import/revision lookup, capture transaction, pass tuple(sorted(unique_ids)) to PlanningProblem.baseline_course_ids for B/C; persist hash/objective evidence. Do not choose the latest revision silently.
- [ ] Run focused/full tests and actual isolated API/worker B/C control, checking published old plan survives rejected build. Commit only owned files.

## Task4: import/mapping/confirmation UI and bounded acceptance

Create frontend/src/components/UniversityBaselinePanel.jsx and its .test.jsx; frontend/src/utils/universityBaselineApi.js. Modify frontend/src/pages/PlanBuilder.jsx to show source revision selection and pass explicit baseline_revision_id.

UI: file/columns preview; row code/title/credits and explicit catalogue selection; unresolved/ambiguous rows highlighted; confirmation summary with unique course count and source hash; confirmed revisions read-only. B/C disabled with a clear missing-base reason, A available. No new animation in this task.

- [ ] RED component tests: unresolved rows block confirmation; changing mappings invalidates preview; selected confirmed revision appears in B/C request; another version's stale response cannot replace current state; keyboard labels/focus and mobile table scrolling remain usable.
```javascript
it('blocks confirmation while rows are unresolved', () => {
  render(<UniversityBaselinePanel rows={[{source_row: 2, course_id: null}]} />)
  expect(screen.getByRole('button', {name: 'Подтвердить исходный план'})).toBeDisabled()
})
```
- [ ] Implement panel/API calls with cancellation or version guards; save no baseline from generated variants.
- [ ] Run full frontend tests/build plus desktop/mobile/keyboard authenticated bounded QA. Publish a separate bundle only after no active jobs and retain rollback bundle.
- [ ] Compare A/B/C on one fixed input with a genuine confirmed source plan: coverage, added IDs, required courses, hashes and distinctness/alternative_unavailable. Do not alter frozen cohort inputs to invent a baseline; fresh20/40 still require independent structural and honest content acceptance.
- [ ] Commit/push code and factual evidence; mark each task only after its checks are verified.

## Handoff gate

Design is approved. This implementation plan requires review before execution; no model-training approval is implied. Execute locally task-by-task with TDD and an independent final code review. The overall thread goal remains open after this subsystem ships.
