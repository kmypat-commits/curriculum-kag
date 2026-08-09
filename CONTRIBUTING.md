# Contributing to Curriculum-KAG

## Principles

1. Preserve evidence provenance and multilingual text.
2. Do not silently weaken planner or regulatory constraints.
3. Keep API routes thin; place domain logic in services.
4. Add a regression test for every corrected planner defect.
5. Never commit databases, model weights, credentials or raw restricted data.

## Local verification

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\test.ps1
git diff --check
```

For changes affecting running endpoints:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\smoke-test.ps1
```

## Pull requests

- describe the user-visible problem and the invariant being protected;
- identify affected education levels and languages;
- include before/after evidence;
- state whether database migration is required;
- do not mix generated article artefacts with application changes;
- keep refactors behaviour-preserving unless the change is explicitly tested.

## Data contributions

Every dataset contribution must include source, permission, extraction date, schema version, checksum, language status and whether the record is raw, normalized, approved or expert-verified.
