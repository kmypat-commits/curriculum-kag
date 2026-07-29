"""Fill missing course_localizations without overwriting verified records."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.course import Course, CourseLocalization
from app.models.epvo import EpvoDisciplineNormalized


ROOT = Path(__file__).resolve().parents[2]
TRANSLATIONS = ROOT / "backend" / "data" / "course_translations.json"
VERIFIED_STATUSES = {
    "approved", "verified", "verified_epvo",
    "verified_epvo_fuzzy", "machine_reviewed",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("--database-url or DATABASE_URL is required")

    legacy = (
        json.loads(TRANSLATIONS.read_text(encoding="utf-8"))
        if TRANSLATIONS.exists() else {}
    )
    engine = create_engine(args.database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    db = Session()
    inserted = {"ru": 0, "kk": 0, "en": 0}
    verified = 0
    draft = 0
    try:
        existing = {
            (int(course_id), str(language))
            for course_id, language in db.query(
                CourseLocalization.course_id,
                CourseLocalization.language,
            ).all()
        }
        epvo_cache: dict[int, EpvoDisciplineNormalized | None] = {}
        for course in db.query(Course).yield_per(500):
            payload = legacy.get(str(course.id), {})
            titles = payload.get("title") if isinstance(payload.get("title"), dict) else {}
            descriptions = (
                payload.get("description")
                if isinstance(payload.get("description"), dict) else {}
            )
            raw_status = payload.get("review_status") or "draft"
            status = "verified" if raw_status in VERIFIED_STATUSES else "draft"
            source = payload.get("source") or "localization_backfill"

            normalized = None
            if str(course.course_id or "").startswith("EPVO-"):
                try:
                    epvo_id = int(str(course.course_id).split("-", 1)[1])
                except ValueError:
                    epvo_id = 0
                if epvo_id:
                    if epvo_id not in epvo_cache:
                        epvo_cache[epvo_id] = db.get(EpvoDisciplineNormalized, epvo_id)
                    normalized = epvo_cache[epvo_id]

            normalized_titles = {
                "ru": normalized.title_ru if normalized else None,
                "kk": normalized.title_kk if normalized else None,
                "en": normalized.title_en if normalized else None,
            }
            content = (normalized.content_json or {}) if normalized else {}
            normalized_descriptions = {
                "ru": content.get("description_ru") or content.get("description"),
                "kk": content.get("description_kk"),
                "en": content.get("description_en"),
            }
            for language in ("ru", "kk", "en"):
                if (course.id, language) in existing:
                    continue
                title = (
                    (titles or {}).get(language)
                    or normalized_titles.get(language)
                    or course.title
                )
                description = (
                    (descriptions or {}).get(language)
                    or normalized_descriptions.get(language)
                    or course.description
                )
                row_status = status if (titles or {}).get(language) else (
                    "verified" if normalized_titles.get(language) else "draft"
                )
                row_source = source if (titles or {}).get(language) else (
                    "epvo" if normalized_titles.get(language) else "rule_based_draft"
                )
                db.add(CourseLocalization(
                    course_id=course.id,
                    language=language,
                    title=str(title or course.title),
                    description=str(description) if description else None,
                    source=str(row_source),
                    status=row_status,
                ))
                existing.add((course.id, language))
                inserted[language] += 1
                if row_status == "verified":
                    verified += 1
                else:
                    draft += 1
            if sum(inserted.values()) and sum(inserted.values()) % 500 == 0:
                db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    result = {
        "database": engine.dialect.name,
        "inserted_by_language": inserted,
        "inserted_total": sum(inserted.values()),
        "verified": verified,
        "draft": draft,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
