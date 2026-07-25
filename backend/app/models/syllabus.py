from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func

from app.database import Base


class SyllabusDraft(Base):
    __tablename__ = "syllabus_drafts"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String, nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)
    weeks = Column(Integer, nullable=False)
    contact_share = Column(Float, nullable=False)
    mode = Column(String, nullable=False)
    content_json = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default="draft")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
