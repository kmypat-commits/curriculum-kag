from sqlalchemy import Column, Integer, String, Text, JSON, Float, ForeignKey, Table, DateTime, UniqueConstraint, event
from sqlalchemy.orm import relationship, Session
from sqlalchemy.sql import func
from app.database import Base

# Association table for course prerequisites
course_prerequisites = Table(
    'course_prerequisites',
    Base.metadata,
    Column('course_id', Integer, ForeignKey('courses.id', ondelete='CASCADE')),
    Column('prerequisite_id', Integer, ForeignKey('courses.id', ondelete='CASCADE'))
)


class Course(Base):
    __tablename__ = "courses"
    
    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(String, unique=True, nullable=False, index=True)
    title = Column(String, nullable=False)
    domain = Column(String, nullable=False, index=True)  # D1, D2, general
    credits = Column(Integer, nullable=False)
    recommended_semester = Column(Integer)
    description = Column(Text)
    topics = Column(JSON)  # List of topics
    learning_outcomes = Column(JSON)  # List of course LOs
    assessment_methods = Column(JSON)
    language = Column(String, default="ru")
    cycle_component = Column(String)  # обязательный, вузовский, по выбору
    
    # Relationships
    prerequisites = relationship(
        "Course",
        secondary=course_prerequisites,
        primaryjoin=id == course_prerequisites.c.course_id,
        secondaryjoin=id == course_prerequisites.c.prerequisite_id,
        backref="postrequisites"
    )
    chunks = relationship("CourseChunk", back_populates="course", cascade="all, delete-orphan")


class CourseChunk(Base):
    __tablename__ = "course_chunks"
    
    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey('courses.id', ondelete='CASCADE'), nullable=False)
    chunk_type = Column(String, nullable=False)  # description, topics, learning_outcomes
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer)
    
    # Relationships
    course = relationship("Course", back_populates="chunks")
    embedding = relationship("Embedding", back_populates="chunk", uselist=False, cascade="all, delete-orphan")


class CourseLocalization(Base):
    __tablename__ = "course_localizations"

    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    language = Column(String, nullable=False, index=True)  # ru, kk, en
    title = Column(String, nullable=False)
    description = Column(Text)
    source = Column(String, nullable=False, default="manual", index=True)  # epvo, machine, manual, goso
    status = Column(String, nullable=False, default="draft", index=True)  # verified, draft, needs_review
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    course = relationship("Course", backref="localizations")

    __table_args__ = (UniqueConstraint("course_id", "language"),)


@event.listens_for(Session, "before_flush")
def ensure_new_course_localizations(session, _flush_context, _instances):
    """Every newly created discipline starts with explicit RU/KK/EN drafts.

    EPVO or expert translations can upgrade these rows to ``verified`` in the
    same transaction. This invariant prevents future repository imports,
    bridge promotion, and manual creation from producing untranslated courses.
    """
    new_courses = [row for row in session.new if isinstance(row, Course)]
    if not new_courses:
        return
    pending = {
        (id(row.course), row.language)
        for row in session.new
        if isinstance(row, CourseLocalization) and row.course is not None
    }
    for course in new_courses:
        for language in ("ru", "kk", "en"):
            if (id(course), language) in pending:
                continue
            session.add(CourseLocalization(
                course=course,
                language=language,
                title=course.title,
                description=course.description,
                source="automatic_course_draft",
                status="draft",
            ))
