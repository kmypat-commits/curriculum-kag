"""Fail fast when the public planner request contract disappears from OpenAPI."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app


REQUIRED_SCHEMAS = {
    "PlannerBuildRequest",
    "SyllabusDraftRequest",
    "SemesterInsightRequest",
    "BridgeReplacementCandidate",
    "GenerateBridgeRequest",
    "LoAchievabilityRequest",
    "ApplyPriorityRequest",
    "BridgeReplacementSelection",
    "MatchFeedbackRequest",
    "PlanFeedbackRequest",
}
REQUIRED_OPERATIONS = {
    ("/planner/{project_version_id}/build", "post"),
    ("/planner/{project_version_id}/build-retry", "post"),
    ("/planner/{project_version_id}/performance", "get"),
    ("/planner/syllabus/draft/{kind}/{entity_id}", "post"),
    ("/planner/version/{project_version_id}/semester-insight", "post"),
    ("/kag/match-feedback", "post"),
    ("/kag/{project_version_id}/generate-bridge", "post"),
    ("/kag/{project_version_id}/lo-achievability", "post"),
    ("/epvo/projects/{project_id}/apply-priority", "post"),
    ("/planner/{project_version_id}/bridge-ai-replacement-apply", "post"),
    ("/planner/{project_version_id}/bridge-replacement-apply-all", "post"),
    ("/kag/{project_version_id}/plan-feedback", "post"),
}


def main() -> int:
    document = app.openapi()
    schemas = set((document.get("components") or {}).get("schemas") or {})
    paths = document.get("paths") or {}
    missing_schemas = sorted(REQUIRED_SCHEMAS - schemas)
    missing_operations = sorted(
        f"{method.upper()} {path}"
        for path, method in REQUIRED_OPERATIONS
        if method not in (paths.get(path) or {})
    )
    if missing_schemas or missing_operations:
        if missing_schemas:
            print("Missing OpenAPI schemas: " + ", ".join(missing_schemas))
        if missing_operations:
            print("Missing OpenAPI operations: " + ", ".join(missing_operations))
        return 1
    print(
        "OpenAPI planner contract passed: "
        f"{len(REQUIRED_SCHEMAS)} schemas, {len(REQUIRED_OPERATIONS)} operations"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
