"""Persist public planner build identity and request hash.

The status table remains a current snapshot in this migration.  Its public
identifier is intentionally independent of an operating-system PID, making
it safe to expose in a client URL and to carry into the later job/attempt
history tables.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260908_build_identity"
down_revision = "20260903_cli_token_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("plan_build_status")}
    if "job_id" not in columns:
        op.add_column("plan_build_status", sa.Column("job_id", sa.String(), nullable=True))
    if "request_hash" not in columns:
        op.add_column("plan_build_status", sa.Column("request_hash", sa.String(), nullable=True))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("plan_build_status")}
    if "ix_plan_build_status_job_id" not in indexes:
        op.create_index("ix_plan_build_status_job_id", "plan_build_status", ["job_id"], unique=True)
    if "ix_plan_build_status_request_hash" not in indexes:
        op.create_index("ix_plan_build_status_request_hash", "plan_build_status", ["request_hash"])


def downgrade() -> None:
    # SQLite cannot portably drop columns.  Keeping this downgrade
    # non-destructive is safer than rebuilding a live planner-status table.
    pass
