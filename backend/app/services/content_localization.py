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
    """Return database translations, using legacy JSON only for missing rows."""
    titles = {}
    descriptions = {}
    status = None
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
    if len(titles) < 3:
        legacy_titles = course_translations(course_id, "title")
        legacy_descriptions = course_translations(course_id, "description")
        for language, value in legacy_titles.items():
            titles.setdefault(language, value)
        for language, value in legacy_descriptions.items():
            descriptions.setdefault(language, value)
        status = status or course_translation_status(course_id)
    return {
        "title_translations": titles,
        "description_translations": descriptions,
        "translation_status": status,
    }


def course_localization_map(db, course_ids, include_descriptions=True):
    """Batch variant of course_localization_payload for response builders."""
    result = {int(course_id): {
        "title_translations": {},
        "description_translations": {},
        "translation_status": None,
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
            if include_descriptions and row.description:
                payload["description_translations"][row.language] = row.description
            if row.status == "verified":
                payload["translation_status"] = "verified"
            elif not payload.get("translation_status"):
                payload["translation_status"] = row.status
    except Exception:
        pass
    missing_ids = [
        course_id for course_id, payload in result.items()
        if len(payload["title_translations"]) < 3
    ]
    for course_id in missing_ids:
        payload = result[course_id]
        for language, value in course_translations(course_id, "title").items():
            payload["title_translations"].setdefault(language, value)
        if include_descriptions:
            for language, value in course_translations(course_id, "description").items():
                payload["description_translations"].setdefault(language, value)
        payload["translation_status"] = (
            payload["translation_status"] or course_translation_status(course_id)
        )
    return result


def register_course_translations(records, db=None):
    """Store translations in the database; keep JSON only as a legacy fallback."""
    if not records:
        return 0
    if db is not None:
        from app.models.course import CourseLocalization

        stored = 0
        verified_statuses = {
            "approved", "verified", "verified_epvo",
            "verified_epvo_fuzzy", "machine_reviewed",
        }
        for course_id, payload in records.items():
            if not isinstance(payload, dict):
                continue
            titles = payload.get("title") if isinstance(payload.get("title"), dict) else payload
            descriptions = payload.get("description") if isinstance(payload.get("description"), dict) else {}
            status = "verified" if payload.get("review_status") in verified_statuses else "draft"
            source = payload.get("source") or "epvo_normalized_repository"
            for language in ("ru", "kk", "en"):
                title = str((titles or {}).get(language) or "").strip()
                if not title:
                    continue
                row = db.query(CourseLocalization).filter(
                    CourseLocalization.course_id == int(course_id),
                    CourseLocalization.language == language,
                ).first()
                if row is None:
                    row = CourseLocalization(
                        course_id=int(course_id),
                        language=language,
                        title=title,
                    )
                    db.add(row)
                row.title = title
                description = str((descriptions or {}).get(language) or "").strip()
                if description:
                    row.description = description
                row.source = source
                row.status = status
                stored += 1
        db.flush()
        return stored

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
    return len(records)
