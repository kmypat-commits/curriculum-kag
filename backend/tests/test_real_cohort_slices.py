"""Independent frozen-input identity and arithmetic gate for 20+40 runs."""

import hashlib
import json

from scripts.independent_curriculum_checks import check_variant


def _canonical(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _reports(tmp_path):
    prepared = []
    cases = []
    for number in range(3):
        payload = {"constraints": {"total_credits": 10,
                                   "max_credits_per_semester": 5,
                                   "total_semesters": 2}}
        path = tmp_path / f"programme-{number}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        canonical_hash = _canonical(payload)
        prepared.append({"program_id": str(number), "input": str(path),
                         "sha256": file_hash, "canonical_sha256": canonical_hash})
        cases.append({"program_id": str(number), "case_index": number + 1,
                      "input_sha256": canonical_hash,
                      "expected_input_sha256": canonical_hash,
                      "passed": True,
                      "variants": {"A": {"credits": 10,
                                         "semester_loads": {"1": 5, "2": 5},
                                         "schedule_fingerprint": [[1, f"A{number}", 5],
                                                                  [2, f"B{number}", 5]],
                                         "prerequisite_pairs": []}}})
    def part(rows):
        return {"completed": len(rows), "reports": rows,
                "manifest": {"cases": [
                    {"program_id": row["program_id"],
                     "input_sha256": row["input_sha256"],
                     "input_file_sha256": prepared[int(row["program_id"])]["sha256"]}
                    for row in rows
                ]}}
    return part(cases[:2]), part(cases[2:]), {"prepared": prepared}


def test_slice_audit_accepts_only_exact_ordered_frozen_inputs(tmp_path):
    from scripts.audit_real_cohort_evidence import audit_slices

    first, second, frozen = _reports(tmp_path)
    result = audit_slices(first, second, frozen,
                          first_offset=0, first_count=2,
                          second_offset=2, second_count=1)
    assert result["internal_passed"] == 3
    assert result["structural_passed"] == 3
    assert result["findings"] == []

    first["reports"].reverse()
    result = audit_slices(first, second, frozen,
                          first_offset=0, first_count=2,
                          second_offset=2, second_count=1)
    assert any(row["reason"] == "cohort_identity_mismatch"
               for row in result["findings"])


def test_slice_audit_rejects_changed_input_file(tmp_path):
    from scripts.audit_real_cohort_evidence import audit_slices

    first, second, frozen = _reports(tmp_path)
    path = tmp_path / "programme-0.json"
    path.write_text('{"constraints":{}}', encoding="utf-8")
    result = audit_slices(first, second, frozen,
                          first_offset=0, first_count=2,
                          second_offset=2, second_count=1)
    assert any(row["reason"] == "input_hash_mismatch"
               for row in result["findings"])


def test_first_slice_can_be_accepted_before_second_run_exists(tmp_path):
    from scripts.audit_real_cohort_evidence import audit_slices

    first, _second, frozen = _reports(tmp_path)
    result = audit_slices(first, {}, frozen,
                          first_offset=0, first_count=2,
                          second_offset=2, second_count=0)
    assert result["accepted"]
    assert result["requested"] == 2


def test_independent_check_detects_missing_semester_even_when_credits_add_up():
    variant = {"credits": 5, "semester_loads": {"1": 5},
               "schedule_fingerprint": [[1, "Only course", 5]],
               "prerequisite_pairs": []}
    issues = check_variant(variant, target_credits=5, min_load=0, max_load=8,
                           num_semesters=2)
    assert any(issue["reason"] == "missing_semester" for issue in issues)
