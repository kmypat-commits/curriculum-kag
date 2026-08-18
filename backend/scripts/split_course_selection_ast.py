"""Deterministically split course_selection.py without changing source bytes.

Run once from backend: python scripts/split_course_selection_ast.py --write
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


PLANNER = Path(__file__).resolve().parents[1] / "app" / "planner"
SOURCE = PLANNER / "course_selection.py"

CANDIDATE_NAMES = {
    "_repair_missing_ict_competencies",
    "_limit_general_course_items",
    "_remap_equivalent_prerequisites",
    "_normalize_selected_courses_for_quality",
    "_promote_epvo_priority_courses",
    "_select_exact_professional_subset",
    "_fit_real_professional_block_after_goso",
}
BRIDGE_NAMES = {
    "_bridge_item",
    "_force_bridge_item",
    "_ensure_foundation_capacity",
    "_trim_to_target_credits",
    "_fill_existing_bridge_credit_gap",
    "ensure_core_interdisciplinary_bridge",
    "ensure_secondary_domain_bridge_modules",
    "ensure_credit_bridge_modules",
}
VARIANT_NAMES = {"_diversify_variant_items", "select_courses_for_variant"}


def _source_segment(lines: list[str], node: ast.AST) -> str:
    return "\n".join(lines[node.lineno - 1: node.end_lineno])


def _module_source(header: str, functions: list[str], extra_imports: str = "") -> str:
    parts = [header.rstrip(), extra_imports.strip(), *functions]
    return "\n\n".join(part for part in parts if part) + "\n"


def build_split(source: str) -> dict[str, str]:
    tree = ast.parse(source)
    lines = source.splitlines()
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    expected = CANDIDATE_NAMES | BRIDGE_NAMES | VARIANT_NAMES
    missing = expected - functions.keys()
    if missing:
        raise RuntimeError(f"Expected functions are absent: {sorted(missing)}")
    first_function = min(node.lineno for node in functions.values())
    header = "\n".join(lines[:first_function - 1])

    def segments(names: set[str]) -> list[str]:
        return [_source_segment(lines, functions[name]) for name in sorted(names, key=lambda name: functions[name].lineno)]

    variant_imports = """from app.planner.bridge_creation import (
    _bridge_item,
    _ensure_foundation_capacity,
    _fill_existing_bridge_credit_gap,
    _force_bridge_item,
    _trim_to_target_credits,
)
from app.planner.candidate_retrieval import (
    _fit_real_professional_block_after_goso,
    _limit_general_course_items,
    _normalize_selected_courses_for_quality,
    _promote_epvo_priority_courses,
    _remap_equivalent_prerequisites,
    _repair_missing_ict_competencies,
    _select_exact_professional_subset,
)"""
    facade = """\"\"\"Stable imports for the modular course-selection pipeline.\"\"\"

from app.planner.bridge_creation import (
    _bridge_item, _ensure_foundation_capacity, _fill_existing_bridge_credit_gap,
    _force_bridge_item, _trim_to_target_credits, ensure_core_interdisciplinary_bridge,
    ensure_credit_bridge_modules, ensure_secondary_domain_bridge_modules,
)
from app.planner.candidate_retrieval import (
    _fit_real_professional_block_after_goso, _limit_general_course_items,
    _normalize_selected_courses_for_quality, _promote_epvo_priority_courses,
    _remap_equivalent_prerequisites, _repair_missing_ict_competencies,
    _select_exact_professional_subset,
)
from app.planner.variant_strategy import _diversify_variant_items, select_courses_for_variant
"""
    result = {
        "candidate_retrieval.py": _module_source(header, segments(CANDIDATE_NAMES)),
        "bridge_creation.py": _module_source(header, segments(BRIDGE_NAMES)),
        "variant_strategy.py": _module_source(header, segments(VARIANT_NAMES), variant_imports),
        "course_selection.py": facade,
    }
    for name, text in result.items():
        compile(text, str(PLANNER / name), "exec")
    return result


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    if "def select_courses_for_variant" not in source:
        raise RuntimeError("Run against the pre-split course_selection.py only.")
    result = build_split(source)
    if "--write" not in sys.argv:
        print("Validated split:", ", ".join(result))
        return 0
    for name, text in result.items():
        (PLANNER / name).write_text(text, encoding="utf-8", newline="\n")
    print("Written split:", ", ".join(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
