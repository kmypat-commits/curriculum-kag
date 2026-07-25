import json
from functools import lru_cache
from pathlib import Path


TRANSLATIONS_FILE = Path(__file__).resolve().parents[2] / "data" / "course_translations.json"


@lru_cache(maxsize=1)
def _course_translations():
    if not TRANSLATIONS_FILE.exists():
        return {}
    try:
        return json.loads(TRANSLATIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def course_translations(course_id, field="title"):
    record = _course_translations().get(str(course_id), {})
    if record.get("review_status") not in {"approved", "verified_epvo", "verified_epvo_fuzzy", "machine_reviewed"}:
        return {}
    value = record.get(field, {})
    return value if isinstance(value, dict) else {}


def course_translation_status(course_id):
    return _course_translations().get(str(course_id), {}).get("review_status")


def course_localization_payload(db, course_id):
    """Return title/description translations from SQLite, falling back to legacy JSON."""
    titles = dict(course_translations(course_id, "title"))
    descriptions = dict(course_translations(course_id, "description"))
    status = course_translation_status(course_id)
    try:
        from app.models.course import CourseLocalization

        rows = db.query(CourseLocalization).filter(CourseLocalization.course_id == course_id).all()
        for row in rows:
            if row.title:
                titles[row.language] = row.title
            if row.description:
                descriptions[row.language] = row.description
            if row.status == "verified":
                status = "verified"
            elif not status:
                status = row.status
    except Exception:
        pass
    return {
        "title_translations": titles,
        "description_translations": descriptions,
        "translation_status": status,
    }


def course_localization_map(db, course_ids):
    """Batch variant of course_localization_payload for response builders."""
    result = {int(course_id): {
        "title_translations": dict(course_translations(course_id, "title")),
        "description_translations": dict(course_translations(course_id, "description")),
        "translation_status": course_translation_status(course_id),
    } for course_id in set(course_ids or []) if course_id}
    if not result:
        return result
    try:
        from app.models.course import CourseLocalization

        rows = db.query(CourseLocalization).filter(CourseLocalization.course_id.in_(list(result))).all()
        for row in rows:
            payload = result.setdefault(int(row.course_id), {
                "title_translations": {},
                "description_translations": {},
                "translation_status": None,
            })
            if row.title:
                payload["title_translations"][row.language] = row.title
            if row.description:
                payload["description_translations"][row.language] = row.description
            if row.status == "verified":
                payload["translation_status"] = "verified"
            elif not payload.get("translation_status"):
                payload["translation_status"] = row.status
    except Exception:
        pass
    return result


def register_course_translations(records):
    """Atomically add verified translations for approved EPVO courses."""
    if not records:
        return
    current = dict(_course_translations())
    for course_id, payload in records.items():
        if not isinstance(payload, dict):
            continue
        existing = dict(current.get(str(course_id), {}))
        titles = payload.get("title") if isinstance(payload.get("title"), dict) else payload
        descriptions = payload.get("description") if isinstance(payload.get("description"), dict) else None
        existing["title"] = {key: value for key, value in (titles or {}).items() if value}
        if descriptions:
            existing["description"] = {key: value for key, value in descriptions.items() if value}
        existing["review_status"] = payload.get("review_status") or "verified_epvo"
        existing["source"] = payload.get("source") or "epvo_normalized_repository"
        current[str(course_id)] = existing
    temporary = TRANSLATIONS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(TRANSLATIONS_FILE)
    _course_translations.cache_clear()
