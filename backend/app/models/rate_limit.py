"""Database-backed request rate-limit buckets for multi-worker deployments."""

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"

    bucket = Column(String(64), primary_key=True)
    client_key = Column(String(255), primary_key=True)
    window_start = Column(Integer, primary_key=True)
    event_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
