"""Append-only university baseline imports and confirmed revisions."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class UniversityBaselineImport(Base):
    __tablename__ = "university_baseline_imports"
    id = Column(Integer, primary_key=True)
    project_version_id = Column(Integer, ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    source_name = Column(String, nullable=False)
    source_sha256 = Column(String, nullable=False)
    source_bytes = Column(Integer, nullable=False)
    rows_json = Column(JSON, nullable=False)
    mapping_json = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default="draft", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UniversityBaselineRevision(Base):
    __tablename__ = "university_baseline_revisions"
    __table_args__ = (UniqueConstraint("project_version_id", "revision_number", name="uq_university_baseline_version_number"), UniqueConstraint("import_id", name="uq_university_baseline_revision_import"))
    id = Column(Integer, primary_key=True)
    project_version_id = Column(Integer, ForeignKey("project_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    import_id = Column(Integer, ForeignKey("university_baseline_imports.id", ondelete="RESTRICT"), nullable=False)
    revision_number = Column(Integer, nullable=False)
    confirmed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source_sha256 = Column(String, nullable=False)
    canonical_sha256 = Column(String, nullable=False)
    resolved_rows_json = Column(JSON, nullable=False)
