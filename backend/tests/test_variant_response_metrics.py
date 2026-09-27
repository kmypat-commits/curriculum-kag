from copy import deepcopy


def test_summary_omits_heavy_evidence_without_mutating_persisted_metrics():
    from app.services.plan_reporting import variant_response_metrics
    metrics = {'total_credits': 240, 'verification': {'feasible': True},
               'selection_evidence_snapshot': {'courses': {'1': {'text': 'evidence'}}}}
    original = deepcopy(metrics)
    summary = variant_response_metrics(metrics, include_explanations=False)
    assert summary == {'total_credits': 240, 'verification': {'feasible': True}}
    assert metrics == original
    assert variant_response_metrics(metrics, include_explanations=True) == original
