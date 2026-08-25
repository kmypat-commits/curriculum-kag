"""Add composite indexes used by planner read endpoints."""

from alembic import op
import sqlalchemy as sa


revision = "20260825_planner_read_indexes"
down_revision = "20260817_plan_build_status"
branch_labels = None
depends_on = None


INDEXES = (
    ("ix_match_scores_version_course", "match_scores", ["project_version_id", "course_id"]),
    ("ix_match_scores_version_lo", "match_scores", ["project_version_id", "lo_id"]),
    ("ix_plans_project_version_variant", "plans", ["project_version_id", "variant_type"]),
    ("ix_plan_items_plan_semester", "plan_items", ["plan_id", "semester"]),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for name, table, columns in INDEXES:
        if table not in inspector.get_table_names():
            continue
        names = {row["name"] for row in inspector.get_indexes(table)}
        if name not in names:
            op.create_index(name, table, columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for name, table, _columns in reversed(INDEXES):
        if table not in inspector.get_table_names():
            continue
        names = {row["name"] for row in inspector.get_indexes(table)}
        if name in names:
            op.drop_index(name, table_name=table)
