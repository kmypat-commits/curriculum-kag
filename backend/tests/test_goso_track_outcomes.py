"""Mandatory outcomes follow the selected regulatory track, not its degree label."""
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from app.planner.goso import ensure_goso_learning_outcomes


@pytest.mark.parametrize('track,target,semesters,want', [
    ('profile',60,2, {'LO-GOSO-M3','LO-GOSO-M4','LO-GOSO-M5'}),
    ('scientific_pedagogical',120,4,
     {'LO-GOSO-M1','LO-GOSO-M2','LO-GOSO-M3','LO-GOSO-M4','LO-GOSO-M5'}),
])
def test_generated_regulatory_outcomes_match_applicable_track(track,target,semesters,want):
    version=SimpleNamespace(id=1,learning_outcomes=[],project=SimpleNamespace(
        constraints_json={'jurisdiction':'KZ','education_level':'master',
                          'master_track':track,'total_credits':target,'total_semesters':semesters}))
    outcomes=ensure_goso_learning_outcomes(version,MagicMock())
    assert {lo.lo_code for lo in outcomes} == want
