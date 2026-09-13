import copy

from scripts.score_expert_rubric import score_review
from scripts.merge_expert_rubric_reviews import merge_reviews
from scripts.prepare_expert_rubric_packets import build_packets


def test_expert_rubric_reports_separate_validity_and_agreement():
    report = score_review({"items": [
        {"anonymous_plan_id": "P-001",
         "expert_a": {"relevance": 4, "semester": 5, "bridge": 3},
         "expert_b": {"relevance": 4, "semester": 4, "bridge": 3},
         "software_validity": {"expert_a": True, "expert_b": True},
         "content_validity": {"expert_a": True, "expert_b": False}},
    ]})
    assert report["dimensions"]["relevance"]["cohens_kappa"] == 1.0
    assert report["software_validity"]["expert_a_pass_rate"] == 1.0
    assert report["content_validity"]["expert_b_pass_rate"] == 0.0
    assert report["software_validity"]["exact_agreement"] == 1.0
    assert report["content_validity"]["exact_agreement"] == 0.0
    assert report["content_validity"]["cohens_kappa"] == 0.0


def test_expert_rubric_rejects_duplicate_or_non_blind_input_ids():
    item = {"anonymous_plan_id": "P-001",
            "expert_a": {"relevance": 4, "semester": 4, "bridge": 4},
            "expert_b": {"relevance": 4, "semester": 4, "bridge": 4},
            "software_validity": {"expert_a": True, "expert_b": True},
            "content_validity": {"expert_a": True, "expert_b": True}}
    try:
        score_review({"items": [item, {**item}]})
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate anonymous IDs must be rejected")


def test_expert_rubric_requires_boolean_validity_flags():
    item = {"anonymous_plan_id": "P-002",
            "expert_a": {"relevance": 4, "semester": 4, "bridge": 4},
            "expert_b": {"relevance": 4, "semester": 4, "bridge": 4},
            "software_validity": {"expert_a": "false", "expert_b": True},
            "content_validity": {"expert_a": True, "expert_b": True}}
    try:
        score_review({"items": [item]})
    except ValueError as exc:
        assert "boolean" in str(exc)
    else:
        raise AssertionError("string validity flags must be rejected")


def test_blinded_packets_exclude_internal_generation_details_and_merge_reviews():
    variant = {
        "credits": 60,
        "semester_loads": {"1": 30, "2": 30},
        "schedule_fingerprint": [[1, "Research methods", 30], [2, "Thesis seminar", 30]],
        "bridge_titles": ["Bridge module"],
        "prerequisite_pairs": [{
            "prerequisite_title": "Research methods", "prerequisite_semester": 1,
            "course_title": "Thesis seminar", "course_semester": 2,
        }],
    }
    cohort = {"status": "passed", "reports": [{
        "passed": True, "cohort_index": 7, "temporary_project_id": 42,
        "temporary_version_id": 84, "level": "master", "jurisdiction": "KZ",
        "profile": "internal-only", "scope": {"direction": "7M061", "group": "M094"},
        "variants": {"A": variant, "B": variant, "C": variant},
        "match_diagnostics": {"must_not": "leave packet"},
    }]}
    packet, controller = build_packets(cohort, "controller-secret")
    item = packet["items"][0]
    assert item["anonymous_plan_id"].startswith("P-")
    assert "profile" not in item["programme_context"]
    assert "match_diagnostics" not in str(packet)
    assert controller["items"][0]["temporary_project_id"] == 42

    expert_a = {**copy.deepcopy(packet), "reviewer": "expert-a"}
    expert_b = {**copy.deepcopy(packet), "reviewer": "expert-b"}
    for payload, rating in ((expert_a, 4), (expert_b, 5)):
        assessment = payload["items"][0]["assessment"]
        assessment.update({"relevance": rating, "semester": rating, "bridge": rating,
                           "software_validity": True, "content_validity": True})
    merged = merge_reviews(expert_a, expert_b)
    assert merged["items"][0]["expert_a"]["relevance"] == 4
    assert merged["items"][0]["expert_b"]["relevance"] == 5


def test_blinded_packets_reject_running_cohort():
    try:
        build_packets({"status": "running", "reports": []}, "controller-secret")
    except ValueError as exc:
        assert "before the cohort has passed" in str(exc)
    else:
        raise AssertionError("running cohort must not be issued to reviewers")
