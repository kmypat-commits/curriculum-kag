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
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
