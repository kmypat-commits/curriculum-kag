"""Baseline for the existing PostgreSQL schema.

The production database was migrated from the verified SQLite/PostgreSQL
backup before Alembic was introduced.  This revision intentionally performs
no DDL: it records that exact schema as the migration starting point.  Future
schema changes must be added as normal forward/reversible revisions.
"""

from alembic import op


revision = "20260802_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing production schema is the baseline; do not recreate populated
    # tables during deploy.
    pass


def downgrade() -> None:
    # Baseline is intentionally non-destructive and cannot be downgraded.
    pass
