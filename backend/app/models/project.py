from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Project(Base):
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    domain1 = Column(String, nullable=False)  # Primary domain
    domain2 = Column(String, nullable=False)  # Secondary domain
    goal = Column(Text)
    constraints_json = Column(JSON)  # Stores all constraints
    created_by = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    versions = relationship("ProjectVersion", back_populates="project", cascade="all, delete-orphan")


class ProjectVersion(Base):
    __tablename__ = "project_versions"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    version_number = Column(Integer, nullable=False)
    status = Column(String, default="draft")  # draft, in_progress, completed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    project = relationship("Project", back_populates="versions")
    learning_outcomes = relationship("LearningOutcome", back_populates="project_version", cascade="all, delete-orphan")
    plans = relationship("Plan", back_populates="project_version", cascade="all, delete-orphan")


class LearningOutcome(Base):
    __tablename__ = "learning_outcomes"
    
    id = Column(Integer, primary_key=True, index=True)
    project_version_id = Column(Integer, ForeignKey('project_versions.id', ondelete='CASCADE'), nullable=False)
    lo_code = Column(String, nullable=False)  # LO1, LO2, etc.
    lo_text = Column(Text, nullable=False)
    taxonomy_level = Column(String)  # Bloom's taxonomy level
    weight = Column(Float, default=1.0) # Importance weight (0.5 to 2.0)
    order_index = Column(Integer)
    
    # Relationships
    project_version = relationship("ProjectVersion", back_populates="learning_outcomes")
