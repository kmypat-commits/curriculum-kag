"""Add shared request rate-limit buckets."""

from alembic import op
import sqlalchemy as sa


revision = "20260903_rate_limit_buckets"
down_revision = "20260902_build_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The baseline migration creates all registered ORM tables on a pristine
    # database.  Keep this revision idempotent for that path and for existing
    # installations that already have the shared limiter table.
    if "rate_limit_buckets" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "rate_limit_buckets",
        sa.Column("bucket", sa.String(length=64), nullable=False),
        sa.Column("client_key", sa.String(length=255), nullable=False),
        sa.Column("window_start", sa.Integer(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("bucket", "client_key", "window_start"),
    )


def downgrade() -> None:
    # The table may have been created by the non-destructive baseline; never
    # remove it as part of a downgrade.
    pass
