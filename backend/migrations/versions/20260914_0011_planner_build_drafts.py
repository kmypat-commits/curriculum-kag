"""Preserve rejected planner schedules as non-publishable methodist drafts."""

from alembic import op
import sqlalchemy as sa


revision = "20260914_planner_build_drafts"
down_revision = "20260908_program_spec_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "planner_build_drafts" not in set(inspector.get_table_names()):
        op.create_table(
            "planner_build_drafts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_version_id", sa.Integer(), sa.ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("job_id", sa.String(), nullable=True),
            sa.Column("variant_type", sa.String(), nullable=False),
            sa.Column("schedule_json", sa.JSON(), nullable=False),
            sa.Column("metrics_json", sa.JSON(), nullable=False),
            sa.Column("rejection_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("job_id", "variant_type", name="uq_planner_build_draft_job_variant"),
        )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("planner_build_drafts")}
    for name, columns in (
        ("ix_planner_build_drafts_project_version_id", ["project_version_id"]),
        ("ix_planner_build_drafts_created_by_user_id", ["created_by_user_id"]),
        ("ix_planner_build_drafts_job_id", ["job_id"]),
        ("ix_planner_build_drafts_version_created", ["project_version_id", "created_at"]),
    ):
        if name not in indexes:
            op.create_index(name, "planner_build_drafts", columns)


def downgrade() -> None:
    op.drop_table("planner_build_drafts")
