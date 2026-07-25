"""Validate the future EP dataset and create leakage-safe deterministic splits."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


REQUIRED_PROGRAM_FIELDS = {
    "program_id", "university_id", "courses", "prerequisite_edges",
    "program_learning_outcomes", "source", "snapshot_date", "license_or_permission",
}
REQUIRED_COURSE_FIELDS = {"code", "title", "semester", "credits", "learning_outcomes"}


def split_for(program_id, seed):
    value = int(hashlib.sha256(f"{seed}:{program_id}".encode()).hexdigest()[:8], 16) % 100
    return "train" if value < 70 else "validation" if value < 85 else "test"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="experiment-results/ml-dataset")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    source = Path(args.input)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    names = ("train", "validation", "test")
    writers = {name: (output / f"{name}.jsonl").open("w", encoding="utf-8") for name in names}
    seen_programs, errors, counts = set(), [], Counter()
    try:
        with source.open(encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append({"line": line_number, "error": f"invalid_json: {exc}"})
                    continue
                missing = sorted(REQUIRED_PROGRAM_FIELDS - set(record))
                if missing:
                    errors.append({"line": line_number, "error": "missing_program_fields", "fields": missing})
                    continue
                program_id = str(record["program_id"])
                if program_id in seen_programs:
                    errors.append({"line": line_number, "error": "duplicate_program_id", "program_id": program_id})
                    continue
                seen_programs.add(program_id)
                programme_lo_codes = {
                    str(item.get("code") if isinstance(item, dict) else item)
                    for item in record["program_learning_outcomes"]
                }
                codes, valid = set(), True
                for course in record["courses"]:
                    course_missing = sorted(REQUIRED_COURSE_FIELDS - set(course))
                    if course_missing:
                        errors.append({"line": line_number, "error": "missing_course_fields", "fields": course_missing})
                        valid = False
                        break
                    code = str(course["code"])
                    if code in codes:
                        errors.append({"line": line_number, "error": "duplicate_course_code", "code": code})
                        valid = False
                        break
                    codes.add(code)
                    if int(course["semester"]) < 1 or int(course["credits"]) < 1:
                        errors.append({"line": line_number, "error": "invalid_semester_or_credits", "code": code})
                        valid = False
                        break
                    unknown_los = sorted(
                        str(value) for value in course["learning_outcomes"]
                        if str(value) not in programme_lo_codes
                    )
                    if unknown_los:
                        errors.append({"line": line_number, "error": "course_references_unknown_lo", "code": code, "count": len(unknown_los)})
                        valid = False
                        break
                if not valid:
                    continue
                bad_edges = [edge for edge in record["prerequisite_edges"] if len(edge) != 2 or edge[0] not in codes or edge[1] not in codes]
                if bad_edges:
                    errors.append({"line": line_number, "error": "edge_references_unknown_course", "count": len(bad_edges)})
                    continue
                split = split_for(program_id, args.seed)
                writers[split].write(json.dumps(record, ensure_ascii=False) + "\n")
                counts[split] += 1
    finally:
        for writer in writers.values():
            writer.close()

    manifest = {
        "source": str(source.resolve()), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "seed": args.seed, "counts": dict(counts), "valid_programs": sum(counts.values()),
        "errors": errors, "status": "ready" if not errors and sum(counts.values()) else "needs_correction",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "source": manifest["source"], "seed": args.seed, "counts": dict(counts),
        "valid_programs": manifest["valid_programs"], "error_count": len(errors),
        "first_errors": errors[:5], "status": manifest["status"],
    }, ensure_ascii=False, indent=2))
    raise SystemExit(0 if manifest["status"] == "ready" else 2)


if __name__ == "__main__":
    main()
