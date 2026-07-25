from sqlalchemy import Column, Integer, String, ForeignKey, JSON, Float, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base
from app.config import settings

# Attempt to import pgvector, fallback to Text if not available
try:
    from pgvector.sqlalchemy import Vector
    HAS_PGVECTOR = True
except ImportError:
    HAS_PGVECTOR = False
    Vector = None

class Embedding(Base):
    __tablename__ = "embeddings"
    
    id = Column(Integer, primary_key=True, index=True)
    chunk_id = Column(Integer, ForeignKey('course_chunks.id', ondelete='CASCADE'), unique=True, nullable=False)
    
    if HAS_PGVECTOR:
        vector = Column(Vector(settings.EMBEDDING_DIMENSION))
    else:
        vector = Column(Text)  # Store as string/JSON if pgvector not available
        
    model_version = Column(String, nullable=False)
    
    # Relationships
    chunk = relationship("CourseChunk", back_populates="embedding")


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    
    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, nullable=False, index=True)
    target_id = Column(Integer, nullable=False, index=True)
    edge_type = Column(String, nullable=False, index=True)  # course_teaches, course_covers, etc.
    properties_json = Column(JSON)
    weight = Column(Float, default=1.0)


class MatchScore(Base):
    __tablename__ = "match_scores"
    
    id = Column(Integer, primary_key=True, index=True)
    project_version_id = Column(Integer, ForeignKey('project_versions.id', ondelete='CASCADE'), nullable=False)
    course_id = Column(Integer, ForeignKey('courses.id', ondelete='CASCADE'))
    lo_id = Column(Integer, ForeignKey('learning_outcomes.id', ondelete='CASCADE'))
    chunk_id = Column(Integer, ForeignKey('course_chunks.id'))
    score = Column(Float, nullable=False, default=0.0)
    model_name = Column(String(255), nullable=True)
    model_version = Column(String(50), nullable=True)
    
    if HAS_PGVECTOR:
        vector = Column(Vector(settings.EMBEDDING_DIMENSION), nullable=True)
    else:
        vector = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    evidence_json = Column(JSON)  # List of chunk IDs and reasoning
    graph_path_json = Column(JSON)  # Graph traversal path if applicable


class MatchFeedback(Base):
    __tablename__ = "match_feedback"
    id = Column(Integer, primary_key=True)
    project_version_id = Column(Integer, ForeignKey('project_versions.id', ondelete='CASCADE'), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey('courses.id', ondelete='CASCADE'), nullable=False, index=True)
    lo_id = Column(Integer, ForeignKey('learning_outcomes.id', ondelete='CASCADE'), nullable=False, index=True)
    verdict = Column(String, nullable=False, index=True)  # confirmed/weak/incorrect/corrected
    corrected_score = Column(Float)
    comment = Column(Text)
    user_id = Column(Integer, ForeignKey('users.id'))
    model_snapshot_json = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
