# Academic open-source publication checklist

## Source release

- [ ] Regression suite passes.
- [ ] PostgreSQL smoke test passes.
- [ ] Frontend production build passes.
- [ ] No `.env`, token, database, backup, model or runtime file is tracked.
- [ ] Apache-2.0 copyright holder is confirmed.
- [ ] Git tag, changelog and source archive are generated.

## Model release

- [ ] Only the selected production checkpoint is uploaded.
- [ ] `model-retention-policy.json` is applied; experimental weights are archived, not silently deleted.
- [ ] Model Card matches the frozen metrics and split checksum.
- [ ] Base-model license and attribution are preserved.
- [ ] Weight SHA-256 is published.

## Dataset release

- [ ] Redistribution rights are documented.
- [ ] Personal and confidential fields are excluded.
- [ ] CEER schema and Dataset Card are published.
- [ ] Raw, normalized and approved layers are distinguishable.
- [ ] Machine translations are labelled `draft/needs_review`.
- [ ] Counts and checksums are regenerated from the released files.

## Demonstration Space

- [ ] Uses demo users and demo data only.
- [ ] Secrets are stored in Space settings.
- [ ] Resource limits and timeouts are visible to users.
- [ ] Generated plans carry the expert-review disclaimer.
- [ ] The Space links to GitHub, Model Card, Dataset Card and article.
