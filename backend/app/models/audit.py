from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    action = Column(String, nullable=False)  # create, update, delete, generate, etc.
    entity_type = Column(String, nullable=False)  # project, course, plan, bridge_module
    entity_id = Column(Integer)
    details_json = Column(JSON)  # Additional context
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
