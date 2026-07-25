"""Extract scattered EPVO course–LO expert labels into a reproducible ML table."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def split_for(program_id: str, seed: int) -> str:
    bucket = int(hashlib.sha256(f"{seed}:{program_id}".encode()).hexdigest()[:8], 16) % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def score_value(value):
    try:
        score = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return score if score in {0.0, 0.5, 1.0} else None


def localized(record, prefix):
    return {
        "ru": clean(record.get(prefix + "Ru")),
        "kz": clean(record.get(prefix + "Kz")),
        "en": clean(record.get(prefix + "En")),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="experiment-results/epvo-full/raw/details")
    parser.add_argument("--output", default="experiment-results/epvo-expert-labels")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    source = Path(args.input)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    files = sorted(source.glob("*.json"), key=lambda path: int(path.stem))
    if args.limit:
        files = files[: args.limit]

    pairs_tmp = output / "course_lo_pairs.jsonl.tmp"
    programs_tmp = output / "programs.jsonl.tmp"
    counts, score_counts, errors = Counter(), Counter(), []
    with pairs_tmp.open("w", encoding="utf-8") as pair_stream, programs_tmp.open("w", encoding="utf-8") as program_stream:
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append({"file": path.name, "error": str(exc)})
                continue

            program_id = str(data.get("id") or path.stem)
            split = split_for(program_id, args.seed)
            outcomes = {str(lo.get("id")): lo for lo in data.get("formedLearningOutcomes") or []}
            disciplines = {str(course.get("id")): course for course in data.get("disciplinesInfo") or []}

            # One score can occur both below the discipline and below experts.
            # The composite key keeps one vote per expert/course/LO.
            votes = {}
            raw_results = []
            for course in disciplines.values():
                raw_results.extend(course.get("expertCheckResults") or [])
            for expert in data.get("experts") or []:
                raw_results.extend(expert.get("expertCheckResult") or [])
            for result in raw_results:
                score = score_value(result.get("result"))
                course_id, lo_id = str(result.get("disId")), str(result.get("floId"))
                if score is None or course_id not in disciplines or lo_id not in outcomes:
                    continue
                expert_id = str(result.get("repAppExpertId") or result.get("expertId") or "unknown")
                votes[(expert_id, course_id, lo_id)] = score

            votes_by_pair = defaultdict(list)
            for (_, course_id, lo_id), score in votes.items():
                votes_by_pair[(course_id, lo_id)].append(score)

            declared_pairs = set()
            for course_id, course in disciplines.items():
                for lo in course.get("learningOutcomes") or []:
                    lo_id = str(lo.get("id"))
                    if lo_id in outcomes:
                        declared_pairs.add((course_id, lo_id))

            # Keep scored pairs even if an old EPVO card omitted the parallel
            # learningOutcomes array; this preserves the expert ground truth.
            all_pairs = declared_pairs | set(votes_by_pair)
            for course_id, lo_id in sorted(all_pairs):
                course, lo = disciplines[course_id], outcomes[lo_id]
                pair_votes = votes_by_pair.get((course_id, lo_id), [])
                expert_score = round(sum(pair_votes) / len(pair_votes), 4) if pair_votes else None
                row = {
                    "program_id": program_id,
                    "university_id": data.get("universityId"),
                    "program_status": data.get("status"),
                    "split": split,
                    "course_id": course_id,
                    "course_title": localized(course, "name"),
                    "course_description": {
                        "ru": clean(course.get("briefinforu")),
                        "kz": clean(course.get("briefinfo")),
                        "en": clean(course.get("briefinfoen")),
                    },
                    "credits": course.get("creditscount"),
                    "year": course.get("year"),
                    "term": course.get("term"),
                    "lo_id": lo_id,
                    "lo_code": clean(lo.get("code")),
                    "lo_text": localized(lo, "learningOutcomeName"),
                    "declared_link": (course_id, lo_id) in declared_pairs,
                    "expert_score": expert_score,
                    "expert_votes": len(pair_votes),
                    "source_file": path.name,
                }
                pair_stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                counts["pairs"] += 1
                counts[f"pairs_{split}"] += 1
                if expert_score is None:
                    counts["unlabeled_pairs"] += 1
                else:
                    counts["labeled_pairs"] += 1
                    score_counts[str(expert_score)] += 1

            program_stream.write(json.dumps({
                "program_id": program_id,
                "university_id": data.get("universityId"),
                "status": data.get("status"),
                "split": split,
                "name": localized(data, "eduProgramName"),
                "goal": localized(data, "eduGoalName"),
                "credits": data.get("creditsCount"),
                "outcome_count": len(outcomes),
                "discipline_count": len(disciplines),
                "declared_pair_count": len(declared_pairs),
                "scored_pair_count": len(votes_by_pair),
                "source_file": path.name,
            }, ensure_ascii=False) + "\n")
            counts["programs"] += 1

    pairs_path, programs_path = output / "course_lo_pairs.jsonl", output / "programs.jsonl"
    pairs_tmp.replace(pairs_path)
    programs_tmp.replace(programs_path)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source.resolve()),
        "seed": args.seed,
        "counts": dict(counts),
        "expert_score_distribution": dict(score_counts),
        "errors": errors,
        "files": {"pairs": pairs_path.name, "programs": programs_path.name},
        "label_meaning": {"0.0": "expert rejected link", "0.5": "medium", "1.0": "high"},
        "status": "ready" if counts["labeled_pairs"] and not errors else "needs_review",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
