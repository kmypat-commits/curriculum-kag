"""Persist curriculum build progress.

Revision ID: 20260817_plan_build_status
Revises: 20260802_baseline
"""

from alembic import op
import sqlalchemy as sa


revision = "20260817_plan_build_status"
down_revision = "20260802_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "plan_build_status" not in inspector.get_table_names():
        op.create_table(
            "plan_build_status",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "project_version_id",
                sa.Integer(),
                sa.ForeignKey("project_versions.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("state", sa.String(), nullable=False, server_default="idle"),
            sa.Column("stage", sa.String(), nullable=False, server_default="idle"),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        inspector = sa.inspect(bind)
    index_names = {index["name"] for index in inspector.get_indexes("plan_build_status")}
    if "ix_plan_build_status_project_version_id" not in index_names:
        op.create_index("ix_plan_build_status_project_version_id", "plan_build_status", ["project_version_id"])


def downgrade() -> None:
    op.drop_index("ix_plan_build_status_project_version_id", table_name="plan_build_status")
    op.drop_table("plan_build_status")
