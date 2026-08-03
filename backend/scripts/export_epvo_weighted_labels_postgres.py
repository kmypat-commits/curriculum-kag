"""Export EPVO course--LO links with the original 0/0.5/1 expert scale.

The normalized link table intentionally stores only declared positive links.
This exporter reads the immutable raw discipline cards instead, where external
EPVO experts annotate each course--LO pair as rejected (0), medium (0.5), or
strong (1).  No production tables are modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

from sqlalchemy import create_engine, text


def clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def localized(payload: dict, prefixes: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for lang, suffixes in {
        "ru": ("Ru", "RU", "ru"),
        "kz": ("Kz", "KZ", "kk", "Kk"),
        "en": ("En", "EN", "en"),
    }.items():
        for prefix in prefixes:
            for suffix in suffixes:
                value = clean(payload.get(prefix + suffix))
                if value:
                    out[lang] = value
                    break
            if lang in out:
                break
    return out


def split_for(program_id: str, seed: int) -> str:
    bucket = int(hashlib.sha256(f"{seed}:{program_id}".encode()).hexdigest()[:8], 16) % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def score(value: object) -> float | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if number in (0.0, 0.5, 1.0) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    ap.add_argument("--output", type=Path, default=Path(".runtime/epvo-weighted-postgres"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-programmes", type=int, default=0)
    args = ap.parse_args()
    if not args.database_url:
        raise SystemExit("--database-url or DATABASE_URL is required")

    engine = create_engine(args.database_url, pool_pre_ping=True)
    args.output.mkdir(parents=True, exist_ok=True)
    outcomes: dict[str, dict[str, dict]] = defaultdict(dict)
    programs: dict[str, dict] = {}
    with engine.connect() as db:
        selected: set[str] | None = None
        if args.max_programmes > 0:
            selected = {str(row[0]) for row in db.execute(text(
                "SELECT DISTINCT program_source_id FROM raw_epvo_disciplines ORDER BY program_source_id LIMIT :limit"
            ), {"limit": args.max_programmes})}
        filter_sql = ""
        filter_params: dict[str, object] = {}
        if selected is not None:
            placeholders = ", ".join(f":selected_{i}" for i in range(len(selected)))
            filter_sql = f" WHERE program_source_id IN ({placeholders})"
            filter_params = {f"selected_{i}": value for i, value in enumerate(sorted(selected))}
        outcome_query = text(
            "SELECT program_source_id, source_key, payload_json FROM raw_epvo_learning_outcomes"
            + filter_sql
        )
        for row in db.execute(outcome_query, filter_params):
            payload = row.payload_json or {}
            outcomes[str(row.program_source_id)][str(row.source_key)] = {
                "id": str(row.source_key),
                "text": localized(payload, ("learningOutcomeName", "name")),
                "code": clean(payload.get("code")),
            }
        program_filter_sql = filter_sql.replace("program_source_id", "source_id")
        program_query = text("SELECT source_id, payload_json FROM raw_epvo_programs" + program_filter_sql)
        for row in db.execute(program_query, filter_params):
            payload = row.payload_json or {}
            area = payload.get("eduAreaObj") or {}
            direction = payload.get("trainingDirectionsObj") or {}
            group = payload.get("groupEduProgramObj") or {}
            programs[str(row.source_id)] = {
                "program_id": str(row.source_id),
                "split": split_for(str(row.source_id), args.seed),
                "name": localized(payload, ("eduProgramName", "name")),
                "goal": localized(payload, ("eduGoalName", "goal")),
                "training_direction": localized(direction, ("name",)),
                "program_group": localized(group, ("name",)),
                "education_area": localized(area, ("name",)),
                "training_direction_code": clean(direction.get("codeDirection")),
                "program_group_code": clean(group.get("code")),
                "education_level": clean(payload.get("eduType") or payload.get("academicDegree")),
                "credits": payload.get("creditsCount"),
            }

        if selected is None:
            selected = set(programs)
        else:
            selected &= set(programs)
        query_params: dict[str, object] = {}
        if args.max_programmes > 0:
            placeholders = ", ".join(f":program_{i}" for i in range(len(selected)))
            query = text(f"""SELECT program_source_id, source_key, payload_json
                          FROM raw_epvo_disciplines
                          WHERE program_source_id IN ({placeholders})
                          ORDER BY program_source_id, source_key""")
            query_params = {f"program_{i}": value for i, value in enumerate(sorted(selected))}
        else:
            query = text("""SELECT program_source_id, source_key, payload_json
                          FROM raw_epvo_disciplines
                          ORDER BY program_source_id, source_key""")
        stream = db.execute(query, query_params)
        pair_path = args.output / "course_lo_pairs.jsonl"
        program_path = args.output / "programs.jsonl"
        counts = defaultdict(int)
        current_program = None
        current_pairs: dict[tuple[str, str], dict] = {}
        current_courses = set()

        def flush(program_id: str | None, pair_out, program_out) -> None:
            if not program_id or program_id not in selected or not current_pairs:
                return
            info = programs.get(program_id, {"program_id": program_id, "split": split_for(program_id, args.seed)})
            rows = [row for row in current_pairs.values() if row.get("declared_link") or row.get("expert_score") is not None]
            if not rows:
                return
            for row in sorted(rows, key=lambda item: (item["course_id"], item["lo_id"])):
                pair_out.write(json.dumps({"program_id": program_id, "split": info.get("split"), **row}, ensure_ascii=False) + "\n")
                counts["pairs"] += 1
                if row.get("expert_score") is None:
                    counts["unlabeled_pairs"] += 1
                else:
                    counts["labeled_pairs"] += 1
                    counts[f"score_{row['expert_score']}"] += 1
            program_out.write(json.dumps({**info, "course_count": len(current_courses), "pair_count": len(rows)}, ensure_ascii=False) + "\n")
            counts["programs"] += 1

        with pair_path.open("w", encoding="utf-8") as pair_out, program_path.open("w", encoding="utf-8") as program_out:
            for row in stream:
                program_id = str(row.program_source_id)
                if program_id not in selected:
                    continue
                if current_program != program_id:
                    flush(current_program, pair_out, program_out)
                    current_program = program_id
                    current_pairs = {}
                    current_courses = set()
                payload = row.payload_json or {}
                course_id = str(row.source_key)
                current_courses.add(course_id)
                title = localized(payload, ("name",))
                description = {
                    "ru": clean(payload.get("briefinforu")),
                    "kz": clean(payload.get("briefinfo")),
                    "en": clean(payload.get("briefinfoen")),
                }
                declared_ids = {str(item.get("id")) for item in (payload.get("learningOutcomes") or []) if item.get("id") is not None}
                checks = payload.get("expertCheckResults") or []
                votes: dict[str, list[float]] = defaultdict(list)
                for item in checks:
                    value = score(item.get("result"))
                    lo_id = item.get("floId")
                    if value is not None and lo_id is not None:
                        votes[str(lo_id)].append(value)
                        counts[f"raw_vote_{value}"] += 1
                for lo_id in declared_ids | set(votes):
                    if lo_id not in outcomes[program_id]:
                        continue
                    key = (course_id, lo_id)
                    item = current_pairs.setdefault(key, {
                        "course_id": course_id,
                        "course_title": title,
                        "course_description": description,
                        "lo_id": lo_id,
                        "lo_code": outcomes[program_id][lo_id].get("code", ""),
                        "lo_text": outcomes[program_id][lo_id].get("text", {}),
                        "declared_link": False,
                        "expert_score": None,
                        "expert_votes": 0,
                    })
                    item["declared_link"] = item["declared_link"] or lo_id in declared_ids
                    if votes.get(lo_id):
                        item["expert_score"] = round(sum(votes[lo_id]) / len(votes[lo_id]), 4)
                        item["expert_votes"] = len(votes[lo_id])
            flush(current_program, pair_out, program_out)

    manifest = {
        "source": "PostgreSQL raw_epvo_disciplines.expertCheckResults + raw_epvo_learning_outcomes",
        "seed": args.seed,
        "counts": dict(counts),
        "label_meaning": {"0.0": "внешний эксперт отверг связь", "0.5": "средняя достижимость", "1.0": "высокая достижимость"},
        "status": "ready" if counts["labeled_pairs"] else "empty",
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    return 0 if manifest["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
