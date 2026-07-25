from typing import List, Dict, Tuple, Optional
from collections import Counter
import math
import re
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models.course import Course, CourseChunk
from app.models.embedding import Embedding, GraphEdge
from app.models.project import LearningOutcome
from app.kag.embedding_service import embedding_service
from app.config import settings


def retrieve_top_k_courses(
    lo: LearningOutcome,
    db: Session,
    k: int = None,
    domain_filter: List[str] = None
) -> List[Dict]:
    """
    Retrieve top-k courses most relevant to a learning outcome
    """
    if k is None:
        k = settings.TOP_K_RETRIEVAL
    
    from app.models.embedding import HAS_PGVECTOR
    
    if HAS_PGVECTOR and not str(settings.DATABASE_URL).startswith("sqlite"):
        # Original PGVector implementation (previous code logic)
        lo_embedding = embedding_service.encode(lo.lo_text)
        query = text("""
            SELECT 
                c.id, c.course_id, c.title, c.domain, c.credits,
                cc.id as chunk_id, cc.chunk_type, cc.chunk_text,
                1 - (e.vector <=> :lo_vector) as similarity
            FROM courses c
            JOIN course_chunks cc ON cc.course_id = c.id
            JOIN embeddings e ON e.chunk_id = cc.id
            WHERE (:domain_filter IS NULL OR c.domain = ANY(:domain_filter))
            ORDER BY e.vector <=> :lo_vector
            LIMIT :k
        """)
        params = {"lo_vector": lo_embedding.tolist(), "k": k * 3, "domain_filter": domain_filter}
        results = db.execute(query, params).fetchall()
    else:
        # SQLite / Manual Fallback
        import numpy as np
        import json
        
        # Get all chunks with their embeddings
        chunks = db.query(Course, CourseChunk, Embedding).join(
            CourseChunk, CourseChunk.course_id == Course.id
        ).join(
            Embedding, Embedding.chunk_id == CourseChunk.id
        )
        
        chunks = chunks.filter(Embedding.model_version == embedding_service.get_model_version())
        # Normalize domain filter
        domain_filter_normalized = [d.lower().strip().strip('"\'') for d in domain_filter if d]
        
        # Fetch ALL chunks — we'll filter in Python with normalized comparison
        all_data = chunks.all()
        
        if domain_filter_normalized:
            all_data = [
                (c, ch, e) for c, ch, e in all_data
                if any(
                    df in c.domain.lower().strip().strip('"\'')
                    or c.domain.lower().strip().strip('"\'') in df
                    for df in domain_filter_normalized
                )
            ]
        
        if not all_data:
            return []
            
        lo_embedding = embedding_service.encode(lo.lo_text)
        lo_text_lower = lo.lo_text.lower()
        query_terms = re.findall(r"[\w-]+", lo_text_lower, flags=re.UNICODE)
        documents = [re.findall(r"[\w-]+", chunk.chunk_text.lower(), flags=re.UNICODE) for _, chunk, _ in all_data]
        doc_freq = Counter(term for terms in documents for term in set(terms))
        avg_len = sum(len(terms) for terms in documents) / max(len(documents), 1)
        raw_bm25 = []
        for terms in documents:
            tf = Counter(terms); score = 0.0
            for term in query_terms:
                df = doc_freq.get(term, 0); idf = math.log(1 + (len(documents) - df + 0.5) / (df + 0.5)); freq = tf.get(term, 0)
                if freq: score += idf * (freq * 2.2) / (freq + 1.2 * (0.25 + 0.75 * len(terms) / max(avg_len, 1)))
            raw_bm25.append(score)
        max_bm25 = max(raw_bm25, default=0.0)
        results_list = []
        for row_index, (course_obj, chunk_obj, emb_obj) in enumerate(all_data):
            # Parse vector from string if stored as text
            try:
                if isinstance(emb_obj.vector, str):
                    vec = np.array(json.loads(emb_obj.vector))
                else:
                    vec = np.array(emb_obj.vector)
                
                # 1. Base embedding similarity
                similarity = np.dot(lo_embedding, vec) / (
                    np.linalg.norm(lo_embedding) * np.linalg.norm(vec) + 1e-9
                )
                
                lexical_score = raw_bm25[row_index] / max_bm25 if max_bm25 > 0 else 0.0
                # Thesis T6, Eq. hybrid coverage: alpha=0.75 semantic
                # similarity and 0.25 normalized BM25 lexical relevance.
                total_similarity = 0.75 * float(similarity) + 0.25 * lexical_score
                
                results_list.append((
                    course_obj.id, course_obj.course_id, course_obj.title,
                    course_obj.domain, course_obj.credits, chunk_obj.id,
                    chunk_obj.chunk_type, chunk_obj.chunk_text, total_similarity
                ))
            except:
                continue
        
        # Sort and take top
        results_list.sort(key=lambda x: x[8], reverse=True)
        results = results_list[:k*3]

    # Aggregate by course
    course_scores = {}
    for row in results:
        course_id = row[0]
        if course_id not in course_scores:
            course_scores[course_id] = {
                "course_id": course_id, "course_code": row[1], "title": row[2],
                "domain": row[3], "credits": row[4], "chunks": [],
                "max_similarity": 0, "avg_similarity": 0
            }
        
        chunk_info = {
            "chunk_id": row[5], "chunk_type": row[6],
            "chunk_text": row[7][:200] + "..." if len(row[7]) > 200 else row[7],
            "similarity": float(row[8])
        }
        
        course_scores[course_id]["chunks"].append(chunk_info)
        course_scores[course_id]["max_similarity"] = max(course_scores[course_id]["max_similarity"], float(row[8]))
    
    for course_data in course_scores.values():
        if course_data["chunks"]:
            course_data["avg_similarity"] = sum(c["similarity"] for c in course_data["chunks"]) / len(course_data["chunks"])
    
    return sorted(course_scores.values(), key=lambda x: x["max_similarity"], reverse=True)[:k]


def retrieve_top_k_courses_hybrid(
    lo: LearningOutcome,
    db: Session,
    k: int = None,
    domain_filter: Optional[List[str]] = None,
    graph_weight: float = 0.25,
) -> List[Dict]:
    """
    Hybrid KAG retrieval: vector search + knowledge-graph expansion.

    1. Run standard vector retrieval to get top-k*2 candidates.
    2. For each candidate, expand via graph neighbors (DOMAIN_SIMILAR,
       PREREQUISITE) and add any new courses with a graph-proximity score.
    3. Re-rank by blended score: (1-graph_weight)*vector_score +
       graph_weight*graph_score.

    Falls back to pure vector retrieval if the graph has no edges.
    """
    if k is None:
        k = settings.TOP_K_RETRIEVAL

    # Step 1: vector candidates (fetch more to leave room for graph additions)
    vector_results = retrieve_top_k_courses(lo, db, k=k * 2, domain_filter=domain_filter)

    # Check whether the knowledge graph has been built
    graph_has_edges = db.query(GraphEdge).limit(1).count() > 0
    if not graph_has_edges:
        return vector_results[:k]

    # Step 2: graph expansion
    from app.kag.knowledge_graph import get_graph_neighbors

    expanded: Dict[int, Dict] = {r["course_id"]: r for r in vector_results}
    # Assign initial vector scores
    for r in vector_results:
        r["vector_score"] = r["max_similarity"]
        r["graph_score"] = 0.0

    for r in vector_results[:k]:  # expand only the top-k seed nodes
        neighbors = get_graph_neighbors(
            r["course_id"], db, max_hops=2, max_neighbors=10
        )
        for nb in neighbors:
            cid = nb["course_id"]
            if cid in expanded:
                # Boost existing entry's graph score
                hop_decay = 1.0 / nb["hop"]
                expanded[cid]["graph_score"] = max(
                    expanded[cid].get("graph_score", 0.0),
                    nb["weight"] * hop_decay,
                )
            else:
                # New candidate from graph: fetch course row
                course = db.query(Course).filter(Course.id == cid).first()
                if course is None:
                    continue
                # Check domain filter
                if domain_filter:
                    dn = [d.lower().strip() for d in domain_filter]
                    cdomain = (course.domain or "").lower().strip()
                    if not any(d in cdomain or cdomain in d for d in dn):
                        continue
                hop_decay = 1.0 / nb["hop"]
                expanded[cid] = {
                    "course_id": cid,
                    "course_code": course.course_id,
                    "title": course.title,
                    "domain": course.domain,
                    "credits": course.credits,
                    "chunks": [],
                    "max_similarity": 0.0,
                    "avg_similarity": 0.0,
                    "vector_score": 0.0,
                    "graph_score": nb["weight"] * hop_decay,
                }

    # Step 3: blended re-ranking
    alpha = graph_weight
    for entry in expanded.values():
        vs = entry.get("vector_score", entry.get("max_similarity", 0.0))
        gs = entry.get("graph_score", 0.0)
        entry["hybrid_score"] = (1 - alpha) * vs + alpha * gs

    ranked = sorted(expanded.values(), key=lambda x: x["hybrid_score"], reverse=True)
    return ranked[:k]


def retrieve_similar_chunks(
    query_text: str,
    db: Session,
    k: int = 5,
    chunk_type: str = None
) -> List[Dict]:
    """
    Retrieve similar chunks for any query text
    """
    from app.models.embedding import HAS_PGVECTOR
    
    if HAS_PGVECTOR and not str(settings.DATABASE_URL).startswith("sqlite"):
        query_embedding = embedding_service.encode(query_text)
        query_sql = text("""
            SELECT cc.id, cc.chunk_type, cc.chunk_text, c.course_id, c.title,
            1 - (e.vector <=> :query_vector) as similarity
            FROM course_chunks cc
            JOIN embeddings e ON e.chunk_id = cc.id
            JOIN courses c ON c.id = cc.course_id
            WHERE (:chunk_type IS NULL OR cc.chunk_type = :chunk_type)
            ORDER BY e.vector <=> :query_vector LIMIT :k
        """)
        params = {"query_vector": query_embedding.tolist(), "k": k, "chunk_type": chunk_type}
        results = db.execute(query_sql, params).fetchall()
    else:
        import numpy as np
        import json
        
        query_embedding = embedding_service.encode(query_text)
        chunks = db.query(CourseChunk, Embedding, Course).join(
            Embedding, Embedding.chunk_id == CourseChunk.id
        ).join(
            Course, Course.id == CourseChunk.course_id
        )
        if chunk_type:
            chunks = chunks.filter(CourseChunk.chunk_type == chunk_type)
        
        results_list = []
        for chunk_obj, emb_obj, course_obj in chunks.all():
            try:
                if isinstance(emb_obj.vector, str):
                    vec = np.array(json.loads(emb_obj.vector))
                else:
                    vec = np.array(emb_obj.vector)
                similarity = np.dot(query_embedding, vec) / (np.linalg.norm(query_embedding) * np.linalg.norm(vec) + 1e-9)
                results_list.append({
                    "chunk_id": chunk_obj.id, "chunk_type": chunk_obj.chunk_type,
                    "chunk_text": chunk_obj.chunk_text, "course_code": course_obj.course_id,
                    "course_title": course_obj.title, "similarity": float(similarity)
                })
            except: continue
        
        results_list.sort(key=lambda x: x["similarity"], reverse=True)
        return results_list[:k]







