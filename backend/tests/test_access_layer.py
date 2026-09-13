from types import SimpleNamespace

from app.services.access import may_access_project, require_plan_object_access
from app.services.rbac import check_permission, get_user_permissions, ROLE_POLICY
from app.services.program_profiles import profile_for
from app.config import Settings, validate_production_settings
from app.planner.goso_ruleset import GOSO_RULESET, GOSO_RULESET_CHECKSUM, GOSO_RULESET_VERSION, supports_profile
from app.planner.invariant_ledger import run_to_fixed_point
from app.planner.goso import evaluate_goso_compliance


def _user(user_id, role):
    return SimpleNamespace(id=user_id, roles=[SimpleNamespace(name=role, permissions=[])])


def _routes(routes, prefix=""):
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
            yield from _routes(route.original_router.routes, nested_prefix)
        else:
            yield route


def _effective_app_routes(app):
    for route in app.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is not None:
            yield from contexts()
        else:
            yield route


def test_object_access_is_owner_or_admin_only():
    project = SimpleNamespace(created_by=7)
    assert may_access_project(_user(7, "analyst"), project)
    assert not may_access_project(_user(8, "analyst"), project)
    assert may_access_project(_user(8, "admin"), project)


def test_permission_matrix_separates_readers_from_mutators():
    analyst = _user(8, "analyst")
    methodist = _user(7, "methodist")
    assert check_permission(analyst, "planner", "read")
    assert not check_permission(analyst, "repository", "write")
    assert check_permission(methodist, "repository", "write")
    assert check_permission(_user(99, "admin"), "anything", "anything")
    assert ("repository", "write") in ROLE_POLICY["methodist"]


def test_user_permission_payload_matches_effective_role_policy():
    permissions = get_user_permissions(_user(8, "analyst"))
    assert {f"{item['resource']}:{item['action']}" for item in permissions} >= {
        "repository:read", "planner:read", "export:read", "kag:read", "epvo:read",
    }


def test_user_without_loaded_permissions_has_safe_empty_extra_permissions():
    from app.services.rbac import get_user_permissions

    user = SimpleNamespace(id=10, roles=[SimpleNamespace(name="viewer")])
    assert get_user_permissions(user) == []


def test_supported_postgraduate_volume_profiles_follow_regulatory_matrix():
    for credits, semesters in ((60, 2), (90, 3)):
        constraints = {
            "education_level": "master", "master_track": "professional",
            "jurisdiction": "KZ", "total_credits": credits, "total_semesters": semesters,
        }
        assert profile_for(constraints) is not None
    assert profile_for({
        "education_level": "master", "master_track": "scientific_pedagogical",
        "jurisdiction": "KZ", "total_credits": 120, "total_semesters": 4,
    }) is not None
    assert profile_for({
        "education_level": "master", "master_track": "professional",
        "jurisdiction": "KZ", "total_credits": 120, "total_semesters": 4,
    }) is None
    for credits, semesters in ((60, 2), (90, 3), (120, 4)):
        assert profile_for({
            "education_level": "master", "master_track": "professional",
            "jurisdiction": "INTERNATIONAL", "total_credits": credits,
            "total_semesters": semesters,
        }) is not None


def test_unsupported_volume_profile_is_rejected_by_shared_table():
    assert profile_for({
        "education_level": "master", "master_track": "professional",
        "jurisdiction": "KZ", "total_credits": 75, "total_semesters": 3,
    }) is None


def test_profile_table_rejects_cross_product_credit_semester_pairs():
    assert profile_for({
        "education_level": "bachelor", "jurisdiction": "INTERNATIONAL",
        "total_credits": 180, "total_semesters": 8,
    }) is None


def test_doctorate_profiles_are_explicit_for_both_tracks():
    for track in ("scientific_pedagogical", "professional"):
        assert profile_for({
            "education_level": "doctorate", "doctorate_track": track,
            "jurisdiction": "KZ", "total_credits": 180, "total_semesters": 6,
        }) is not None


def test_doctorate_rejects_master_volume_shortcuts_for_both_jurisdictions():
    for jurisdiction in ("KZ", "INTERNATIONAL"):
        for track in ("scientific_pedagogical", "professional"):
            for credits, semesters in ((60, 2), (90, 3), (120, 4)):
                assert profile_for({
                    "education_level": "doctorate", "doctorate_track": track,
                    "jurisdiction": jurisdiction, "total_credits": credits,
                    "total_semesters": semesters,
                }) is None


def test_goso_ruleset_has_version_source_and_unique_rule_ids():
    assert GOSO_RULESET_VERSION == "KZ-GOSO-2026.05"
    assert GOSO_RULESET["source"]["url"].startswith("https://adilet.zan.kz/")
    ids = [rule["rule_id"] for rule in GOSO_RULESET["rules"]]
    assert ids and len(ids) == len(set(ids))
    assert len(GOSO_RULESET_CHECKSUM) == 64
    assert supports_profile({"education_level": "master", "master_track": "professional", "regulatory_profile": "KZ_GOSO_2026"})
    assert not supports_profile({"education_level": "master", "master_track": "professional", "regulatory_profile": "UNKNOWN_2026"})


def test_repair_fixed_point_is_bounded_and_terminates():
    state, iterations = run_to_fixed_point(0, lambda value: min(value + 1, 3), lambda value: value, max_iterations=5)
    assert state == 3 and iterations == 4


def test_production_settings_require_domain_host_and_https_safe_values():
    settings = Settings(
        DATABASE_URL="postgresql://user:pass@postgres:5432/test_db", SECRET_KEY="x" * 64,
            APP_ENV="production", DOMAIN="example.org",
            ALLOWED_HOSTS=["example.org"], CORS_ORIGINS=["https://example.org"],
            AUTH_COOKIE_SECURE=True, GIT_UI_ENABLED=False,
    )
    validate_production_settings(settings)
    settings.DOMAIN = "other.example.org"
    try:
        validate_production_settings(settings)
    except RuntimeError as error:
        assert "DOMAIN" in str(error)
    else:
        raise AssertionError("DOMAIN outside ALLOWED_HOSTS must be rejected")
    settings.DOMAIN = "example.org"
    settings.DATABASE_URL = "sqlite:///./unsafe-production.db"
    try:
        validate_production_settings(settings)
    except RuntimeError as error:
        assert "DATABASE_URL" in str(error)
    else:
        raise AssertionError("SQLite must be rejected in production")


def test_production_settings_reject_git_ui():
    settings = Settings(
        DATABASE_URL="postgresql://user:pass@postgres:5432/test_db",
        SECRET_KEY="x" * 64,
        APP_ENV="production",
        DOMAIN="example.org",
        ALLOWED_HOSTS=["example.org"],
        CORS_ORIGINS=["https://example.org"],
        AUTH_COOKIE_SECURE=True,
        GIT_UI_ENABLED=True,
    )
    try:
        validate_production_settings(settings)
    except RuntimeError as error:
        assert "GIT_UI_ENABLED" in str(error)
    else:
        raise AssertionError("Git UI must be disabled in production")


def test_production_settings_bound_cli_token_lifetime():
    base = dict(
        DATABASE_URL="postgresql://user:pass@postgres:5432/test_db",
        SECRET_KEY="x" * 64,
        APP_ENV="production",
        DOMAIN="example.org",
        ALLOWED_HOSTS=["example.org"],
        CORS_ORIGINS=["https://example.org"],
        AUTH_COOKIE_SECURE=True,
        GIT_UI_ENABLED=False,
    )
    try:
        validate_production_settings(Settings(**base, CLI_TOKEN_EXPIRE_MINUTES=241))
    except RuntimeError as error:
        assert "CLI_TOKEN_EXPIRE_MINUTES" in str(error)
    else:
        raise AssertionError("Production must bound CLI token lifetime")


def test_production_settings_reject_local_defaults_and_missing_domain():
    base = dict(
        DATABASE_URL="postgresql://user:pass@postgres:5432/test_db",
        SECRET_KEY="x" * 64,
        APP_ENV="production",
        AUTH_COOKIE_SECURE=True,
    )
    for settings in (
        Settings(**base, DOMAIN="", ALLOWED_HOSTS=["localhost"], CORS_ORIGINS=["http://localhost:3001"]),
        Settings(**base, DOMAIN="example.org", ALLOWED_HOSTS=["example.org"], CORS_ORIGINS=["http://localhost:3001"]),
    ):
        try:
            validate_production_settings(settings)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Production must not accept local defaults")


def test_production_settings_reject_nonpositive_request_and_rate_limits():
    base = dict(
        DATABASE_URL="postgresql://user:pass@postgres:5432/test_db",
        SECRET_KEY="x" * 64,
            APP_ENV="production", DOMAIN="example.org",
            ALLOWED_HOSTS=["example.org"], CORS_ORIGINS=["https://example.org"],
            AUTH_COOKIE_SECURE=True, GIT_UI_ENABLED=False,
    )
    for field in ("MAX_REQUEST_BYTES", "RATE_LIMIT_LOGIN_PER_MINUTE", "RATE_LIMIT_BUILD_PER_TEN_MINUTES", "RATE_LIMIT_EXPENSIVE_PER_TEN_MINUTES"):
        values = {**base, field: 0}
        try:
            validate_production_settings(Settings(**values))
        except RuntimeError as error:
            assert field in str(error) or "rate limits" in str(error)
        else:
            raise AssertionError(f"Production must reject nonpositive {field}")


def test_production_settings_reject_process_local_multiworker_rate_limits():
    settings = Settings(
        DATABASE_URL="postgresql://user:pass@postgres:5432/test_db",
        SECRET_KEY="x" * 64, APP_ENV="production", DOMAIN="example.org",
            ALLOWED_HOSTS=["example.org"], CORS_ORIGINS=["https://example.org"],
            AUTH_COOKIE_SECURE=True, GIT_UI_ENABLED=False, WEB_CONCURRENCY=2,
    )
    try:
        validate_production_settings(settings)
    except RuntimeError as error:
        assert "WEB_CONCURRENCY" in str(error)
    else:
        raise AssertionError("Production must not enable process-local multi-worker limits")


def test_verifier_never_marks_unknown_regulatory_profile_compliant():
    version = SimpleNamespace(project=SimpleNamespace(constraints_json={
        "jurisdiction": "KZ", "education_level": "master",
        "master_track": "professional", "regulatory_profile": "UNKNOWN_2026",
    }))
    result = evaluate_goso_compliance({}, version)
    assert result["compliant"] is False
    assert result["violations"][0]["reason"] == "unsupported_regulatory_profile"


def test_plan_routes_have_a_real_plan_ownership_dependency():
    from app.main import app

    route = next(route for route in _effective_app_routes(app) if route.path == "/planner/{plan_id}/toggle-active")
    names = {getattr(dep.call, "__name__", "") for dep in route.dependant.dependencies}
    assert "require_plan_object_access" in names


def test_planner_mutations_require_write_permission():
    from app.main import app

    paths = {
        "/planner/{project_version_id}/build",
        "/planner/{project_version_id}/build-retry",
        "/planner/{project_version_id}/build-cancel",
        "/planner/{project_version_id}/recompute-matches",
        "/planner/{project_version_id}/course-exclusions",
        "/planner/{plan_id}/toggle-active",
    }
    routes = [route for route in _effective_app_routes(app) if route.path in paths]
    assert len(routes) == len(paths)
    for route in routes:
        permissions = {
            getattr(dep.call, "__name__", "")
            for dep in route.dependant.dependencies
        }
        assert "check_permission" in permissions or any(
            "require_permission" in repr(dep.call) for dep in route.dependant.dependencies
        )


def test_syllabus_entity_routes_have_type_aware_access_dependency():
    from app.main import app

    routes = [route for route in _effective_app_routes(app) if route.path in {
        "/planner/syllabus/{kind}/{entity_id}",
        "/planner/syllabus/draft/{kind}/{entity_id}",
    }]
    assert len(routes) >= 3
    for route in routes:
        names = {getattr(dep.call, "__name__", "") for dep in route.dependant.dependencies}
        assert "require_syllabus_entity_access" in names


def test_evidence_bundle_has_plan_ownership_dependency():
    from app.main import app

    route = next(route for route in _effective_app_routes(app) if route.path == "/planner/{plan_id}/evidence-bundle")
    names = {getattr(dep.call, "__name__", "") for dep in route.dependant.dependencies}
    assert "require_plan_object_access" in names


def test_global_planner_mutations_require_write_permission():
    from app.main import app

    routes = [
        route for route in _effective_app_routes(app)
        if "POST" in (getattr(route, "methods", set()) or set())
        and route.path in {"/projects", "/projects/lo/weights"}
    ]
    assert len(routes) == 2
    for route in routes:
        names = {getattr(dep.call, "__name__", "") for dep in route.dependant.dependencies}
        assert "require_permission_planner_write" in names


def test_global_epvo_model_state_requires_read_permission():
    from app.main import app

    paths = {
        "/epvo/dataset-passport",
        "/epvo/dataset-passport/export.csv",
        "/epvo/reproducible-baseline",
        "/epvo/lstm-gnn-manifest",
        "/epvo/article-experiment-report",
        "/epvo/lstm-gnn-smoke/status",
        "/epvo/lstm-smoke/status",
    }
    routes = [route for route in _effective_app_routes(app) if route.path in paths]
    assert {route.path for route in routes} == paths
    for route in routes:
        names = {
            getattr(dep.call, "__name__", "")
            for dep in route.dependant.dependencies
        }
        assert "check_permission" in names or any(
            "require_permission" in repr(dep.call)
            for dep in route.dependant.dependencies
        )
