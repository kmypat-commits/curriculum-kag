"""Repair provable UTF-8/CP1251 mojibake in course localizations.

Only values containing known mojibake markers are considered. A candidate is
written back only when the round-trip removes markers and introduces no
replacement characters.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.course import Course, CourseLocalization
from app.models.epvo import EpvoDisciplineNormalized


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "backend" / "experiment-results" / "localization-audit" / "mojibake-repair.json"
MARKERS = ("Р", "С", "вЂ", "РІ", "Рќ", "Рџ")


def repair(value: str | None) -> str | None:
    if not value or not any(marker in value for marker in MARKERS):
        return None
    try:
        # Mojibake produced by mixed Windows code pages can contain both
        # Cyrillic CP1251 characters and punctuation represented by CP1252.
        raw = bytearray()
        for char in value:
            try:
                raw.extend(char.encode("cp1251"))
            except UnicodeEncodeError:
                raw.extend(char.encode("cp1252"))
        candidate = bytes(raw).decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    if "�" in candidate:
        return None
    before = sum(value.count(marker) for marker in MARKERS)
    after = sum(candidate.count(marker) for marker in MARKERS)
    return candidate if after < before else None


def main() -> int:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    engine = create_engine(url, pool_pre_ping=True)
    changed: list[dict] = []
    with Session(engine) as db:
        rows = db.query(CourseLocalization).all()
        course_by_id = {row.id: row for row in db.query(Course).all()}
        epvo_by_course_id = {
            int(row.approved_course_id): row
            for row in db.query(EpvoDisciplineNormalized).filter(
                EpvoDisciplineNormalized.approved_course_id.isnot(None)
            ).all()
        }
        epvo_ids = []
        for course in course_by_id.values():
            if str(course.course_id or "").startswith("EPVO-"):
                try:
                    epvo_ids.append(int(str(course.course_id).split("-", 1)[1]))
                except ValueError:
                    pass
        epvo_by_normalized_id = {
            int(row.id): row
            for row in db.query(EpvoDisciplineNormalized).filter(
                EpvoDisciplineNormalized.id.in_(epvo_ids or [-1])
            ).all()
        }
        legacy = {}
        legacy_path = ROOT / "backend" / "data" / "course_translations.json"
        if legacy_path.exists():
            try:
                legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                legacy = {}
        for row in rows:
            for field in ("title", "description"):
                old = getattr(row, field) or ""
                if "�" in old:
                    source = legacy.get(str(row.course_id), {}).get(field, {}).get(row.language)
                    course = course_by_id.get(int(row.course_id))
                    epvo = epvo_by_course_id.get(int(row.course_id))
                    if epvo is None and course and str(course.course_id or "").startswith("EPVO-"):
                        try:
                            epvo = epvo_by_normalized_id.get(int(str(course.course_id).split("-", 1)[1]))
                        except ValueError:
                            epvo = None
                    content = epvo.content_json if epvo and isinstance(epvo.content_json, dict) else {}
                    source = source or content.get(f"{field}_{row.language}")
                    if field == "description" and not source:
                        source = course.description if course and row.language == "ru" else None
                    if source and "�" not in source:
                        setattr(row, field, source)
                        changed.append({
                            "course_id": row.course_id,
                            "language": row.language,
                            "field": field,
                            "before": old,
                            "after": source,
                            "source": "legacy_or_epvo",
                        })
                        continue
                    # No authoritative source was available. Remove only the
                    # replacement marker and explicitly mark the row for
                    # review; never fabricate the missing text.
                    if "�" in old:
                        cleaned = old.replace("�", "")
                        setattr(row, field, cleaned)
                        row.status = "needs_review"
                        changed.append({
                            "course_id": row.course_id,
                            "language": row.language,
                            "field": field,
                            "before": old,
                            "after": cleaned,
                            "source": "marker_removed_needs_review",
                        })
                        continue
                new = repair(old)
                if new is None:
                    continue
                setattr(row, field, new)
                changed.append({
                    "course_id": row.course_id,
                    "language": row.language,
                    "field": field,
                    "before": old,
                    "after": new,
                })
        db.commit()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"changed": len(changed), "rows": changed}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"changed": len(changed), "output": str(OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
