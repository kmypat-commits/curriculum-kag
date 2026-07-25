"""Create compact program groups for leakage-safe course–LO link detection."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


def clean(value): return re.sub(r"\s+", " ", str(value or "")).strip()


def localized(record, prefix):
    return {lang: clean(record.get(prefix + suffix)) for lang, suffix in (("ru", "Ru"), ("kz", "Kz"), ("en", "En"))}


def split_for(program_id, seed):
    value = int(hashlib.sha256(f"{seed}:{program_id}".encode()).hexdigest()[:8], 16) % 100
    return "train" if value < 70 else "validation" if value < 85 else "test"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="experiment-results/epvo-full/raw/details")
    parser.add_argument("--output", default="experiment-results/epvo-link-dataset")
    parser.add_argument("--seed", type=int, default=42); args = parser.parse_args()
    source, output = Path(args.input), Path(args.output); output.mkdir(parents=True, exist_ok=True)
    target_tmp = output / "programs.jsonl.tmp"; counts, errors = Counter(), []
    with target_tmp.open("w", encoding="utf-8") as stream:
        for path in sorted(source.glob("*.json"), key=lambda p: int(p.stem)):
            try: data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc: errors.append({"file": path.name, "error": str(exc)}); continue
            program_id = str(data.get("id") or path.stem)
            outcomes = [{
                "id": str(lo.get("id")), "code": clean(lo.get("code")),
                "text": localized(lo, "learningOutcomeName"),
            } for lo in data.get("formedLearningOutcomes") or [] if lo.get("id") is not None]
            outcome_ids = {lo["id"] for lo in outcomes}; courses, edges = [], set()
            for course in data.get("disciplinesInfo") or []:
                if course.get("id") is None: continue
                course_id = str(course["id"])
                courses.append({
                    "id": course_id, "title": localized(course, "name"),
                    "description": {"ru": clean(course.get("briefinforu")), "kz": clean(course.get("briefinfo")), "en": clean(course.get("briefinfoen"))},
                    "credits": course.get("creditscount"), "year": course.get("year"), "term": course.get("term"),
                })
                for lo in course.get("learningOutcomes") or []:
                    lo_id = str(lo.get("id"))
                    if lo_id in outcome_ids: edges.add((course_id, lo_id))
            if not courses or not outcomes or not edges: continue
            stream.write(json.dumps({
                "program_id": program_id, "university_id": data.get("universityId"),
                "split": split_for(program_id, args.seed), "courses": courses, "outcomes": outcomes,
                "program_name": localized(data, "eduProgramName"),
                "program_goal": localized(data, "eduGoalName"),
                "training_direction": localized(data.get("trainingDirectionsObj") or {}, "name"),
                "program_group": localized(data.get("groupEduProgramObj") or {}, "name"),
                "positive_edges": sorted(edges), "source_file": path.name,
            }, ensure_ascii=False) + "\n")
            counts["programs"] += 1; counts["courses"] += len(courses); counts["outcomes"] += len(outcomes); counts["positive_edges"] += len(edges)
    target = output / "programs.jsonl"; target_tmp.replace(target)
    manifest = {"counts": dict(counts), "errors": errors, "seed": args.seed, "file": target.name, "status": "ready" if counts["programs"] and not errors else "needs_review"}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__": main()
