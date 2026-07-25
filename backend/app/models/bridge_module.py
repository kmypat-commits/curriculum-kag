from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class BridgeModule(Base):
    __tablename__ = "bridge_modules"
    
    id = Column(Integer, primary_key=True, index=True)
    project_version_id = Column(Integer, ForeignKey('project_versions.id', ondelete='CASCADE'), nullable=False)
    course_id = Column(String, unique=True, nullable=False)  # Generated ID
    title = Column(String, nullable=False)
    goal = Column(Text)
    description = Column(Text)
    credits = Column(Integer, nullable=False)
    recommended_semester = Column(Integer)
    
    # Generated content
    learning_outcomes = Column(JSON)  # List of 5-8 LOs
    topics = Column(JSON)  # List of 12-15 weekly topics
    prerequisites = Column(JSON)  # List of prerequisite course IDs
    assessment_methods = Column(JSON)
    
    # Provenance
    source_chunks_json = Column(JSON)  # Evidence chunks used
    generation_params_json = Column(JSON)  # LLM parameters
    target_los = Column(JSON)  # Which program LOs this addresses
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(Integer, ForeignKey('users.id'))
