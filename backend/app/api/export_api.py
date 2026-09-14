from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.database import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.access import require_project_version_access
from app.models.plan import Plan, PlanItem
from app.models.project import ProjectVersion
from app.models.course import Course
from app.models.bridge_module import BridgeModule
from app.models.embedding import MatchScore
from app.models.audit import AuditEvent
from app.services.content_localization import course_localization_map
from app.services.language import normalize_language
from app.services.plan_pdf_export import build_plan_pdf
from app.kag.knowledge_graph import get_graph_stats
from app.kag.embedding_service import embedding_service
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from io import BytesIO

router = APIRouter(dependencies=[Depends(require_project_version_access)])


def export_cell_value(value):
    """Make nested metrics safe for an XLSX cell without losing evidence."""
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        import json
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return value


def resolve_export_plan(db: Session, project_version_id: int, variant: str | None) -> Plan | None:
    """Use the active plan by default, or an explicitly requested A/B/C plan."""
    query = db.query(Plan).filter(Plan.project_version_id == project_version_id)
    if variant:
        normalized = variant.upper()
        if normalized not in {"A", "B", "C"}:
            raise HTTPException(status_code=422, detail="Вариант плана должен быть A, B или C")
        query = query.filter(Plan.variant_type == normalized)
    return query.order_by(Plan.is_active.desc(), Plan.id.desc()).first()


def localized_title(localizations: dict, course: Course, language: str = "ru") -> str:
    translations = (localizations.get(course.id) or {}).get("title_translations") or {}
    language = normalize_language(language)
    # Prefer the requested interface language, then use a deterministic fallback
    # so an incomplete legacy row never produces an empty export cell.
    return (
        translations.get(language)
        or translations.get("ru")
        or translations.get("kk")
        or translations.get("en")
        or course.title
    )


@router.post("/{project_version_id}")
async def export_plan(
    project_version_id: int,
    format: str = "xlsx",
    language: str = "ru",
    variant: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export the selected published curriculum plan to XLSX or PDF."""
    
    format = format.strip().lower()
    if format not in {"xlsx", "pdf"}:
        raise HTTPException(status_code=400, detail="Поддерживаются форматы XLSX и PDF")
    
    try:
        # Get project version
        project_version = db.query(ProjectVersion).filter(
            ProjectVersion.id == project_version_id
        ).first()
        
        if not project_version:
            raise HTTPException(status_code=404, detail="Версия проекта не найдена")
        
        # The active plan is the published methodist-facing result.  A caller
        # can request B/C explicitly for comparison, but must never receive an
        # arbitrary historical A because the table order happened to change.
        plan = resolve_export_plan(db, project_version_id, variant)
        
        if not plan:
            raise HTTPException(status_code=404, detail="Учебный план не найден")
        
        # Create workbook
        wb = openpyxl.Workbook()
        
        # Sheet 1: Curriculum Plan
        ws1 = wb.active
        ws1.title = "Curriculum Plan"
        
        # Headers
        headers = ["Semester", "Course Code", "Course Title", "Credits", "Domain", "Type", "Prerequisites"]
        ws1.append(headers)
        
        # Style headers
        for cell in ws1[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
            cell.font = Font(color="FFFFFF", bold=True)
        
        # Get plan items
        items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).order_by(PlanItem.semester).all()
        course_ids = [item.course_id for item in items if item.course_id]
        bridge_ids = [item.bridge_module_id for item in items if item.bridge_module_id]
        localizations = course_localization_map(db, course_ids)
        courses_by_id = {
            course.id: course
            for course in db.query(Course).filter(Course.id.in_(course_ids)).all()
        } if course_ids else {}
        bridges_by_id = {
            bridge.id: bridge
            for bridge in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids)).all()
        } if bridge_ids else {}

        if format == "pdf":
            output = build_plan_pdf(
                project_version=project_version,
                plan=plan,
                items=items,
                courses_by_id=courses_by_id,
                bridges_by_id=bridges_by_id,
                localizations=localizations,
                language=normalize_language(language),
            )
            return StreamingResponse(
                output,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": (
                        f"attachment; filename=curriculum_plan_{project_version_id}_{plan.variant_type}.pdf"
                    )
                },
            )
        
        for item in items:
            if item.course_id:
                course = courses_by_id.get(item.course_id)
                if not course:
                    continue
                ws1.append([
                    item.semester,
                    course.course_id,
                    localized_title(localizations, course, language),
                    item.credits,
                    course.domain,
                    item.course_type,
                    ", ".join([p.course_id for p in course.prerequisites]) if course.prerequisites else ""
                ])
            elif item.bridge_module_id:
                bm = bridges_by_id.get(item.bridge_module_id)
                if not bm:
                    continue
                ws1.append([
                    item.semester,
                    bm.course_id,
                    bm.title + " [BRIDGE]",
                    item.credits,
                    "Interdisciplinary",
                    item.course_type,
                    ", ".join(bm.prerequisites) if bm.prerequisites else ""
                ])
        
        # Sheet 2: LO Coverage Matrix
        ws2 = wb.create_sheet("LO Coverage")
        
        # Get LOs
        los = project_version.learning_outcomes
        ws2.append(["Course Code", "Course Title"] + [lo.lo_code for lo in los])
        
        # Get all courses in plan
        courses = list(courses_by_id.values())
        lo_ids = [lo.id for lo in los]
        match_scores = (
            db.query(MatchScore.course_id, MatchScore.lo_id, func.max(MatchScore.score))
            .filter(
                MatchScore.project_version_id == project_version_id,
                MatchScore.course_id.in_(course_ids),
                MatchScore.lo_id.in_(lo_ids),
            )
            .group_by(MatchScore.course_id, MatchScore.lo_id)
            .all()
        ) if course_ids and lo_ids else []
        score_by_course_lo = {
            (course_id, lo_id): score
            for course_id, lo_id, score in match_scores
        }
        
        for course in courses:
            row = [course.course_id, localized_title(localizations, course, language)]
            for lo in los:
                score = score_by_course_lo.get((course.id, lo.id))
                row.append(f"{score:.2f}" if score is not None else "0.00")
            ws2.append(row)
        
        # Sheet 3: Metrics
        ws3 = wb.create_sheet("Metrics")
        ws3.append(["Metric", "Value"])
        
        metrics = plan.metrics_json or {}
        for key, value in metrics.items():
            ws3.append([key.replace("_", " ").title(), export_cell_value(value)])
        
        # Sheet 4: Deterministic verification details
        ws4 = wb.create_sheet("Verification")
        ws4.append(["Check", "Result"])
        verification = (metrics or {}).get("verification", {})
        for key in ["feasible", "hard_violation_count", "target_credits", "total_credits", "maximum_total_credits", "min_lo_coverage", "average_lo_coverage", "coverage_threshold", "evidence_count", "redundancy"]:
            ws4.append([key, str(verification.get(key, ""))])
        ws4.append(["prerequisite_violations", len(verification.get("prerequisite_violations", []))])
        ws4.append(["semester_load_violations", len(verification.get("semester_load_violations", []))])

        ws5 = wb.create_sheet("Knowledge Graph")
        ws5.append(["Metric", "Value"])
        for key, value in {**get_graph_stats(db), **embedding_service.get_status()}.items():
            ws5.append([key, str(value)])

        ws6 = wb.create_sheet("Audit Log")
        ws6.append(["Timestamp", "Action", "Entity Type", "Entity ID", "Details"])
        audit_events = (
            db.query(AuditEvent)
            .filter(
                or_(
                    (AuditEvent.entity_type == "plan") & (AuditEvent.entity_id == plan.id),
                    (AuditEvent.entity_type == "project_version") & (AuditEvent.entity_id == project_version_id),
                )
            )
            .order_by(AuditEvent.id.desc())
            .limit(200)
            .all()
        )
        for event in audit_events:
            ws6.append([
                str(event.timestamp), event.action, event.entity_type,
                event.entity_id, export_cell_value(event.details_json),
            ])

        ws7 = wb.create_sheet("International Quality")
        ws7.append(["Framework Score", str((metrics or {}).get("international_quality", {}).get("score", ""))])
        ws7.append(["Passed", str((metrics or {}).get("international_quality", {}).get("passed", ""))])
        ws7.append([])
        ws7.append(["Check", "Passed", "Evidence", "Recommendation"])
        for check in (metrics or {}).get("international_quality", {}).get("checks", []):
            ws7.append([
                check.get("name", ""),
                str(check.get("passed", "")),
                check.get("evidence", ""),
                check.get("recommendation", ""),
            ])
        # Save to BytesIO
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=curriculum_plan_{project_version_id}_{plan.variant_type}.xlsx"
                )
            }
        )
        
    except (SQLAlchemyError, OSError, RuntimeError, ValueError, TypeError) as e:
        raise HTTPException(status_code=500, detail=f"Не удалось выполнить экспорт: {e.__class__.__name__}") from e

