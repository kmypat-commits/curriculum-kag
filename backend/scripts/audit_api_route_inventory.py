"""Export the registered FastAPI route inventory for access-control review."""
from __future__ import annotations

import argparse
import json
import sys
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app


ACCESS_MARKERS = {
    "require_project_access",
    "require_project_object_access",
    "require_project_version_access",
    "require_version_access",
    "require_plan_access",
    "require_plan_object_access",
    "require_syllabus_entity_access",
    "require_permission",
    "require_git_admin",
}


def iter_registered_routes(routes, prefix=""):
    """Yield leaf routes across FastAPI's nested IncludedRouter tree."""
    for route in routes:
        if hasattr(route, "path"):
            if prefix:
                yield SimpleNamespace(
                    path=prefix + route.path,
                    methods=getattr(route, "methods", set()),
                    dependant=route.dependant,
                )
            else:
                yield route
        elif hasattr(route, "original_router"):
            context = getattr(route, "include_context", None)
            nested_prefix = prefix + (getattr(context, "prefix", "") if context else "")
            yield from iter_registered_routes(route.original_router.routes, nested_prefix)
        else:
            yield route


def iter_effective_app_routes(application):
    """Use FastAPI's effective contexts so include prefixes/dependencies merge."""
    for route in application.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is not None:
            yield from contexts()
        else:
            yield route


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    routes = []
    for route in iter_effective_app_routes(app):
        path = getattr(route, "path", None)
        methods = sorted(getattr(route, "methods", set()) or [])
        if not path or not methods:
            continue
        dependency_names = sorted({
            getattr(dep.call, "__name__", type(dep.call).__name__)
            for dep in getattr(route, "dependant", None).dependencies
        })
        object_parameters = [part[1:-1] for part in path.split("/") if part.startswith("{") and part.endswith("}")]
        access_markers = sorted(
            (set(dependency_names) & ACCESS_MARKERS)
            | {name for name in dependency_names if name.startswith("require_permission_")}
        )
        routes.append({
            "path": path,
            "methods": methods,
            "object_parameters": object_parameters,
            "access_markers": access_markers,
            "dependencies": dependency_names,
        })
    routes.sort(key=lambda item: (item["path"], item["methods"]))
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "route_count": len(routes),
        "object_scoped_route_count": sum(bool(item["object_parameters"]) for item in routes),
        "routes": routes,
        "review_note": "Routes without an access marker require explicit documented global-read policy or manual ownership proof.",
    }
    unprotected_object_routes = [
        item for item in routes
        if item["object_parameters"] and not item["access_markers"]
    ]
    payload["unprotected_object_scoped_routes"] = unprotected_object_routes
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "route_count": payload["route_count"],
        "object_scoped_route_count": payload["object_scoped_route_count"],
        "unprotected_object_scoped_route_count": len(unprotected_object_routes),
    }, ensure_ascii=False))
    if unprotected_object_routes:
        print(
            "Unprotected object-scoped routes detected: "
            + ", ".join(item["path"] for item in unprotected_object_routes),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
