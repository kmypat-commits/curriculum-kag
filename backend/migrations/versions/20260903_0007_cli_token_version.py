"""Add per-user CLI token revocation version.

Revision ID: 20260903_cli_token_version
Revises: 20260903_rate_limit_buckets
"""

from alembic import op
import sqlalchemy as sa


revision = "20260903_cli_token_version"
down_revision = "20260903_rate_limit_buckets"
branch_labels = None
depends_on = None


def upgrade():
    # Keep the server default: SQLite cannot portably ALTER COLUMN after an
    # ADD COLUMN, and the default also makes the migration safe for existing
    # rows and out-of-band inserts.
    inspector = sa.inspect(op.get_bind())
    if "cli_token_version" in {column["name"] for column in inspector.get_columns("users")}:
        return
    op.add_column("users", sa.Column("cli_token_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    # The column may have been created by the baseline metadata bootstrap;
    # keep downgrade non-destructive for the documented rollback path.
    pass
