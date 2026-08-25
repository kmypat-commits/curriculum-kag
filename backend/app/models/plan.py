from sqlalchemy import Column, Integer, String, JSON, Float, ForeignKey, DateTime, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Plan(Base):
    __tablename__ = "plans"
    
    id = Column(Integer, primary_key=True, index=True)
    project_version_id = Column(Integer, ForeignKey('project_versions.id', ondelete='CASCADE'), nullable=False)
    variant_type = Column(String, nullable=False)  # A, B, C
    metrics_json = Column(JSON)  # Coverage, conflicts, new courses count, etc.
    is_active = Column(Integer, default=0)  # 0 or 1 for boolean in SQLite
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_plans_project_version_variant", "project_version_id", "variant_type"),
    )
    
    # Relationships
    project_version = relationship("ProjectVersion", back_populates="plans")
    items = relationship("PlanItem", back_populates="plan", cascade="all, delete-orphan")


class PlanItem(Base):
    __tablename__ = "plan_items"
    
    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey('plans.id', ondelete='CASCADE'), nullable=False)
    semester = Column(Integer, nullable=False)
    course_id = Column(Integer, ForeignKey('courses.id'))
    bridge_module_id = Column(Integer, ForeignKey('bridge_modules.id'))
    credits = Column(Integer, nullable=False)
    course_type = Column(String)  # mandatory, elective, practice, etc.
    prerequisites_snapshot = Column(JSON)  # Snapshot of prerequisites at plan creation

    __table_args__ = (
        Index("ix_plan_items_plan_semester", "plan_id", "semester"),
    )
    
    # Relationships
    plan = relationship("Plan", back_populates="items")
