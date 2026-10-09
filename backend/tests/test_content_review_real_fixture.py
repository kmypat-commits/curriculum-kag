"""Frozen, source-grounded acceptance examples; labels are not academic approval."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.planner.content_evaluation import assess_course, evaluate_content

CASES = json.loads((Path(__file__).parent / 'fixtures/content_review_real_20261010.json')
                   .read_text(encoding='utf-8'))['cases']


@pytest.mark.parametrize('case', CASES, ids=[str(c['course']['id']) for c in CASES])
def test_real_source_fragments_match_reviewed_role_and_uncertainty(case):
    row = assess_course(case['profile'], SimpleNamespace(**case['course']))
    assert row['role'] == case['expected']['role'], case['rationale']
    assert row['status'] == case['expected']['status'], case['rationale']
    if row['status'] in ('needs_review', 'insufficient_data', 'supporting', 'regulatory'):
        assert row['priority_adjustment'] == 0
    assert row['advisory'] is True


@pytest.mark.parametrize('ids', [(517, 734), (1813, 5071)])
def test_real_distinct_languages_and_levels_are_not_duplicate_suggestions(ids):
    courses = [SimpleNamespace(**c['course']) for c in CASES if c['course']['id'] in ids]
    result = evaluate_content(profile={'title': 'Мировая экономика'}, courses=courses,
        schedule={}, content_vectors={cid: {'model': 'same-test-model', 'vector': [1, 0]} for cid in ids})
    assert result['duplicate_groups'] == []
