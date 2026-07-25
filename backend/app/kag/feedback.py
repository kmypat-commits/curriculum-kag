"""Expert-in-the-loop knowledge accumulation for promoted bridge modules."""
from datetime import datetime, timezone
from typing import Dict, Optional
from sqlalchemy.orm import Session
from app.models.audit import AuditEvent
from app.models.bridge_module import BridgeModule
from app.models.course import Course
from app.kag.indexing import index_course


def promote_bridge_to_course(bridge_module_id: int, db: Session, promoted_by_user_id: Optional[int] = None, force_domain: Optional[str] = None, force_semester: Optional[int] = None) -> Dict:
    bridge = db.query(BridgeModule).filter(BridgeModule.id == bridge_module_id).first()
    if not bridge: raise ValueError(f"Bridge module {bridge_module_id} not found")
    marker = f"[Promoted from bridge module #{bridge_module_id}]"
    existing = db.query(Course).filter(Course.description.like(f"%{marker}%")).first()
    if existing:
        return {"course_id": existing.id, "course_code": existing.course_id, "title": existing.title, "domain": existing.domain, "credits": existing.credits, "already_promoted": True, "message": "This bridge module was already promoted."}
    code = f"BRIDGE_{bridge_module_id:04d}"
    course = Course(course_id=code, title=bridge.title, domain=force_domain or "interdisciplinary", credits=bridge.credits or 5, recommended_semester=force_semester or bridge.recommended_semester, description="\n".join(filter(None, [marker, bridge.goal, f"Targets LOs: {', '.join(bridge.target_los or [])}"])), topics=bridge.topics or [], learning_outcomes=bridge.learning_outcomes or [], assessment_methods=bridge.assessment_methods or [], cycle_component="mandatory")
    db.add(course); db.flush()
    chunks_created = index_course(course, db)
    # Do not rebuild the full graph synchronously here.  On a large EPVO-backed
    # repository this turns a single "add bridge module" click into a long,
    # timeout-prone operation.  The course and its chunks are indexed now; the
    # complete graph can be rebuilt explicitly via /kag/graph/build.
    db.add(AuditEvent(user_id=promoted_by_user_id, action="promote_bridge_to_course", entity_type="bridge_module", entity_id=bridge_module_id, details_json={"new_course_id": course.id, "new_course_code": code, "chunks_indexed": chunks_created, "graph_rebuild_deferred": True, "promoted_at": datetime.now(timezone.utc).isoformat()}))
    db.commit(); db.refresh(course)
    return {"course_id": course.id, "course_code": course.course_id, "title": course.title, "domain": course.domain, "credits": course.credits, "chunks_indexed": chunks_created, "graph_rebuild_deferred": True, "already_promoted": False, "message": f"Bridge module promoted; knowledge base now has {db.query(Course).count()} courses."}


def record_plan_feedback(plan_id: int, feedback: str, details: Optional[Dict] = None, db: Session = None, user_id: Optional[int] = None) -> None:
    if feedback not in {"accepted", "rejected", "modified"}: raise ValueError("feedback must be accepted, rejected, or modified")
    db.add(AuditEvent(user_id=user_id, action=f"plan_feedback_{feedback}", entity_type="plan", entity_id=plan_id, details_json=details or {})); db.commit()
