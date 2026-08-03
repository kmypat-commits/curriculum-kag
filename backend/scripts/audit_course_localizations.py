"""Audit RU/KK/EN course localizations in SQLite or PostgreSQL."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE = f"sqlite:///{(ROOT / 'backend' / 'curriculum_kag.db').as_posix()}"
DEFAULT_OUT = (
    ROOT / "backend" / "experiment-results"
    / "translation-audit" / "course_localization_gaps.json"
)


def safe_database_name(url: str) -> str:
    if "@" not in url:
        return url
    prefix, suffix = url.rsplit("@", 1)
    scheme_user = prefix.split(":", 2)[:2]
    return ":".join(scheme_user) + ":***@" + suffix


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL") or DEFAULT_SQLITE,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    engine = create_engine(args.database_url, pool_pre_ping=True)
    missing: dict[str, int] = {}
    samples: dict[str, list[dict]] = {}
    catalogue_layers: dict[str, dict] = {}
    source_coverage: dict[str, dict[str, float | int]] = {}
    with engine.connect() as connection:
        total_courses = int(connection.execute(text("SELECT count(*) FROM courses")).scalar() or 0)
        by_language = {
            str(row.language): int(row.count)
            for row in connection.execute(text(
                "SELECT language, count(*) AS count "
                "FROM course_localizations GROUP BY language"
            )).mappings()
        }
        by_status = {
            str(row.status): int(row.count)
            for row in connection.execute(text(
                "SELECT status, count(*) AS count "
                "FROM course_localizations GROUP BY status"
            )).mappings()
        }
        # Only the Unicode replacement character is an unambiguous corruption
        # signal at the SQL layer. Broad mojibake LIKE patterns caused false
        # positives for ordinary Cyrillic and Kazakh words.
        corrupt_predicate = " OR ".join(
            [
                "title LIKE :replacement",
                "description LIKE :replacement",
            ]
        )
        corrupt_params = {
            "replacement": "%\ufffd%",
            # Use multi-character fragments to avoid false positives such as
            # the legitimate Kazakh acronym ``КРІ``.
            "moji1": "%РџР%",
            "moji2": "%РЎР%",
            "moji3": "%РІР%",
            "moji4": "%С‚Р%",
            "moji5": "%вЂ%",
            "moji6": "%У™%",
            "moji7": "%Т›%",
        }
        corrupt_values = int(connection.execute(
            text("SELECT count(*) FROM course_localizations WHERE " + corrupt_predicate),
            corrupt_params,
        ).scalar() or 0)
        corrupt_samples = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT course_id, language, title, description "
                    "FROM course_localizations "
                    "WHERE " + corrupt_predicate + " "
                    "ORDER BY course_id, language LIMIT 30"
                ),
                corrupt_params,
            ).mappings()
        ]
        same_title_fallbacks = int(connection.execute(text("""
            WITH p AS (
              SELECT course_id,
                max(title) FILTER (WHERE language='ru') AS ru,
                max(title) FILTER (WHERE language='kk') AS kk,
                max(title) FILTER (WHERE language='en') AS en
              FROM course_localizations GROUP BY course_id
            )
            SELECT count(*) FROM p WHERE ru=kk AND kk=en AND coalesce(ru,'')<>''
        """)).scalar() or 0)
        unresolved_description_fallbacks = int(connection.execute(text("""
            WITH p AS (
              SELECT course_id,
                max(description) FILTER (WHERE language='ru') AS ru,
                max(description) FILTER (WHERE language='kk') AS kk,
                max(description) FILTER (WHERE language='en') AS en
              FROM course_localizations GROUP BY course_id
            )
            SELECT count(*) FROM p
            JOIN epvo_disciplines_normalized n ON n.approved_course_id=p.course_id
            WHERE p.ru=p.kk AND p.kk=p.en AND coalesce(p.ru,'')<>''
              AND trim(coalesce(n.content_json->>'description_kk',''))=''
              AND trim(coalesce(n.content_json->>'description_en',''))=''
        """)).scalar() or 0)
        for language in ("ru", "kk", "en"):
            condition = (
                "FROM courses c LEFT JOIN course_localizations l "
                "ON l.course_id = c.id AND l.language = :language "
                "WHERE l.id IS NULL"
            )
            missing[language] = int(connection.execute(
                text("SELECT count(*) " + condition),
                {"language": language},
            ).scalar() or 0)
            rows = connection.execute(
                text(
                    "SELECT c.id, c.course_id, c.title "
                    + condition + " ORDER BY c.id LIMIT 30"
                ),
                {"language": language},
            ).mappings()
            samples[language] = [dict(row) for row in rows]

        # Directions and programme groups are also user-visible multilingual
        # catalogue data.  Keep this check in the same audit so a complete
        # course report cannot hide an untranslated wizard dropdown.
        for table in ("epvo_directions", "epvo_groups"):
            try:
                total = int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)
                missing_count = int(connection.execute(text(
                    f"SELECT count(*) FROM {table} WHERE "
                    "title_ru IS NULL OR trim(title_ru)='' OR "
                    "title_kk IS NULL OR trim(title_kk)='' OR "
                    "title_en IS NULL OR trim(title_en)=''"
                )).scalar() or 0)
                catalogue_predicate = " OR ".join(
                    f"{column} LIKE :{parameter}"
                    for column in ("title_ru", "title_kk", "title_en")
                        for parameter in ("replacement",)
                )
                corrupt_count = int(connection.execute(text(
                    f"SELECT count(*) FROM {table} WHERE {catalogue_predicate}"
                ), corrupt_params).scalar() or 0)
                catalogue_layers[table] = {
                    "total": total,
                    "missing_translations": missing_count,
                    "corrupt_values": corrupt_count,
                    "complete": total > 0 and missing_count == 0 and corrupt_count == 0,
                }
            except Exception:
                # Older SQLite snapshots do not contain the layered EPVO
                # catalogue; the course audit remains useful there.
                catalogue_layers[table] = {"available": False}

        # The normalized layer can contain historical EPVO cards that are not
        # promoted to the active repository. Report its source completeness
        # separately; missing fields here mean that the raw card itself had no
        # translation and must not be silently replaced by RU text.
        try:
            normalized_total = int(connection.execute(text("SELECT count(*) FROM epvo_disciplines_normalized")).scalar() or 0)
            for field in ("title_ru", "title_kk", "title_en"):
                filled = int(connection.execute(text(f"SELECT count(*) FROM epvo_disciplines_normalized WHERE trim(coalesce({field},''))<>''")).scalar() or 0)
                source_coverage[field] = {"filled": filled, "total": normalized_total, "coverage": round(filled / max(normalized_total, 1), 6)}
            for lang in ("ru", "kk", "en"):
                filled = int(connection.execute(text(f"SELECT count(*) FROM epvo_disciplines_normalized WHERE trim(coalesce(content_json->>'description_{lang}',''))<>''")).scalar() or 0)
                source_coverage[f"description_{lang}"] = {"filled": filled, "total": normalized_total, "coverage": round(filled / max(normalized_total, 1), 6)}
        except Exception:
            source_coverage = {}

    report = {
        "database": safe_database_name(args.database_url),
        "database_dialect": engine.dialect.name,
        "total_courses": total_courses,
        "localized_by_language": by_language,
        "localized_by_status": by_status,
        "missing_by_language": missing,
        "corrupt_values": corrupt_values,
        "corrupt_samples": corrupt_samples,
        "same_title_fallbacks": same_title_fallbacks,
        "unresolved_description_fallbacks": unresolved_description_fallbacks,
        "translation_quality_score": round(
            1 - unresolved_description_fallbacks / max(total_courses, 1), 4
        ),
        "complete": (
            total_courses > 0
            and all(value == 0 for value in missing.values())
            and corrupt_values == 0
            and all(
                not layer.get("available", True) or layer.get("complete", False)
                for layer in catalogue_layers.values()
            )
        ),
        "samples": samples,
        "catalogue_layers": catalogue_layers,
        "normalized_source_coverage": source_coverage,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "complete": report["complete"],
        "database": report["database_dialect"],
        "courses": total_courses,
        "localized": by_language,
        "statuses": by_status,
        "missing": missing,
        "corrupt_values": corrupt_values,
        "translation_quality_score": report["translation_quality_score"],
        "unresolved_description_fallbacks": unresolved_description_fallbacks,
        "directions": catalogue_layers.get("epvo_directions"),
        "groups": catalogue_layers.get("epvo_groups"),
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
