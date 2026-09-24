"""Freeze exact, policy-resolved TEM inputs without running the planner.

Refuse to guess a postgraduate track from a credit total when the source goal
does not state one. Exclusions are made before observing generation results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.program_profiles import profile_for


def resolve_track(row: dict) -> tuple[str | None, str]:
    level, credits = row["education_level"], int(row["credits"])
    if level == "bachelor" and credits == 240:
        return "standard", "KZ profile: bachelor 240 credits"
    if level == "master" and credits in (60, 90):
        return "professional", f"KZ profile: professional master {credits} credits"
    if level == "master" and credits == 120:
        return "scientific_pedagogical", "KZ profile: scientific-pedagogical master 120 credits"
    if level == "doctorate" and credits == 180:
        goal = str(row.get("goal_ru") or "").casefold()
        # Both doctoral tracks allow 180 credits. Only an explicit scientific
        # and pedagogical designation in the source resolves that ambiguity.
        if re.search(r"научно-педагог|научн\w*[\s-]+и[\s-]+педагог", goal):
            return "scientific_pedagogical", "source goal explicitly names scientific-pedagogical training"
        return None, "doctoral 180-credit track is not specified by the source"
    return None, "no unambiguous KZ profile for source credit total"


def prepare(row: dict) -> tuple[dict | None, str]:
    track, provenance = resolve_track(row)
    if track is None:
        return None, provenance
    direction = str(row.get("training_direction_code") or "").strip()
    group = str(row.get("program_group_code") or "").strip()
    if not re.fullmatch(r"[678][BMДD][0-9]{3}", direction) or not group:
        return None, "missing or invalid catalogue direction/group code"
    area = direction[:4]
    credits = int(row["credits"])
    semesters = credits // 30
    constraints = {
        "education_level": row["education_level"],
        "jurisdiction": "KZ",
        "regulatory_profile": "KZ_GOSO_2026",
        "program_type": "standard",
        "education_area": area,
        "direction_code": direction,
        "group_code": group,
        "instruction_language": "ru",
        "total_semesters": semesters,
        "total_credits": credits,
        "max_credits_per_semester": 30,
        "duration_years": semesters / 2,
        "credit_tolerance": 3,
        "min_domain1_percent": 40,
        "min_domain2_percent": 0,
        "allow_new_courses": True,
        "max_new_courses": 5,
    }
    if row["education_level"] == "master":
        constraints["master_track"] = track
    if row["education_level"] == "doctorate":
        constraints["doctorate_track"] = track
    if profile_for(constraints) is None:
        return None, "resolved constraints do not match versioned programme profile"
    outcomes = [
        {"code": str(item["code"]).strip(), "text": str(item["text"]).strip()}
        for item in row["learning_outcomes"]
    ]
    if len(outcomes) < 3 or len({item["code"] for item in outcomes}) != len(outcomes):
        return None, "missing or duplicate source learning outcomes"
    payload = {
        "source_program_id": str(row["program_id"]),
        "source_split": row["split"],
        "title": row["title_ru"],
        "goal": row["goal_ru"],
        "domain1": row["training_direction_ru"],
        "domain2": "",
        "audit_profile": "standard",
        "learning_outcomes": outcomes,
        "constraints": constraints,
        "constraint_provenance": provenance,
        # Prerequisite density is reported, not silently compared with an
        # unrelated ICT-specific control threshold.
        "quality_contract": {"min_prerequisite_edges": 0},
    }
    return payload, provenance


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.selection.read_text(encoding="utf-8"))
    actual_sha = hashlib.sha256(Path(source["source"]).read_bytes()).hexdigest()
    if actual_sha != source["source_sha256"]:
        parser.error("Source export SHA-256 changed since selection; refusing to prepare inputs")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prepared, excluded = [], []
    for row in source["programmes"]:
        payload, reason = prepare(row)
        if payload is None:
            excluded.append({"program_id": row["program_id"], "reason": reason})
            continue
        target = args.output_dir / f"program-{row['program_id']}.json"
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        target.write_bytes(encoded)
        prepared.append({
            "program_id": row["program_id"], "split": row["split"],
            "level": row["education_level"], "profile": "standard",
            "input": str(target), "sha256": hashlib.sha256(encoded).hexdigest(),
            "canonical_sha256": hashlib.sha256(json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest(),
            "constraint_provenance": reason,
        })
    manifest = {
        "status": "prepared_not_generated", "selection": str(args.selection),
        "source_sha256": actual_sha, "selected_count": len(source["programmes"]),
        "prepared_count": len(prepared), "excluded_count": len(excluded),
        "prepared": prepared, "excluded": excluded,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: manifest[key] for key in ("status", "selected_count", "prepared_count", "excluded_count", "excluded")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
