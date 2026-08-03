"""Small side-effect helpers shared by the curriculum scheduler.

Keeping list mutation primitives separate makes the large scheduling module
easier to audit without changing its scoring or placement rules.
"""
from typing import Dict, List
import re
import unicodedata


def remove_item_once(items: List[Dict], item: Dict) -> bool:
    """Remove an item only if it is still present in the source list."""
    try:
        items.remove(item)
        return True
    except ValueError:
        return False


def title_key(title: str | None) -> str:
    """Canonical title used to prevent semantic duplicate disciplines."""
    value = title or ""
    suspicious = "Ð" in value or "Ñ" in value or (
        len(value) > 6 and (value.count("Р") + value.count("С")) > len(value) / 4
    )
    if suspicious:
        for source_encoding in ("latin1", "cp1251"):
            try:
                repaired = value.encode(source_encoding).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            if repaired and repaired != value:
                value = repaired
                break
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+", value, flags=re.UNICODE))


def schedule_loads(schedule: Dict[int, List[Dict]]) -> Dict[int, int]:
    """Return credit load per semester without mutating the schedule."""
    return {
        semester: sum(int(item.get("credits") or 0) for item in items)
        for semester, items in schedule.items()
    }


def semester_by_course(schedule: Dict[int, List[Dict]]) -> Dict[int, int]:
    """Map each real course id to its current semester."""
    return {
        item["course_id"]: semester
        for semester, items in schedule.items()
        for item in items
        if item.get("course_id") is not None
    }


def course_dependents(schedule: Dict[int, List[Dict]]) -> Dict[int, List[int]]:
    """Build the reverse prerequisite map used by safe semester moves."""
    result: Dict[int, List[int]] = {}
    for items in schedule.values():
        for item in items:
            course_id = item.get("course_id")
            if course_id is None:
                continue
            for prerequisite_id in item.get("prerequisites") or []:
                result.setdefault(prerequisite_id, []).append(course_id)
    return result


def move_item(schedule: Dict[int, List[Dict]], source: int, target: int, item: Dict) -> bool:
    """Move an item between semesters without crashing on stale candidates."""
    if source == target:
        return False
    if not remove_item_once(schedule[source], item):
        return False
    schedule[target].append(item)
    return True


def swap_items(schedule: Dict[int, List[Dict]], left_semester: int, left_item: Dict, right_semester: int, right_item: Dict) -> bool:
    """Swap two schedule items only when both still exist."""
    if left_item not in schedule[left_semester] or right_item not in schedule[right_semester]:
        return False
    schedule[left_semester].remove(left_item)
    schedule[right_semester].remove(right_item)
    schedule[left_semester].append(right_item)
    schedule[right_semester].append(left_item)
    return True
