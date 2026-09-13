"""Add cancellation and idempotency markers to planner builds."""

from alembic import op
import sqlalchemy as sa


revision = "20260902_build_control"
down_revision = "20260902_build_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plan_build_status", sa.Column("cancel_requested", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("plan_build_status", sa.Column("idempotency_key", sa.String(), nullable=True))
    op.create_index("ix_plan_build_status_idempotency_key", "plan_build_status", ["idempotency_key"])


def downgrade() -> None:
    op.drop_index("ix_plan_build_status_idempotency_key", table_name="plan_build_status")
    op.drop_column("plan_build_status", "idempotency_key")
    op.drop_column("plan_build_status", "cancel_requested")
