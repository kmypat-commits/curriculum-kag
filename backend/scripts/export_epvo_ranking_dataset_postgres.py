"""Build a clean, programme-level EPVO ranking set from PostgreSQL.

The old JSONL ranking set was an export artifact and is no longer present in
the repository.  This exporter reconstructs the same positive-edge view from
the raw EPVO layers and the normalized catalogue without touching production
tables or models.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import defaultdict
from pathlib import Path

from sqlalchemy import create_engine, text


def clean(value: object) -> str:
    text_value = " ".join(str(value or "").split()).strip()
    # Repair historical UTF-8/CP1251 mojibake using Unicode escapes so this
    # source remains ASCII-safe on Windows checkouts.
    for _ in range(2):
        if not re.search(r"(?:\u0420.|\u0421.){2,}", text_value):
            break
        try:
            candidate = text_value.encode("cp1251").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if candidate == text_value:
            break
        if (candidate.count("\u0420") + candidate.count("\u0421")) >= (text_value.count("\u0420") + text_value.count("\u0421")):
            break
        text_value = candidate
    # Some historical EPVO payloads were decoded as CP1251 after UTF-8.
    # Repair only the characteristic mojibake pattern; never alter normal
    # Latin/Cyrillic text.  This keeps the benchmark independent from stale
    # pre-repair JSONL exports without changing PostgreSQL.
    for _ in range(2):
        if not re.search(r"(?:Р.|С.){2,}", text_value):
            break
        try:
            candidate = text_value.encode("cp1251").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if candidate == text_value:
            break
        # Require a meaningful reduction of the common mojibake markers.
        old_markers = text_value.count("Р") + text_value.count("С")
        new_markers = candidate.count("Р") + candidate.count("С")
        if new_markers >= old_markers:
            break
        text_value = candidate
    return text_value


def localized(payload: dict, *keys: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for language, suffixes in {
        "ru": ("Ru", "RU", "ru"),
        "kz": ("Kz", "KZ", "kk", "Kk"),
        "en": ("En", "EN", "en"),
    }.items():
        for key in keys:
            for suffix in suffixes:
                value = clean(payload.get(f"{key}{suffix}"))
                if value:
                    result[language] = value
                    break
            if language in result:
                break
    return result


def split_for(program_id: str, seed: int = 42) -> str:
    bucket = int(hashlib.sha256(f"{seed}:{program_id}".encode()).hexdigest()[:8], 16) % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--output", type=Path, default=Path(".runtime/epvo-ranking-postgres"))
    parser.add_argument("--min-labelled-links", type=int, default=1)
    parser.add_argument("--max-programmes", type=int, default=2000,
                        help="Deterministic programme cap for a fast independent benchmark export")
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("--database-url or DATABASE_URL is required")

    engine = create_engine(args.database_url, pool_pre_ping=True)
    programmes: dict[str, dict] = {}
    disciplines: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    outcomes: dict[str, dict[str, dict]] = defaultdict(dict)
    normalized: dict[str, dict] = {}
    localized_courses: dict[int, dict[str, dict[str, str]]] = defaultdict(dict)
    links: dict[str, set[tuple[str, str]]] = defaultdict(set)
    link_strength: dict[tuple[str, str, str], float] = {}

    with engine.connect() as db:
        programme_filter = ""
        programme_params: dict[str, object] = {}
        if args.max_programmes > 0:
            selected_ids = [str(row[0]) for row in db.execute(text(
                "SELECT DISTINCT program_source_id FROM epvo_discipline_lo_links "
                "ORDER BY program_source_id LIMIT :limit"
            ), {"limit": args.max_programmes})]
            if not selected_ids:
                raise SystemExit("No EPVO programmes with expert links were found")
            placeholders = ", ".join(f":program_{index}" for index in range(len(selected_ids)))
            programme_filter = f" IN ({placeholders})"
            programme_params = {f"program_{index}": value for index, value in enumerate(selected_ids)}
        for row in db.execute(text(
            "SELECT source_id, payload_json FROM raw_epvo_programs "
            f"WHERE source_id{programme_filter}"
            if programme_filter else
            "SELECT source_id, payload_json FROM raw_epvo_programs"
        ), programme_params):
            payload = row.payload_json or {}
            program_id = str(row.source_id)
            direction = payload.get("trainingDirectionsObj") or {}
            group = payload.get("groupEduProgramObj") or {}
            programmes[program_id] = {
                "program_id": program_id,
                "split": split_for(program_id),
                "name": localized(payload, "eduProgramName", "name"),
                "goal": localized(payload, "eduGoalName", "goal"),
                "program_goal": localized(payload, "eduGoalName", "goal"),
                "training_direction": localized(direction, "name"),
                "program_group": localized(group, "name"),
                "training_direction_code": clean(direction.get("codeDirection")),
                "program_group_code": clean(group.get("code")),
                "credits": payload.get("creditsCount"),
            }
        for row in db.execute(text(
            "SELECT program_source_id, source_key, payload_json FROM raw_epvo_disciplines "
            f"WHERE program_source_id{programme_filter}"
            if programme_filter else
            "SELECT program_source_id, source_key, payload_json FROM raw_epvo_disciplines"
        ), programme_params):
            disciplines[str(row.program_source_id)].append((str(row.source_key), row.payload_json or {}))
        for row in db.execute(text(
            "SELECT program_source_id, source_key, payload_json FROM raw_epvo_learning_outcomes "
            f"WHERE program_source_id{programme_filter}"
            if programme_filter else
            "SELECT program_source_id, source_key, payload_json FROM raw_epvo_learning_outcomes"
        ), programme_params):
            payload = row.payload_json or {}
            outcomes[str(row.program_source_id)][str(row.source_key)] = {
                "id": str(row.source_key),
                "text": localized(payload, "learningOutcomeName", "name"),
                "code": clean(payload.get("code")),
            }
        for row in db.execute(text(
            "SELECT id, approved_course_id, source_keys, title_ru, title_kk, title_en, content_json "
            "FROM epvo_disciplines_normalized"
        )):
            item = {
                "id": int(row.approved_course_id or row.id),
                "title": {"ru": clean(row.title_ru), "kz": clean(row.title_kk), "en": clean(row.title_en)},
                "description": {},
            }
            content = row.content_json or {}
            for language in ("ru", "kk", "en"):
                value = clean(content.get(f"description_{language}") or (content.get("description") if language == "ru" else ""))
                if value:
                    item["description"]["kz" if language == "kk" else language] = value
            normalized[str(row.id)] = item
            for source_key in row.source_keys or []:
                normalized[str(source_key)] = item
        # Prefer the active, repaired localization layer over legacy JSON
        # descriptions.  This keeps ranking inputs in the same language-safe
        # state that the UI and repository expose.
        for row in db.execute(text(
            "SELECT course_id, language, title, description "
            "FROM course_localizations WHERE language IN ('ru','kk','en')"
        )):
            localized_courses[int(row.course_id)][str(row.language)] = {
                "title": clean(row.title),
                "description": clean(row.description),
            }
        for item in normalized.values():
            locs = localized_courses.get(int(item["id"]), {})
            for lang, loc in locs.items():
                item["title"]["kz" if lang == "kk" else lang] = loc.get("title") or item["title"].get("kz" if lang == "kk" else lang, "")
                if loc.get("description"):
                    item["description"]["kz" if lang == "kk" else lang] = loc["description"]
        for row in db.execute(text(
            "SELECT program_source_id, discipline_id, lo_source_key, strength "
            "FROM epvo_discipline_lo_links "
            f"WHERE program_source_id{programme_filter}"
            if programme_filter else
            "SELECT program_source_id, discipline_id, lo_source_key, strength "
            "FROM epvo_discipline_lo_links"
        ), programme_params):
            program_id = str(row.program_source_id)
            discipline_id = str(row.discipline_id)
            lo_id = str(row.lo_source_key)
            strength = float(row.strength or 0.0)
            if strength > 0:
                links[program_id].add((discipline_id, lo_id))
            link_strength[(program_id, discipline_id, lo_id)] = strength

    pair_count = 0
    programme_count = 0
    split_counts = defaultdict(int)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    pairs_path = output / "course_lo_pairs.jsonl"
    programs_path = output / "programs.jsonl"
    with pairs_path.open("w", encoding="utf-8") as pair_stream, programs_path.open("w", encoding="utf-8") as program_stream:
        for program_id, program in programmes.items():
            by_course: dict[str, dict] = {}
            source_to_course: dict[str, str] = {}
            for source_key, payload in disciplines.get(program_id, []):
                item = normalized.get(source_key)
                if not item:
                    item = {
                        "id": source_key,
                        "title": localized(payload, "name"),
                        "description": localized(payload, "briefinfo", "description"),
                    }
                course_id = str(item["id"])
                if not any(item.get("title", {}).values()):
                    continue
                by_course[course_id] = {"id": course_id, **item}
                source_to_course[source_key] = course_id
            positive_edges: set[tuple[str, str]] = set()
            for discipline_id, lo_id in links.get(program_id, set()):
                course_id = source_to_course.get(discipline_id, discipline_id)
                if course_id not in by_course or lo_id not in outcomes.get(program_id, {}):
                    continue
                positive_edges.add((course_id, lo_id))
            if len(positive_edges) < args.min_labelled_links or len(by_course) < 2:
                continue
            programme_count += 1
            split_counts[program["split"]] += 1
            row = {
                **program,
                "courses": list(by_course.values()),
                "outcomes": list(outcomes.get(program_id, {}).values()),
                "positive_edges": [list(edge) for edge in sorted(positive_edges)],
            }
            program_stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            for course_id, lo_id in row["positive_edges"]:
                pair_stream.write(json.dumps({
                    "program_id": program_id,
                    "split": program["split"],
                    "course_id": course_id,
                    "lo_id": lo_id,
                    "declared_link": True,
                    "expert_score": link_strength.get((program_id, course_id, lo_id), 1.0),
                }, ensure_ascii=False) + "\n")
                pair_count += 1
    manifest = {
        "source": "PostgreSQL raw_epvo_* + epvo_discipline_lo_links",
        "programmes": programme_count,
        "positive_pairs": pair_count,
        "split_counts": dict(split_counts),
        "database_dialect": engine.dialect.name,
        "status": "ready" if programme_count and pair_count else "empty",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0 if manifest["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
