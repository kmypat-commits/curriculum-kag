"""Layered EPVO storage: immutable raw records and curated normalized data."""
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class RawEpvoProgram(Base):
    __tablename__ = "raw_epvo_programs"
    id = Column(Integer, primary_key=True)
    source_id = Column(String, unique=True, nullable=False, index=True)
    payload_json = Column(JSON, nullable=False)
    checksum = Column(String, nullable=False, index=True)
    collected_at = Column(DateTime(timezone=True), server_default=func.now())


class RawEpvoDiscipline(Base):
    __tablename__ = "raw_epvo_disciplines"
    id = Column(Integer, primary_key=True)
    program_source_id = Column(String, nullable=False, index=True)
    source_key = Column(String, nullable=False, index=True)
    payload_json = Column(JSON, nullable=False)
    checksum = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint("program_source_id", "source_key"),)


class RawEpvoLearningOutcome(Base):
    __tablename__ = "raw_epvo_learning_outcomes"
    id = Column(Integer, primary_key=True)
    program_source_id = Column(String, nullable=False, index=True)
    source_key = Column(String, nullable=False)
    payload_json = Column(JSON, nullable=False)
    checksum = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint("program_source_id", "source_key"),)


class RawEpvoExpertCheck(Base):
    __tablename__ = "raw_epvo_expert_checks"
    id = Column(Integer, primary_key=True)
    program_source_id = Column(String, nullable=False, index=True)
    discipline_source_key = Column(String, nullable=False)
    lo_source_key = Column(String, nullable=False)
    payload_json = Column(JSON, nullable=False)
    checksum = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint("program_source_id", "discipline_source_key", "lo_source_key"),)


class EpvoDirection(Base):
    __tablename__ = "epvo_directions"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False, index=True)
    title_ru = Column(String)
    title_kk = Column(String)
    title_en = Column(String)
    education_level = Column(String, index=True)
    status = Column(String, default="normalized", index=True)


class EpvoGroup(Base):
    __tablename__ = "epvo_groups"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False, index=True)
    direction_code = Column(String, ForeignKey("epvo_directions.code"), nullable=False, index=True)
    title_ru = Column(String)
    title_kk = Column(String)
    title_en = Column(String)
    status = Column(String, default="normalized", index=True)


class EpvoDisciplineNormalized(Base):
    __tablename__ = "epvo_disciplines_normalized"
    id = Column(Integer, primary_key=True)
    canonical_title = Column(String, nullable=False, index=True)
    title_ru = Column(String)
    title_kk = Column(String)
    title_en = Column(String)
    typical_credits = Column(Float)
    typical_semester = Column(Integer)
    direction_codes = Column(JSON, default=list)
    group_codes = Column(JSON, default=list)
    source_programs = Column(JSON, default=list)
    source_keys = Column(JSON, default=list)
    content_json = Column(JSON, default=dict)
    dedup_fingerprint = Column(String, unique=True, nullable=False, index=True)
    status = Column(String, default="normalized", index=True)  # raw/normalized/approved
    approved_course_id = Column(Integer, ForeignKey("courses.id"), nullable=True, index=True)


class EpvoDisciplineLoLink(Base):
    __tablename__ = "epvo_discipline_lo_links"
    id = Column(Integer, primary_key=True)
    discipline_id = Column(Integer, ForeignKey("epvo_disciplines_normalized.id", ondelete="CASCADE"), index=True)
    program_source_id = Column(String, nullable=False, index=True)
    lo_source_key = Column(String, nullable=False)
    strength = Column(Float)
    expert_level = Column(String)
    source = Column(String, default="epvo_expert")
    evidence_json = Column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("discipline_id", "program_source_id", "lo_source_key"),)


class EpvoPrerequisite(Base):
    __tablename__ = "epvo_prerequisites"
    id = Column(Integer, primary_key=True)
    source_discipline_id = Column(Integer, ForeignKey("epvo_disciplines_normalized.id", ondelete="CASCADE"), index=True)
    target_discipline_id = Column(Integer, ForeignKey("epvo_disciplines_normalized.id", ondelete="CASCADE"), index=True)
    relation_type = Column(String, default="prerequisite")
    confidence = Column(Float)
    evidence_json = Column(JSON, default=dict)
    status = Column(String, default="predicted", index=True)
    __table_args__ = (UniqueConstraint("source_discipline_id", "target_discipline_id", "relation_type"),)
