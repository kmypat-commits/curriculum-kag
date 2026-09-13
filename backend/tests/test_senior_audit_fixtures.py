"""Executable, source-controlled minimal corpus for the senior audit.

The cases intentionally use pure policy functions and never reach the shared
catalogue.  Integration/PostgreSQL cases are a separate T02 gate.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.api.planner_build import must_reject_variant
from app.planner.bridge_policy import bridge_can_close_program_lo, bridge_module_limit
from app.planner.domain_evidence import domain_label_matches
from app.planner.invariant_ledger import schedule_fingerprint
from app.planner.scheduler_prerequisites import prerequisite_concepts


CASES_PATH = Path(__file__).parent / "fixtures" / "senior_audit_cases_v1.json"


def _cases() -> dict:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def test_senior_audit_fixture_corpus_is_versioned_and_safe():
    cases = _cases()
    assert cases["schema_version"] == 1
    assert "project_version_id" not in json.dumps(cases).lower()


def test_senior_audit_policy_regressions():
    cases = _cases()
    bridge = cases["bridge_budget"]
    version = SimpleNamespace(project=SimpleNamespace(constraints_json=bridge["constraints"]))
    assert bridge_module_limit(version) == bridge["expected_limit"]

    domain = cases["domain_alias"]
    assert all(domain_label_matches(label, domain["scope"]) for label in domain["accepted"])
    assert not any(domain_label_matches(label, domain["scope"]) for label in domain["rejected"])

    variants = cases["variant_order"]
    assert schedule_fingerprint(variants["left"]) == schedule_fingerprint(variants["right"])

    credit_deficit = cases["credit_deficit"]
    assert credit_deficit["actual_credits"] < credit_deficit["target_credits"]
    assert must_reject_variant(credit_deficit["verification"])

    prerequisites = cases["prerequisite_ontology"]
    assert "security" not in prerequisite_concepts(prerequisites["occupational_safety"])
    assert "security" in prerequisite_concepts(prerequisites["cybersecurity"])

    bridge_proposal = SimpleNamespace(**cases["unapproved_bridge"])
    assert not bridge_can_close_program_lo(bridge_proposal)
