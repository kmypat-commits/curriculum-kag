"""Canonical immutable command snapshot for a planner build."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


def build_program_spec_snapshot(version: Any) -> dict[str, Any]:
    project = version.project
    outcomes = sorted(
        (
            {
                "code": str(lo.lo_code),
                "text": str(lo.lo_text),
                "taxonomy_level": str(lo.taxonomy_level or ""),
                "weight": float(lo.weight or 1.0),
                "order": int(lo.order_index or 0),
            }
            for lo in version.learning_outcomes
        ),
        key=lambda item: (item["order"], item["code"], item["text"]),
    )
    return {
        "schema_version": 1,
        "project_version_id": int(version.id),
        "version_number": int(version.version_number or 0),
        "title": str(project.title or ""),
        "goal": str(project.goal or ""),
        "domain1": str(project.domain1 or ""),
        "domain2": str(project.domain2 or ""),
        "constraints": deepcopy(project.constraints_json or {}),
        "learning_outcomes": outcomes,
    }


def program_spec_hash(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
