from typing import Dict, List
import json
from sqlalchemy.orm import Session
from app.models.course import Course, CourseChunk
from app.models.embedding import Embedding, HAS_PGVECTOR
from app.kag.embedding_service import embedding_service


def chunk_course_content(course: Course) -> List[Dict[str, str]]:
    chunks = []
    if course.description and course.description.strip(): chunks.append({"chunk_type": "description", "chunk_text": course.description.strip()})
    if course.topics:
        text = " | ".join(course.topics) if isinstance(course.topics, list) else str(course.topics)
        if text.strip(): chunks.append({"chunk_type": "topics", "chunk_text": text.strip()})
    if course.learning_outcomes:
        text = " | ".join(course.learning_outcomes) if isinstance(course.learning_outcomes, list) else str(course.learning_outcomes)
        if text.strip(): chunks.append({"chunk_type": "learning_outcomes", "chunk_text": text.strip()})
    return chunks


def index_course(course: Course, db: Session) -> int:
    db.query(CourseChunk).filter(CourseChunk.course_id == course.id).delete(synchronize_session=False); db.flush()
    count = 0
    for index, data in enumerate(chunk_course_content(course)):
        chunk = CourseChunk(course_id=course.id, chunk_type=data["chunk_type"], chunk_text=data["chunk_text"], chunk_index=index)
        db.add(chunk); db.flush()
        vector = embedding_service.encode(data["chunk_text"]).tolist()
        db.add(Embedding(chunk_id=chunk.id, vector=vector if HAS_PGVECTOR else json.dumps(vector), model_version=embedding_service.get_model_version()))
        count += 1
    db.flush(); return count


def index_all_courses(db: Session) -> Dict[str, int]:
    courses = db.query(Course).all(); total_chunks = 0
    for course in courses: total_chunks += index_course(course, db)
    db.commit(); return {"total_courses": len(courses), "total_chunks": total_chunks, "model_version": embedding_service.get_model_version()}


def reindex_course(course_id: int, db: Session) -> int:
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course: raise ValueError(f"Course {course_id} not found")
    count = index_course(course, db); db.commit(); return count
