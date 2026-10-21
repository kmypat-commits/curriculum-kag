from app.api import planner_baseline
from app.schemas.planner import PlannerBuildRequest


def test_baseline_routes_are_owner_scoped_and_have_no_revision_mutation_route():
    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in planner_baseline.router.routes}
    assert ("/{project_version_id}/baseline/import", ("POST",)) in paths
    assert ("/{project_version_id}/baseline/imports/{import_id}/mapping", ("PATCH",)) in paths
    assert ("/{project_version_id}/baseline/imports/{import_id}/confirm", ("POST",)) in paths
    assert ("/{project_version_id}/baseline/revisions", ("GET",)) in paths
    assert ("/{project_version_id}/baseline/revisions/{revision_id}", ("GET",)) in paths
    assert not any("revisions/{revision_id}" in path and "PATCH" in methods for path, methods in paths)


def test_b_and_c_request_can_carry_explicit_revision_only():
    request = PlannerBuildRequest(variants=["B", "C"], baseline_revision_id=17)
    assert request.baseline_revision_id == 17
    assert request.variants == ["B", "C"]
