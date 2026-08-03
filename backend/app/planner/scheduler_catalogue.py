"""Catalogue-level normalization helpers used by the curriculum scheduler.

These functions are deliberately pure: they only normalize titles and remove
semantic duplicates. Keeping them outside the placement/repair pipeline makes
the large scheduler easier to test without changing generation behaviour.
"""
from __future__ import annotations

from typing import Dict, List

from app.planner.scheduler_utils import title_key as _title_key


def is_component_placeholder_title(key: str) -> bool:
    """Reject catalogue metadata accidentally imported as a course title."""
    return key in {
        "обязательный компонент",
        "компонент по выбору",
        "вузовский компонент",
        "mandatory component",
        "elective component",
        "university component",
    }


def foundation_equivalent_title_key(key: str) -> str:
    """Conservatively merge same-credit titles denoting one foundation course."""
    exact_aliases = {
        "основы программирования", "основы программирования python",
        "основы программирования на python", "введение в программирование",
        "fundamentals of programming", "introduction to programming",
    }
    if key in exact_aliases:
        return "semantic programming foundations"
    research_methodology_markers = (
        "методология исследования", "методология исследований",
        "методология научного исследования", "методология научных исследований",
        "research methodology", "methodology of research",
        "ғылыми зерттеу әдіснамасы", "зерттеу әдіснамасы",
    )
    if key in research_methodology_markers:
        return "semantic research methodology"
    if "алгоритм" in key and "структур" in key and "данн" in key:
        return "semantic algorithms and data structures"
    if "операционн" in key and ("систем" in key or "сред" in key or "оболоч" in key):
        return "semantic operating systems"
    if key in {
        "базы данных", "базы данных и информационные системы",
        "система управления базами данных", "системы баз данных",
        "database systems", "database management systems",
    }:
        return "semantic database systems"
    if key in {
        "проектный менеджмент", "управление it проектами",
        "управление ит проектами", "управление проектами",
        "project management", "it project management",
    }:
        return "semantic project management"
    for prefix in (
        "основы ", "введение в ", "введение в основы ", "базовый курс ",
        "fundamentals of ", "introduction to ", "basic course in ",
    ):
        if key.startswith(prefix):
            candidate = key[len(prefix):].strip()
            if len(candidate.split()) >= 2:
                return candidate
    return key


def unique_items_by_title(items: List[Dict]) -> List[Dict]:
    """Keep one curriculum item per title and semantic foundation family."""
    result: List[Dict] = []
    seen: set[str] = set()
    seen_semantic: set[tuple[str, int]] = set()
    for item in items:
        key = _title_key(item.get("title"))
        if is_component_placeholder_title(key):
            continue
        key = key or f"id:{item.get('course_id')}:{item.get('bridge_module_id')}"
        if key in seen:
            continue
        semantic_key = foundation_equivalent_title_key(key)
        semantic_credits = 0 if semantic_key.startswith("semantic ") else int(item.get("credits") or 0)
        semantic_identity = (semantic_key, semantic_credits)
        if semantic_key and semantic_identity in seen_semantic:
            continue
        seen.add(key)
        if semantic_key:
            seen_semantic.add(semantic_identity)
        result.append(item)
    return result
