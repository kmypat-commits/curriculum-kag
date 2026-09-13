"""Store the immutable ProgramSpec command snapshot on planner jobs."""

from alembic import op
import sqlalchemy as sa


revision = "20260908_program_spec_snapshot"
down_revision = "20260908_planner_build_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("planner_build_jobs")}
    if "program_spec_json" not in columns:
        op.add_column("planner_build_jobs", sa.Column("program_spec_json", sa.JSON(), nullable=True))
    if "program_spec_hash" not in columns:
        op.add_column("planner_build_jobs", sa.Column("program_spec_hash", sa.String(), nullable=True))
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("planner_build_jobs")}
    if "ix_planner_build_jobs_program_spec_hash" not in indexes:
        op.create_index("ix_planner_build_jobs_program_spec_hash", "planner_build_jobs", ["program_spec_hash"])


def downgrade() -> None:
    pass
