"""Stable imports for the modular course-selection pipeline."""

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
