from typing import List, Dict, Tuple
from sqlalchemy.orm import Session
from app.models.course import Course
from app.models.project import ProjectVersion
from app.models.embedding import MatchScore
from app.kag.scoring import calculate_semantic_similarity
from app.config import settings


def detect_duplicates(
    project_version_id: int,
    db: Session,
    threshold: float = None
) -> List[Dict]:
    """
    Detect duplicate/similar courses
    Returns list of course pairs with suggestions
    """
    if threshold is None:
        threshold = settings.SIMILARITY_THRESHOLD
    
    project_version = db.query(ProjectVersion).filter(
        ProjectVersion.id == project_version_id
    ).first()
    
    if not project_version:
        raise ValueError(f"Project version {project_version_id} not found")
    
    # Get all courses that have match scores for this project
    course_ids = db.query(MatchScore.course_id).filter(
        MatchScore.project_version_id == project_version_id
    ).distinct().all()
    
    course_ids = [cid[0] for cid in course_ids]
    courses = db.query(Course).filter(Course.id.in_(course_ids)).all()
    
    duplicates = []
    checked_pairs = set()
    
    for i, course1 in enumerate(courses):
        for course2 in courses[i+1:]:
            pair_key = tuple(sorted([course1.id, course2.id]))
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)
            
            # Calculate similarity
            text1 = f"{course1.description or ''} {' '.join(course1.topics or [])}"
            text2 = f"{course2.description or ''} {' '.join(course2.topics or [])}"
            
            similarity = calculate_semantic_similarity(text1, text2)
            
            if similarity >= threshold:
                # Check LO overlap
                los1 = set(db.query(MatchScore.lo_id).filter(
                    MatchScore.course_id == course1.id,
                    MatchScore.project_version_id == project_version_id
                ).all())
                
                los2 = set(db.query(MatchScore.lo_id).filter(
                    MatchScore.course_id == course2.id,
                    MatchScore.project_version_id == project_version_id
                ).all())
                
                lo_overlap = len(los1 & los2) / max(len(los1 | los2), 1)
                
                # Determine suggestion type
                suggestion_type = "merge" if lo_overlap > 0.7 else "adapt"
                
                duplicates.append({
                    "course1": {
                        "id": course1.id,
                        "code": course1.course_id,
                        "title": course1.title,
                        "domain": course1.domain,
                        "credits": course1.credits
                    },
                    "course2": {
                        "id": course2.id,
                        "code": course2.course_id,
                        "title": course2.title,
                        "domain": course2.domain,
                        "credits": course2.credits
                    },
                    "similarity": round(similarity, 3),
                    "lo_overlap": round(lo_overlap, 3),
                    "suggestion_type": suggestion_type,
                    "reasoning": generate_merge_reasoning(
                        course1, course2, similarity, lo_overlap, suggestion_type
                    )
                })
    
    return duplicates


def generate_merge_reasoning(
    course1: Course,
    course2: Course,
    similarity: float,
    lo_overlap: float,
    suggestion_type: str
) -> str:
    """Generate human-readable reasoning for merge/adapt suggestion"""
    if suggestion_type == "merge":
        return (
            f"Courses '{course1.title}' and '{course2.title}' have high content similarity "
            f"({similarity:.1%}) and cover similar learning outcomes ({lo_overlap:.1%} overlap). "
            f"Consider merging them into a single interdisciplinary course combining "
            f"{course1.domain} and {course2.domain} perspectives."
        )
    else:
        return (
            f"Courses '{course1.title}' and '{course2.title}' have similar content "
            f"({similarity:.1%}) but address different learning outcomes. "
            f"Consider adapting one course to incorporate topics from the other, "
            f"creating a bridge between {course1.domain} and {course2.domain}."
        )
