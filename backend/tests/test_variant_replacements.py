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


def test_variant_strategy_calls_partially_bound_bridge_stage_by_keyword():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "planner" / "variant_strategy.py").read_text(encoding="utf-8")
    assert "replace_redundant_bridge(result, None)" not in source
    assert source.count("replace_redundant_bridge(result, protected_bridge_ids=None)") == 2
