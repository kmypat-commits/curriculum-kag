"""Restore corrupt EPVO localizations from the normalized source repository."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker

from app.models.course import Course, CourseLocalization
from app.models.epvo import EpvoDisciplineNormalized, RawEpvoDiscipline


ROOT = Path(__file__).resolve().parents[2]
TRANSLATIONS = ROOT / "backend" / "data" / "course_translations.json"
CONTEXTUAL_OVERRIDES = {
    ("EPVO-29851", "kk"): ("обектілі-бағытталған", "объектілі-бағытталған"),
}


def cleaned(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\ufffd", "")).strip()


def raw_description(payload: dict, language: str) -> str:
    keys = {
        "ru": ("briefinforu", "descriptionRu", "description_ru"),
        "kk": ("briefinfo", "briefinfokz", "descriptionKz", "description_kk"),
        "en": ("briefinfoen", "descriptionEn", "description_en"),
    }[language]
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value and "\ufffd" not in value:
            return value
    return ""


def title_key(value: str | None) -> str:
    return " ".join(str(value or "").casefold().split())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("--database-url or DATABASE_URL is required")

    # The PostgreSQL catalogue is authoritative.  The legacy JSON cache may
    # be absent or empty after an interrupted export; repairs must still run
    # against the database instead of failing before opening a session.
    try:
        raw_translation_cache = TRANSLATIONS.read_text(encoding="utf-8").strip()
        records = json.loads(raw_translation_cache) if raw_translation_cache else {}
    except (OSError, json.JSONDecodeError):
        records = {}
    engine = create_engine(args.database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    db = Session()
    restored = 0
    unresolved = 0
    json_updated = 0
    try:
        affected = db.query(CourseLocalization, Course).join(
            Course, Course.id == CourseLocalization.course_id
        ).filter(or_(
            CourseLocalization.source == "encoding_repair_needs_review",
            CourseLocalization.title.contains("\ufffd"),
            CourseLocalization.description.contains("\ufffd"),
        )).all()
        normalized_by_course: dict[int, EpvoDisciplineNormalized | None] = {}
        subject_ids_by_course: dict[int, set[str]] = {}
        target_title_keys: set[str] = set()
        target_subject_ids: set[str] = set()
        target_source_keys: set[str] = set()
        for affected_row, course in affected:
            normalized = None
            if str(course.course_id or "").startswith("EPVO-"):
                try:
                    normalized = db.get(
                        EpvoDisciplineNormalized,
                        int(str(course.course_id).split("-", 1)[1]),
                    )
                except ValueError:
                    pass
            normalized_by_course[course.id] = normalized
            if (str(course.course_id), affected_row.language) in CONTEXTUAL_OVERRIDES:
                continue
            if normalized and normalized.source_keys:
                target_source_keys.update(
                    str(value).strip()
                    for value in (normalized.source_keys or [])
                    if str(value).strip()
                )
                subject_ids = {
                    str((raw.payload_json or {}).get("subjectid") or "").strip()
                    for raw in db.query(RawEpvoDiscipline).filter(
                        RawEpvoDiscipline.source_key.in_(normalized.source_keys)
                    ).all()
                }
                subject_ids.discard("")
                subject_ids_by_course[course.id] = subject_ids
                target_subject_ids.update(subject_ids)
            target_title_keys.update(filter(None, {
                title_key(course.title),
                title_key(normalized.canonical_title) if normalized else "",
                title_key(normalized.title_ru) if normalized else "",
                title_key(normalized.title_kk) if normalized else "",
                title_key(normalized.title_en) if normalized else "",
            }))

        global_alternatives: dict[tuple[str, str], str] = {}
        subject_alternatives: dict[tuple[str, str], str] = {}
        if target_source_keys:
            # The previous implementation scanned the entire raw EPVO table
            # for every repair, which made the SQLite fallback take minutes
            # on a multi-gigabyte database.  A corrupt course already carries
            # its normalized source_keys, so restrict recovery to those rows.
            # Direct normalized/source-key recovery remains unchanged; broad
            # title/subject fallback is only attempted when explicitly needed
            # by a future repair job.
            raw_query = db.query(RawEpvoDiscipline.payload_json).filter(
                RawEpvoDiscipline.source_key.in_(sorted(target_source_keys))
            )
            for (payload,) in raw_query.yield_per(1000):
                payload = payload or {}
                matching_keys = {
                    title_key(payload.get("nameRu")),
                    title_key(payload.get("nameKz")),
                    title_key(payload.get("nameEn")),
                } & target_title_keys
                subject_id = str(payload.get("subjectid") or "").strip()
                subject_matches = subject_id and subject_id in target_subject_ids
                if not matching_keys and not subject_matches:
                    continue
                for language in ("ru", "kk", "en"):
                    value = raw_description(payload, language)
                    if not value:
                        continue
                    for key in matching_keys:
                        previous = global_alternatives.get((key, language), "")
                        if len(value) > len(previous):
                            global_alternatives[(key, language)] = value
                    if subject_matches:
                        previous = subject_alternatives.get((subject_id, language), "")
                        if len(value) > len(previous):
                            subject_alternatives[(subject_id, language)] = value

        normalized_cache: dict[int, EpvoDisciplineNormalized | None] = {}
        for row, course in affected:
            epvo_id = None
            if str(course.course_id or "").startswith("EPVO-"):
                try:
                    epvo_id = int(str(course.course_id).split("-", 1)[1])
                except ValueError:
                    pass
            normalized = normalized_by_course.get(course.id)
            if epvo_id is not None:
                if epvo_id not in normalized_cache:
                    normalized_cache[epvo_id] = normalized or db.get(EpvoDisciplineNormalized, epvo_id)
                normalized = normalized_cache[epvo_id]
            content = (normalized.content_json or {}) if normalized else {}
            contextual_restore = False
            source_title = getattr(normalized, f"title_{row.language}", None) if normalized else None
            source_description = (
                content.get(f"description_{row.language}")
                or (content.get("description") if row.language == "ru" else None)
            )
            if (
                not source_description
                or "\ufffd" in str(source_description)
            ) and normalized and normalized.source_keys:
                alternatives = []
                for raw in db.query(RawEpvoDiscipline).filter(
                    RawEpvoDiscipline.source_key.in_(normalized.source_keys)
                ).all():
                    value = raw_description(raw.payload_json or {}, row.language)
                    if value:
                        alternatives.append(value)
                if alternatives:
                    source_description = max(alternatives, key=len)
            override = CONTEXTUAL_OVERRIDES.get((str(course.course_id), row.language))
            if override and (not source_description or "\ufffd" in str(source_description)):
                source_description = cleaned(row.description or "").replace(
                    override[0], override[1]
                )
                contextual_restore = True
            if not source_description or "\ufffd" in str(source_description):
                alternatives = [
                    subject_alternatives[(subject_id, row.language)]
                    for subject_id in subject_ids_by_course.get(course.id, set())
                    if (subject_id, row.language) in subject_alternatives
                ]
                if alternatives:
                    source_description = max(alternatives, key=len)
            if not source_description or "\ufffd" in str(source_description):
                candidate_keys = filter(None, {
                    title_key(course.title),
                    title_key(normalized.canonical_title) if normalized else "",
                    title_key(normalized.title_ru) if normalized else "",
                    title_key(normalized.title_kk) if normalized else "",
                    title_key(normalized.title_en) if normalized else "",
                })
                alternatives = [
                    global_alternatives[(key, row.language)]
                    for key in candidate_keys
                    if (key, row.language) in global_alternatives
                ]
                if alternatives:
                    source_description = max(alternatives, key=len)
            source_is_clean = (
                bool(source_description)
                and "\ufffd" not in str(source_description)
                and (not source_title or "\ufffd" not in str(source_title))
            )
            if source_is_clean:
                if source_title:
                    row.title = str(source_title)
                row.description = str(source_description)
                row.status = "draft" if contextual_restore else "verified"
                row.source = (
                    "contextual_restore_ru_en"
                    if contextual_restore else "epvo_normalized_restore"
                )
                restored += 1
            else:
                row.title = cleaned(row.title or course.title)
                row.description = cleaned(row.description or "") or None
                row.status = "needs_review"
                row.source = "encoding_repair_needs_review"
                unresolved += 1

            payload = records.get(str(course.id))
            if isinstance(payload, dict):
                titles = payload.setdefault("title", {})
                descriptions = payload.setdefault("description", {})
                titles[row.language] = row.title
                if row.description:
                    descriptions[row.language] = row.description
                if source_is_clean:
                    payload["review_status"] = "draft" if contextual_restore else "verified_epvo"
                    payload["source"] = (
                        "contextual_restore_ru_en"
                        if contextual_restore else "epvo_normalized_restore"
                    )
                else:
                    payload["review_status"] = "needs_review"
                    payload["source"] = "encoding_repair_needs_review"
                json_updated += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    temporary = TRANSLATIONS.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(TRANSLATIONS)
    print(json.dumps({
        "restored_from_epvo": restored,
        "unresolved": unresolved,
        "legacy_records_updated": json_updated,
    }, ensure_ascii=False))
    return 0 if unresolved == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
