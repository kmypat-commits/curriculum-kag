"""Add durable leases for recoverable planner builds."""

from alembic import op
import sqlalchemy as sa


revision = "20260902_build_leases"
down_revision = "20260825_planner_read_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plan_build_status", sa.Column("worker_id", sa.String(), nullable=True))
    op.add_column("plan_build_status", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("plan_build_status", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("plan_build_status", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_plan_build_status_worker_id", "plan_build_status", ["worker_id"])
    op.create_index("ix_plan_build_status_lease_expires_at", "plan_build_status", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_plan_build_status_lease_expires_at", table_name="plan_build_status")
    op.drop_index("ix_plan_build_status_worker_id", table_name="plan_build_status")
    op.drop_column("plan_build_status", "attempt_count")
    op.drop_column("plan_build_status", "lease_expires_at")
    op.drop_column("plan_build_status", "heartbeat_at")
    op.drop_column("plan_build_status", "worker_id")
