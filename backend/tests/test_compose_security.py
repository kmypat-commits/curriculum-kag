from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_local_compose_has_safe_dev_defaults_and_marks_local_environment():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "POSTGRES_USER: ${POSTGRES_USER:-curriculum_user}" in compose
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-local-dev-only-change-me}" in compose
    assert "POSTGRES_DB: ${POSTGRES_DB:-curriculum_kag}" in compose
    assert "SECRET_KEY: ${SECRET_KEY:-local-development-secret-change-me}" in compose
    assert "APP_ENV: local" in compose
    assert "docker-compose.production.yml" in compose or "Development-only defaults" in compose


def test_local_compose_keeps_reload_explicitly_local_only():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    production = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")

    assert "--reload" in compose
    assert "--reload" not in production


def test_production_compose_binds_health_to_domain_and_local_ports():
    production = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")

    assert "DOMAIN: ${DOMAIN:?set DOMAIN}" in production
    assert "headers={'Host': os.environ['DOMAIN']}" in production
    assert "127.0.0.1:${POSTGRES_PORT:-5433}:5432" in production
    assert "--workers ${WEB_CONCURRENCY:-1}" in production
