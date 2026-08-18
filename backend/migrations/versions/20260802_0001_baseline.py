"""Baseline for the existing PostgreSQL schema.

The first production database pre-dated Alembic, so populated installations
must remain untouched.  A fresh PostgreSQL database, however, needs a real
bootstrap path for CI and reproducible deployments.  We create the registered
ORM schema only when the baseline tables do not exist; later revisions remain
ordinary forward migrations.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260802_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Existing production schema is the baseline; do not recreate populated
    # tables during deploy.  The guard makes clean CI/development databases
    # reproducible without changing a restored production database.
    if "projects" in inspector.get_table_names():
        return
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    from app.database import Base
    import app.models  # noqa: F401 - register all mapped tables
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    # Baseline is intentionally non-destructive and cannot be downgraded.
    pass
