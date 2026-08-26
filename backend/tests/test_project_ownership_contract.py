from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "app" / "api" / "projects.py"


def test_project_routes_enforce_owner_or_admin_contract():
    source = SOURCE.read_text(encoding="utf-8")
    assert "def _may_access_project" in source
    assert "has_role(current_user, \"admin\")" in source
    assert source.count("_require_project_access(current_user, project)") >= 3
    assert "query = query.filter(Project.created_by == current_user.id)" in source
