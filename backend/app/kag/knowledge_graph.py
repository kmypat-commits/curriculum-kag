"""Persistent Curriculum Knowledge Graph used by Curriculum-KAG."""
from datetime import datetime, timezone
from typing import Dict, List, Optional
import json
import numpy as np
from sqlalchemy import distinct
from sqlalchemy.orm import Session
from app.models.course import Course, CourseChunk
from app.models.embedding import Embedding, GraphEdge, MatchScore
from app.kag.embedding_service import embedding_service

LO_NODE_OFFSET = 1_000_000_000

def lo_node_id(lo_id: int) -> int:
    return -(LO_NODE_OFFSET + int(lo_id))


def build_knowledge_graph(db: Session, similarity_threshold: float = 0.72, project_version_id: Optional[int] = None) -> Dict:
    db.query(GraphEdge).delete(synchronize_session=False); db.flush()
    courses = db.query(Course).all(); edge_count = 0
    for course in courses:
        for prereq in course.prerequisites:
            db.add(GraphEdge(source_id=course.id, target_id=prereq.id, edge_type="PREREQUISITE", weight=1.0, properties_json={"source_type": "course", "target_type": "course", "source_code": course.course_id, "target_code": prereq.course_id}))
            edge_count += 1
    vectors = _build_course_vectors(courses, db); ids = list(vectors)
    for index, cid1 in enumerate(ids):
        v1 = vectors[cid1]; n1 = np.linalg.norm(v1)
        if n1 < 1e-9: continue
        for cid2 in ids[index + 1:]:
            v2 = vectors[cid2]; n2 = np.linalg.norm(v2)
            if n2 < 1e-9: continue
            similarity = float(np.dot(v1, v2) / (n1 * n2))
            if similarity >= similarity_threshold:
                db.add(GraphEdge(source_id=cid1, target_id=cid2, edge_type="DOMAIN_SIMILAR", weight=round(similarity, 4), properties_json={"source_type": "course", "target_type": "course", "similarity": round(similarity, 4)})); edge_count += 1
    query = db.query(MatchScore).filter(MatchScore.score >= 0.4)
    if project_version_id is not None: query = query.filter(MatchScore.project_version_id == project_version_id)
    for score in query.all():
        if score.course_id is None or score.lo_id is None: continue
        db.add(GraphEdge(source_id=score.course_id, target_id=lo_node_id(score.lo_id), edge_type="COVERS_LO", weight=round(score.score, 4), properties_json={"source_type": "course", "target_type": "learning_outcome", "lo_id": score.lo_id, "project_version_id": score.project_version_id, "score": score.score})); edge_count += 1
    db.commit(); stats = get_graph_stats(db)
    stats.update({"courses_with_embeddings": len(vectors), "embedding_model": embedding_service.get_model_version(), "rebuilt_at": datetime.now(timezone.utc).isoformat()})
    return stats


def get_graph_neighbors(course_id: int, db: Session, edge_types: Optional[List[str]] = None, max_hops: int = 2, max_neighbors: int = 30) -> List[Dict]:
    edge_types = edge_types or ["PREREQUISITE", "DOMAIN_SIMILAR"]
    visited, queue = {}, [(course_id, 0)]
    while queue and len(visited) < max_neighbors:
        current, hop = queue.pop(0)
        if hop >= max_hops: continue
        edges = db.query(GraphEdge).filter(GraphEdge.edge_type.in_(edge_types), ((GraphEdge.source_id == current) | (GraphEdge.target_id == current))).all()
        for edge in edges:
            neighbor = edge.target_id if edge.source_id == current else edge.source_id
            if neighbor <= 0 or neighbor == course_id or neighbor in visited: continue
            relation = edge.edge_type if edge.source_id == current else edge.edge_type + "_REV"
            visited[neighbor] = {"course_id": neighbor, "edge_type": relation, "weight": edge.weight, "hop": hop + 1}
            queue.append((neighbor, hop + 1))
    return list(visited.values())


def get_prerequisite_closure(course_id: int, db: Session) -> List[int]:
    closure, queue = set(), [course_id]
    while queue:
        current = queue.pop()
        for edge in db.query(GraphEdge).filter(GraphEdge.source_id == current, GraphEdge.edge_type == "PREREQUISITE").all():
            if edge.target_id not in closure: closure.add(edge.target_id); queue.append(edge.target_id)
    return list(closure)


def get_graph_stats(db: Session) -> Dict:
    total_courses = db.query(Course).count(); total_edges = db.query(GraphEdge).count()
    prereq = db.query(GraphEdge).filter(GraphEdge.edge_type == "PREREQUISITE").count(); similar = db.query(GraphEdge).filter(GraphEdge.edge_type == "DOMAIN_SIMILAR").count(); lo_edges = db.query(GraphEdge).filter(GraphEdge.edge_type == "COVERS_LO").count()
    course_nodes = {
        row[0] for row in db.query(distinct(GraphEdge.source_id)).filter(GraphEdge.source_id > 0).all()
    }
    course_nodes.update(
        row[0] for row in db.query(distinct(GraphEdge.target_id)).filter(GraphEdge.target_id > 0).all()
    )
    return {"total_courses": total_courses, "total_edges": total_edges, "prerequisite_edges": prereq, "similarity_edges": similar, "lo_coverage_edges": lo_edges, "connected_nodes": len(course_nodes), "graph_density": round((prereq + similar) / max(1, total_courses * (total_courses - 1)), 6), "graph_built": total_edges > 0}


def _build_course_vectors(courses: List[Course], db: Session) -> Dict[int, np.ndarray]:
    model_version = embedding_service.get_model_version(); result = {}
    for course in courses:
        rows = db.query(CourseChunk, Embedding).join(Embedding, Embedding.chunk_id == CourseChunk.id).filter(CourseChunk.course_id == course.id, Embedding.model_version == model_version).all()
        vectors = []
        for _, embedding in rows:
            try: vectors.append(np.array(json.loads(embedding.vector) if isinstance(embedding.vector, str) else embedding.vector, dtype=np.float32))
            except Exception: continue
        if vectors: result[course.id] = np.mean(vectors, axis=0).astype(np.float32)
    return result
