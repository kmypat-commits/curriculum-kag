"""Durable, non-publishable planner output for methodist review."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class PlannerBuildDraft(Base):
    """A useful but infeasible result that must never become an active plan.

    The regular ``Plan`` table remains the verified publication boundary.  A
    separate table prevents a rejected schedule from being selected by legacy
    plan readers while retaining the concrete work a methodist can inspect.
    """

    __tablename__ = "planner_build_drafts"
    __table_args__ = (
        UniqueConstraint("job_id", "variant_type", name="uq_planner_build_draft_job_variant"),
        Index("ix_planner_build_drafts_version_created", "project_version_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    project_version_id = Column(
        Integer, ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id = Column(String, nullable=True, index=True)
    variant_type = Column(String, nullable=False)
    schedule_json = Column(JSON, nullable=False, default=dict)
    metrics_json = Column(JSON, nullable=False, default=dict)
    rejection_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
