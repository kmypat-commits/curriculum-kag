import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError


TRANSLATIONS_FILE = Path(__file__).resolve().parents[2] / "data" / "course_translations.json"


def _repair_mojibake(value):
    """Repair legacy UTF-8-as-CP1251 text at the presentation boundary."""
    if not isinstance(value, str) or not value or not any(marker in value for marker in ("\u0420", "\u0421", "\u00d0", "\u00d1", "\u00c2")):
        return value
    try:
        repaired = value.encode("cp1251").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    old_markers = value.count("Р") + value.count("С")
    new_markers = repaired.count("Р") + repaired.count("С")
    return repaired if new_markers < old_markers else value


def bridge_title_translations(title):
    """Create stable RU/KK/EN labels for generated bridge modules.

    BridgeModule predates the three-language course catalogue and has one
    generated title column.  These deterministic templates prevent the UI
    from presenting an empty translation map while preserving the original
    Russian title as the authoritative fallback for custom titles.
    """
    text = _repair_mojibake(str(title or "Bridge-модуль"))
    replacements = {
        "ru": {},
        "kk": {
            "Интеграционный модуль": "Интеграциялық модуль",
            "данных и аналитики": "деректер мен аналитика",
            "моделей и алгоритмов": "модельдер мен алгоритмдер",
            "внедрения цифровых систем": "цифрлық жүйелерді енгізу",
            "Информационно-коммуникационные технологии": "Ақпараттық-коммуникациялық технологиялар",
            "Агрономия": "Агрономия",
            " и ": " және ",
            "- семестр": "- семестр",
            "Модуль закрытия пробелов результатов обучения": "Оқу нәтижелеріндегі олқылықтарды жабу модулі",
            "Основы области": "Сала негіздері",
            "Данные и процессы области": "Сала деректері мен процестері",
            "модуль": "модуль",
            "Семестр": "Семестр",
        },
        "en": {
            "Интеграционный модуль": "Integration module",
            "данных и аналитики": "data and analytics",
            "моделей и алгоритмов": "models and algorithms",
            "внедрения цифровых систем": "deployment of digital systems",
            "Информационно-коммуникационные технологии": "Information and communication technologies",
            "Агрономия": "Agronomy",
            " и ": " and ",
            "- семестр": "- semester",
            "Модуль закрытия пробелов результатов обучения": "Learning-outcome gap module",
            "Основы области": "Foundations of",
            "Данные и процессы области": "Data and processes of",
            "модуль": "module",
            "Семестр": "Semester",
        },
    }
    result = {"ru": text}
    for language, mapping in replacements.items():
        value = text
        for source, target in mapping.items():
            value = value.replace(source, target)
        result[language] = value
    return result


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
    # Do not hide an existing EPVO translation only because its review status is
    # draft/needs_review.  The repository must show the source text; the status
    # badge tells the user whether it is verified.  Previously this filter made
    # valid English/Kazakh titles disappear (e.g. ArchiCAD and clinical courses).
    value = record.get(field, {})
    return value if isinstance(value, dict) else {}


@lru_cache(maxsize=1)
def _title_translation_index():
    """Index legacy EPVO translations by normalized Russian title.

    New normalized EPVO rows use an ``EPVO-*`` identifier, while the older
    export is keyed by numeric course id.  Matching by the canonical Russian
    title lets us recover an existing expert-sourced KK/EN title without
    inventing a translation or modifying the raw dataset.
    """
    index = {}
    for record in _course_translations().values():
        title = record.get("title", {}) if isinstance(record, dict) else {}
        if not isinstance(title, dict):
            continue
        ru = _repair_mojibake(title.get("ru") or "")
        key = " ".join(str(ru).casefold().split())
        if key and title.get("kk") and title.get("en"):
            index.setdefault(key, {lang: _repair_mojibake(title.get(lang)) for lang in ("ru", "kk", "en")})
    return index


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
    except (ImportError, SQLAlchemyError, AttributeError):
        pass
    if len(titles) < 3 and _legacy_fallback_enabled():
        legacy_titles = course_translations(course_id, "title")
        legacy_descriptions = course_translations(course_id, "description")
        for language, value in legacy_titles.items():
            titles.setdefault(language, value)
        for language, value in legacy_descriptions.items():
            descriptions.setdefault(language, value)
        status = status or course_translation_status(course_id)
    return {
        "title_translations": {language: _repair_mojibake(value) for language, value in titles.items()},
        "description_translations": {language: _repair_mojibake(value) for language, value in descriptions.items()},
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
    except (ImportError, SQLAlchemyError, AttributeError):
        pass
    missing_ids = [
        course_id for course_id, payload in result.items()
        if len(payload["title_translations"]) < 3
    ]
    for course_id in missing_ids if _legacy_fallback_enabled() else []:
        payload = result[course_id]
        for language, value in course_translations(course_id, "title").items():
            payload["title_translations"].setdefault(language, value)
        if include_descriptions:
            for language, value in course_translations(course_id, "description").items():
                payload["description_translations"].setdefault(language, value)
        payload["translation_status"] = (
            payload["translation_status"] or course_translation_status(course_id)
        )

    # Imported EPVO courses often have their multilingual fields on the
    # normalized repository row rather than in CourseLocalization.  Enrich
    # the response here so every consumer (plans, graph, syllabus and
    # prerequisites) receives the same language map.  This also prevents a
    # language switch from falling back to the raw Course.title.
    try:
        from app.models.course import Course
        from app.models.epvo import EpvoDisciplineNormalized

        ids = [int(value) for value in result]
        courses = db.query(Course).filter(Course.id.in_(ids)).all()
        epvo_rows = db.query(EpvoDisciplineNormalized).filter(
            EpvoDisciplineNormalized.approved_course_id.in_(ids)
        ).all()
        epvo_by_course = {int(row.approved_course_id): row for row in epvo_rows if row.approved_course_id}
        for course in courses:
            payload = result[int(course.id)]
            row = epvo_by_course.get(int(course.id))
            content = row.content_json if row and isinstance(row.content_json, dict) else {}
            for language in ("ru", "kk", "en"):
                title = getattr(row, f"title_{language}", None) if row else None
                title = title or content.get(f"title_{language}")
                if title:
                    payload["title_translations"].setdefault(language, title)
                if include_descriptions:
                    description = content.get(f"description_{language}")
                    if description:
                        payload["description_translations"].setdefault(language, description)
            if not payload["title_translations"] and course.title:
                payload["title_translations"]["ru"] = course.title
            if include_descriptions and not payload["description_translations"] and course.description:
                payload["description_translations"]["ru"] = course.description
            if len(payload["title_translations"]) < 3:
                legacy = _title_translation_index().get(" ".join(str(course.title or "").casefold().split()))
                if legacy and _legacy_fallback_enabled():
                    for language, title in legacy.items():
                        payload["title_translations"].setdefault(language, title)
    except (ImportError, SQLAlchemyError, AttributeError):
        # Localization must never make the plan endpoint unavailable. The
        # database/local JSON values collected above remain valid fallbacks.
        pass
    for payload in result.values():
        payload["title_translations"] = {
            language: _repair_mojibake(value)
            for language, value in payload["title_translations"].items()
        }
        payload["description_translations"] = {
            language: _repair_mojibake(value)
            for language, value in payload["description_translations"].items()
        }
        # Do not present a Russian-only source as a completed multilingual
        # record.  The UI can keep the source fallback, but the status makes
        # the missing KK/EN translation explicit for review.
        title_values = [str(payload["title_translations"].get(lang) or "").strip() for lang in ("ru", "kk", "en")]
        if len(payload["title_translations"]) < 3 or (title_values[0] and title_values[0] == title_values[1] == title_values[2]):
            if payload.get("translation_status") not in {"verified", "verified_epvo", "machine_reviewed"}:
                payload["translation_status"] = "needs_translation"
    return result


def _legacy_fallback_enabled():
    """Return whether the legacy JSON catalogue may be used as a fallback."""
    try:
        from app.config import settings
        return bool(settings.LEGACY_TRANSLATIONS_FALLBACK)
    except (ImportError, AttributeError):
        return False


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
