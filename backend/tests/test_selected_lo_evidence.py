from types import SimpleNamespace

from app.planner.match_aggregation import selected_real_lo_coverage


def test_selected_lo_coverage_rejects_boosted_rank_without_real_evidence():
    matches = [SimpleNamespace(
        lo_id=11, score=1.0,
        evidence_json={"semantic_score": 0.453, "epvo_expert_score": 0.0},
    )]
    assert selected_real_lo_coverage(matches, [11]) == {11: 0.453}


def test_selected_lo_coverage_accepts_independent_expert_evidence():
    matches = [SimpleNamespace(
        lo_id=11, score=0.9,
        evidence_json={"semantic_score": 0.3, "epvo_expert_score": 0.65},
    )]
    assert selected_real_lo_coverage(matches, [11]) == {11: 0.65}
