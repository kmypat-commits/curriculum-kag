from app.planner.variant_replacements import apply_confirmed_variant_replacements


def test_confirmed_replacements_pass_protected_bridges_by_keyword():
    calls = []

    def replacement_stage(items, *, protected_bridge_ids):
        calls.append(protected_bridge_ids)
        return items

    result = apply_confirmed_variant_replacements(
        [{"bridge_module_id": 11, "credits": 3}],
        {"confirmed_bridge_replacements": {"11": "42"}},
        {},
        {},
        8,
        replacement_stage,
    )

    assert calls == [{11}]
    assert result[0]["bridge_module_id"] == 11
