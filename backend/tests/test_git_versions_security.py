from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "app" / "api" / "git_versions.py"


def test_git_version_routes_require_admin_role():
    source = SOURCE.read_text(encoding="utf-8")

    assert "def require_git_admin" in source
    assert "has_role(current_user, \"admin\")" in source
    assert source.count("Depends(require_git_admin)") == 4
