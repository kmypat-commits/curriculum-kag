"""Store university baseline drafts and append-only confirmed revisions."""

from alembic import op
import sqlalchemy as sa

revision = "20261013_university_baselines"
down_revision = "20260914_planner_build_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "university_baseline_imports" not in tables:
        op.create_table(
            "university_baseline_imports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_version_id", sa.Integer(), sa.ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("source_name", sa.String(), nullable=False),
            sa.Column("source_sha256", sa.String(), nullable=False),
            sa.Column("source_bytes", sa.Integer(), nullable=False),
            sa.Column("rows_json", sa.JSON(), nullable=False),
            sa.Column("mapping_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_university_baseline_imports_project_version_id", "university_baseline_imports", ["project_version_id"])
        op.create_index("ix_university_baseline_imports_created_by", "university_baseline_imports", ["created_by"])
        op.create_index("ix_university_baseline_imports_status", "university_baseline_imports", ["status"])
    if "university_baseline_revisions" not in tables:
        op.create_table(
            "university_baseline_revisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_version_id", sa.Integer(), sa.ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("import_id", sa.Integer(), sa.ForeignKey("university_baseline_imports.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("revision_number", sa.Integer(), nullable=False),
            sa.Column("confirmed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("source_sha256", sa.String(), nullable=False),
            sa.Column("canonical_sha256", sa.String(), nullable=False),
            sa.Column("resolved_rows_json", sa.JSON(), nullable=False),
            sa.UniqueConstraint("project_version_id", "revision_number", name="uq_university_baseline_version_number"),
            sa.UniqueConstraint("import_id", name="uq_university_baseline_revision_import"),
        )
        op.create_index("ix_university_baseline_revisions_project_version_id", "university_baseline_revisions", ["project_version_id"])


def downgrade() -> None:
    op.drop_table("university_baseline_revisions")
    op.drop_table("university_baseline_imports")
