"""Validated metadata for the normative ГОСО ruleset."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path


RULESET_PATH = Path(__file__).resolve().parents[2] / "data" / "goso" / "goso-ruleset-2026.json"
REQUIRED_KEYS = {"schema_version", "ruleset_version", "jurisdiction", "effective_date", "source", "supported_profiles", "rules"}


def load_goso_ruleset() -> dict:
    data = json.loads(RULESET_PATH.read_text(encoding="utf-8"))
    missing = REQUIRED_KEYS - set(data)
    if missing or data.get("jurisdiction") != "KZ" or not data.get("ruleset_version"):
        raise RuntimeError(f"ГОСО ruleset schema is invalid: missing={sorted(missing)}")
    if not data.get("source", {}).get("url"):
        raise RuntimeError("ГОСО ruleset must contain a normative source URL")
    if any(not row.get("regulatory_profile") for row in data.get("supported_profiles", [])):
        raise RuntimeError("ГОСО ruleset profiles must identify their regulatory_profile")
    rule_ids = [rule.get("rule_id") for rule in data.get("rules", [])]
    if not rule_ids or len(rule_ids) != len(set(rule_ids)) or any(not value for value in rule_ids):
        raise RuntimeError("ГОСО ruleset must contain unique rule_id values")
    return data


GOSO_RULESET = load_goso_ruleset()
GOSO_RULESET_VERSION = GOSO_RULESET["ruleset_version"]
GOSO_RULESET_CHECKSUM = hashlib.sha256(
    json.dumps(GOSO_RULESET, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()


def supports_profile(constraints: dict) -> bool:
    level = str(constraints.get("education_level") or "").lower()
    track = str(constraints.get("master_track") or constraints.get("doctorate_track") or "standard").lower()
    if level == "bachelor":
        track = "standard"
    if track in {"profile", "specialized", "профильная"}:
        track = "professional"
    regulatory_profile = str(constraints.get("regulatory_profile") or "KZ_GOSO_2026").upper()
    return any(
        row["education_level"] == level and row["track"] == track and row.get("regulatory_profile") == regulatory_profile
        for row in GOSO_RULESET["supported_profiles"]
    )
