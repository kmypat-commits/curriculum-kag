"""Add durable planner build job and attempt history.

The old ``plan_build_status`` table remains the backwards-compatible current
status read model. New tables establish a stable public job identity and a
new fence token for every worker claim.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260908_planner_build_jobs"
down_revision = "20260908_build_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The baseline migration uses Base.metadata.create_all on a brand-new
    # database.  New ORM tables may therefore already exist before this
    # revision runs; only create them for a populated pre-Alembic database.
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "planner_build_jobs" not in tables:
        op.create_table(
            "planner_build_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("public_id", sa.String(), nullable=False, unique=True),
            sa.Column("project_version_id", sa.Integer(), sa.ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("request_hash", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=True),
            sa.Column("state", sa.String(), nullable=False),
            sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancel_requested", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        inspector = sa.inspect(op.get_bind())
    job_indexes = {index["name"] for index in inspector.get_indexes("planner_build_jobs")}
    for name, columns in (
        ("ix_planner_build_jobs_project_version_id", ["project_version_id"]),
        ("ix_planner_build_jobs_requested_by_user_id", ["requested_by_user_id"]),
        ("ix_planner_build_jobs_request_hash", ["request_hash"]),
        ("ix_planner_build_jobs_idempotency_key", ["idempotency_key"]),
        ("ix_planner_build_jobs_state", ["state"]),
    ):
        if name not in job_indexes:
            op.create_index(name, "planner_build_jobs", columns)
    active = sa.text("state IN ('queued', 'running', 'cancelling')")
    if "uq_planner_build_jobs_one_active_version" not in job_indexes:
        op.create_index(
            "uq_planner_build_jobs_one_active_version",
            "planner_build_jobs",
            ["project_version_id"],
            unique=True,
            sqlite_where=active,
            postgresql_where=active,
        )
    if "planner_build_attempts" not in tables:
        op.create_table(
            "planner_build_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("planner_build_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("owner_token", sa.String(), nullable=False, unique=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("job_id", "ordinal", name="uq_planner_build_attempt_job_ordinal"),
        )
        inspector = sa.inspect(op.get_bind())
    attempt_indexes = {index["name"] for index in inspector.get_indexes("planner_build_attempts")}
    for name, columns, unique in (
        ("ix_planner_build_attempts_job_id", ["job_id"], False),
        ("ix_planner_build_attempts_owner_token", ["owner_token"], True),
        ("ix_planner_build_attempts_state", ["state"], False),
        ("ix_planner_build_attempts_lease_expires_at", ["lease_expires_at"], False),
    ):
        if name not in attempt_indexes:
            op.create_index(name, "planner_build_attempts", columns, unique=unique)


def downgrade() -> None:
    op.drop_table("planner_build_attempts")
    op.drop_table("planner_build_jobs")
