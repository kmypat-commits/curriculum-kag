"""Durable planner build command and execution-attempt history.

``PlanBuildStatus`` remains the compact current read model used by the
existing polling API. These tables are the write-side record: a logical job
has a stable public id, while every worker claim receives a distinct owner
token/attempt row.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class PlannerBuildJob(Base):
    __tablename__ = "planner_build_jobs"

    id = Column(Integer, primary_key=True)
    public_id = Column(String, nullable=False, unique=True, index=True)
    project_version_id = Column(
        Integer, ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    request_hash = Column(String, nullable=False, index=True)
    program_spec_json = Column(JSON, nullable=True)
    program_spec_hash = Column(String, nullable=True, index=True)
    idempotency_key = Column(String, nullable=True, index=True)
    state = Column(String, nullable=False, default="queued", index=True)
    queued_at = Column(DateTime(timezone=True), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    deadline_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    cancel_requested = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PlannerBuildAttempt(Base):
    __tablename__ = "planner_build_attempts"
    __table_args__ = (UniqueConstraint("job_id", "ordinal", name="uq_planner_build_attempt_job_ordinal"),)

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("planner_build_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    ordinal = Column(Integer, nullable=False)
    owner_token = Column(String, nullable=False, unique=True, index=True)
    state = Column(String, nullable=False, default="running", index=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    failure_code = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
