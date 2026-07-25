"""Idempotently seed ГОСО РК activity cards into the course repository."""
from app.database import SessionLocal
from app.planner.goso import (
    BACHELOR_COMPLETION_ITEMS,
    DOCTORATE_PROFILE_ITEMS,
    DOCTORATE_SCIENTIFIC_ITEMS,
    GOSO_COURSE_LO_CODES,
    GOSO_PROGRAM_LOS,
    MASTER_PROFILE_60_ITEMS,
    MASTER_PROFILE_90_ITEMS,
    MASTER_SCIENTIFIC_ITEMS,
    _upsert_course,
)


def main() -> None:
    definitions = {}
    for group in (
        BACHELOR_COMPLETION_ITEMS,
        MASTER_SCIENTIFIC_ITEMS,
        MASTER_PROFILE_60_ITEMS,
        MASTER_PROFILE_90_ITEMS,
        DOCTORATE_SCIENTIFIC_ITEMS,
        DOCTORATE_PROFILE_ITEMS,
    ):
        for definition in group:
            definitions.setdefault(definition[0], definition)

    lo_texts = {
        code: text
        for rows in GOSO_PROGRAM_LOS.values()
        for code, text in rows
    }
    db = SessionLocal()
    try:
        for definition in definitions.values():
            course = _upsert_course(db, *definition)
            lo_code = GOSO_COURSE_LO_CODES.get(definition[0])
            if lo_code in lo_texts:
                course.learning_outcomes = [lo_texts[lo_code]]
        db.commit()
        print(f"Seeded ГОСО РК repository cards: {len(definitions)}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
