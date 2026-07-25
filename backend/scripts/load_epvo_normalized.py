"""Load immutable EPVO cards into raw tables and build a deduplicated catalog."""
import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "backend" / "experiment-results" / "epvo-full" / "raw" / "details"
DEFAULT_DB = ROOT / "backend" / "curriculum_kag.db"


def digest(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def normalized(value):
    return re.sub(r"[^0-9a-zа-яәіңғүұқөһ]+", " ", str(value or "").lower()).strip()


def packed(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--database", default=str(DEFAULT_DB))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    files = sorted(Path(args.source).glob("*.json"), key=lambda p: int(p.stem) if p.stem.isdigit() else p.stem)
    db = sqlite3.connect(args.database, timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    required = {"raw_epvo_programs", "raw_epvo_disciplines", "raw_epvo_learning_outcomes", "raw_epvo_expert_checks", "epvo_directions", "epvo_groups", "epvo_disciplines_normalized", "epvo_discipline_lo_links"}
    present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not required <= present:
        raise RuntimeError("EPVO schema is not initialized; restart the backend first")
    if args.resume:
        completed = db.execute("SELECT count(*) FROM raw_epvo_programs").fetchone()[0]
        files = files[completed:]
    if args.limit:
        files = files[:args.limit]
    stats = Counter()
    for index, path in enumerate(files, 1):
        program = json.loads(path.read_text(encoding="utf-8"))
        program_id = str(program.get("id") or path.stem)
        raw_json = packed(program)
        db.execute("INSERT INTO raw_epvo_programs(source_id,payload_json,checksum) VALUES(?,?,?) ON CONFLICT(source_id) DO UPDATE SET payload_json=excluded.payload_json,checksum=excluded.checksum", (program_id, raw_json, digest(program)))
        direction = program.get("trainingDirectionsObj") or {}
        direction_code = str(direction.get("codeDirection") or program.get("trainingDirectionsId") or "").strip()
        area = program.get("eduAreaObj") or {}
        if direction_code:
            db.execute("INSERT INTO epvo_directions(code,title_ru,title_kk,title_en,education_level,status) VALUES(?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET title_ru=excluded.title_ru,title_kk=excluded.title_kk,title_en=excluded.title_en", (direction_code, direction.get("nameRu"), direction.get("nameKz"), direction.get("nameEn"), area.get("classifierCode"), "normalized"))
        group = program.get("groupEduProgramObj") or {}
        group_code = str(group.get("code") or program.get("groupEduProgram") or "").strip()
        if group_code and direction_code:
            db.execute("INSERT INTO epvo_groups(code,direction_code,title_ru,title_kk,title_en,status) VALUES(?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET direction_code=excluded.direction_code,title_ru=excluded.title_ru,title_kk=excluded.title_kk,title_en=excluded.title_en", (group_code, direction_code, group.get("nameRu"), group.get("nameKz"), group.get("nameEn"), "normalized"))
        for outcome in program.get("formedLearningOutcomes") or []:
            source_key = str(outcome.get("id") or outcome.get("code") or digest(outcome)[:16])
            db.execute("INSERT INTO raw_epvo_learning_outcomes(program_source_id,source_key,payload_json,checksum) VALUES(?,?,?,?) ON CONFLICT(program_source_id,source_key) DO UPDATE SET payload_json=excluded.payload_json,checksum=excluded.checksum", (program_id, source_key, packed(outcome), digest(outcome)))
            stats["outcomes"] += 1
        for course in program.get("disciplinesInfo") or []:
            source_key = str(course.get("id") or course.get("subjectid") or digest(course)[:16])
            db.execute("INSERT INTO raw_epvo_disciplines(program_source_id,source_key,payload_json,checksum) VALUES(?,?,?,?) ON CONFLICT(program_source_id,source_key) DO UPDATE SET payload_json=excluded.payload_json,checksum=excluded.checksum", (program_id, source_key, packed(course), digest(course)))
            fingerprint = hashlib.sha256("|".join(normalized(course.get(key)) for key in ("nameRu", "nameKz", "nameEn")).encode("utf-8")).hexdigest()
            existing = db.execute("SELECT id,direction_codes,group_codes,source_programs,source_keys,typical_credits,typical_semester FROM epvo_disciplines_normalized WHERE dedup_fingerprint=?", (fingerprint,)).fetchone()
            credits = float(course.get("creditscount") or 0) or None
            semester = ((int(course.get("year") or 1) - 1) * 2 + int(course.get("term") or 1))
            content = {"description_ru": course.get("briefinforu"), "description_kk": course.get("briefinfo"), "description_en": course.get("briefinfoen")}
            if existing:
                discipline_id = existing[0]
                directions = sorted(set(json.loads(existing[1] or "[]") + ([direction_code] if direction_code else [])))
                groups = sorted(set(json.loads(existing[2] or "[]") + ([group_code] if group_code else [])))
                programs = sorted(set(json.loads(existing[3] or "[]") + [program_id]))
                keys = sorted(set(json.loads(existing[4] or "[]") + [source_key]))
                db.execute("UPDATE epvo_disciplines_normalized SET direction_codes=?,group_codes=?,source_programs=?,source_keys=? WHERE id=?", (packed(directions), packed(groups), packed(programs), packed(keys), discipline_id))
            else:
                canonical = course.get("nameRu") or course.get("nameKz") or course.get("nameEn") or source_key
                cursor = db.execute("INSERT INTO epvo_disciplines_normalized(canonical_title,title_ru,title_kk,title_en,typical_credits,typical_semester,direction_codes,group_codes,source_programs,source_keys,content_json,dedup_fingerprint,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (canonical, course.get("nameRu"), course.get("nameKz"), course.get("nameEn"), credits, semester, packed([direction_code] if direction_code else []), packed([group_code] if group_code else []), packed([program_id]), packed([source_key]), packed(content), fingerprint, "normalized"))
                discipline_id = cursor.lastrowid
                stats["normalized_new"] += 1
            for link in course.get("learningOutcomes") or []:
                lo_key = str(link.get("id") or link.get("code") or digest(link)[:16])
                check_payload = {"declared_link": True, "expert_level": link.get("level") or link.get("expertLevel"), "raw": link}
                db.execute("INSERT INTO raw_epvo_expert_checks(program_source_id,discipline_source_key,lo_source_key,payload_json,checksum) VALUES(?,?,?,?,?) ON CONFLICT(program_source_id,discipline_source_key,lo_source_key) DO UPDATE SET payload_json=excluded.payload_json,checksum=excluded.checksum", (program_id, source_key, lo_key, packed(check_payload), digest(check_payload)))
                db.execute("INSERT INTO epvo_discipline_lo_links(discipline_id,program_source_id,lo_source_key,strength,expert_level,source,evidence_json) VALUES(?,?,?,?,?,?,?) ON CONFLICT(discipline_id,program_source_id,lo_source_key) DO UPDATE SET strength=excluded.strength,expert_level=excluded.expert_level,evidence_json=excluded.evidence_json", (discipline_id, program_id, lo_key, 1.0, str(check_payload["expert_level"] or "declared"), "epvo_expert", packed(check_payload)))
                stats["links"] += 1
            stats["disciplines"] += 1
        stats["programs"] += 1
        if index % 50 == 0:
            db.commit()
            print(packed({"processed": index, "total": len(files)}), flush=True)
    db.commit()
    result = dict(stats)
    result["directions"] = db.execute("SELECT count(*) FROM epvo_directions").fetchone()[0]
    result["groups"] = db.execute("SELECT count(*) FROM epvo_groups").fetchone()[0]
    result["normalized_total"] = db.execute("SELECT count(*) FROM epvo_disciplines_normalized").fetchone()[0]
    db.close()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
