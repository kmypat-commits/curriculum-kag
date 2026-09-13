from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func

from app.database import Base


class PlanBuildStatus(Base):
    """Durable progress snapshot for a plan build or match recomputation."""

    __tablename__ = "plan_build_status"

    id = Column(Integer, primary_key=True)
    project_version_id = Column(
        Integer,
        ForeignKey("project_versions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    state = Column(String, nullable=False, default="idle")
    stage = Column(String, nullable=False, default="idle")
    progress = Column(Integer, nullable=False, default=0)
    payload_json = Column(JSON, nullable=False, default=dict)
    # Public build identity belongs to a logical request, not to the short
    # lived OS process which happened to execute it.  The status row is still
    # only a current snapshot; attempt history is introduced separately.
    job_id = Column(String, nullable=True, unique=True, index=True)
    request_hash = Column(String, nullable=True, index=True)
    worker_id = Column(String, nullable=True, index=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    cancel_requested = Column(Integer, nullable=False, default=0)
    idempotency_key = Column(String, nullable=True, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
