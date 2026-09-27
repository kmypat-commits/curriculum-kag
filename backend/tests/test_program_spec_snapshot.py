from types import SimpleNamespace

from app.services.program_spec_snapshot import build_program_spec_snapshot, program_spec_hash


def _version(outcomes):
    return SimpleNamespace(
        id=10,
        version_number=2,
        project=SimpleNamespace(
            title="Test programme",
            goal="Prepare specialists.",
            domain1="ICT",
            domain2="Medicine",
            constraints_json={"total_credits": 240, "education_level": "bachelor"},
        ),
        learning_outcomes=outcomes,
    )


def test_program_spec_hash_is_stable_when_outcome_rows_arrive_in_a_different_order():
    first = SimpleNamespace(lo_code="LO1", lo_text="Analyse", taxonomy_level="analyse", weight=1.0, order_index=1)
    second = SimpleNamespace(lo_code="LO2", lo_text="Design", taxonomy_level="create", weight=1.5, order_index=2)
    assert program_spec_hash(build_program_spec_snapshot(_version([first, second]))) == program_spec_hash(
        build_program_spec_snapshot(_version([second, first]))
    )


def test_program_spec_hash_changes_when_the_curriculum_command_changes():
    outcome = SimpleNamespace(lo_code="LO1", lo_text="Analyse", taxonomy_level="analyse", weight=1.0, order_index=1)
    baseline = build_program_spec_snapshot(_version([outcome]))
    changed = build_program_spec_snapshot(_version([outcome]))
    changed["goal"] = "Prepare research specialists."
    assert program_spec_hash(baseline) != program_spec_hash(changed)


def test_snapshot_does_not_change_when_live_optional_requirements_are_edited():
    version = _version([])
    version.project.constraints_json["curriculum_requirements"] = {
        "enabled": True, "required_course_ids": [1],
    }
    snapshot = build_program_spec_snapshot(version)
    original_hash = program_spec_hash(snapshot)
    version.project.constraints_json["curriculum_requirements"]["required_course_ids"].append(2)
    assert snapshot["constraints"]["curriculum_requirements"]["required_course_ids"] == [1]
    assert program_spec_hash(snapshot) == original_hash
