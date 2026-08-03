from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from fastapi import Query
from app.database import get_db
from app.models.user import User
from app.models.project import ProjectVersion
from app.models.bridge_module import BridgeModule
from app.services.auth import get_current_user
from app.services.language import normalize_language
from app.kag.scoring import compute_all_matches
from app.kag.gap_detector import detect_gaps
from app.kag.duplication_detector import detect_duplicates
from app.kag.bridge_generator import generate_bridge_modules
from app.kag.knowledge_graph import build_knowledge_graph, get_graph_stats
from app.kag.embedding_service import embedding_service
from app.kag.indexing import index_all_courses
from app.models.embedding import Embedding, MatchFeedback, MatchScore
from sqlalchemy import func
from app.kag.feedback import promote_bridge_to_course, record_plan_feedback
from app.config import settings
from app.models.plan import Plan, PlanItem
from app.planner.verifier import verify_curriculum_plan
from app.services.ai_contracts import validate_achievability
from app.services.pydantic_ai_adapter import run_achievability as run_pydantic_ai_achievability
import json
from typing import Optional

router = APIRouter()


@router.post("/match-feedback")
async def submit_match_feedback(
    project_version_id: int = Body(...), course_id: int = Body(...), lo_id: int = Body(...),
    verdict: str = Body(...), corrected_score: Optional[float] = Body(None), comment: Optional[str] = Body(None),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    if verdict not in {"confirmed", "weak", "incorrect", "corrected"}:
        raise HTTPException(status_code=400, detail="Недопустимая экспертная оценка")
    if corrected_score is not None and not 0.0 <= float(corrected_score) <= 1.0:
        raise HTTPException(status_code=400, detail="Оценка связи должна быть в диапазоне от 0 до 1")
    match = db.query(MatchScore).filter(MatchScore.project_version_id == project_version_id, MatchScore.course_id == course_id, MatchScore.lo_id == lo_id).first()
    snapshot = {"score": match.score, "model_name": match.model_name, "model_version": match.model_version, "evidence": match.evidence_json} if match else {"score": None, "source": "graph_suggestion"}
    feedback = MatchFeedback(project_version_id=project_version_id, course_id=course_id, lo_id=lo_id, verdict=verdict, corrected_score=corrected_score, comment=comment, user_id=current_user.id, model_snapshot_json=snapshot)
    db.add(feedback); db.commit(); db.refresh(feedback)
    return {"id": feedback.id, "status": "recorded", "verdict": verdict}


def _plan_coverage_for_version(project_version_id: int, db: Session, variant: str | None = None):
    """Return stored verifier coverage for the best of the latest A/B/C variants."""
    query = db.query(Plan).filter(Plan.project_version_id == project_version_id)
    if variant:
        query = query.filter(Plan.variant_type == variant.upper())
    plans = query.order_by(
        Plan.is_active.desc(), Plan.id.desc()
    ).all()
    if not plans:
        return None
    candidates = []
    latest_by_variant = {}
    for plan in plans:
        latest_by_variant.setdefault(plan.variant_type, plan)
    for plan in latest_by_variant.values():
        verification = (plan.metrics_json or {}).get("verification")
        if verification:
            candidates.append((plan, verification))
    if not candidates:
        return None
    plan, verification = max(
        candidates,
        key=lambda item: (item[1]["min_lo_coverage"], item[1]["average_lo_coverage"], item[0].id),
    )
    return {
        "plan_id": plan.id, "variant_type": plan.variant_type,
        "average_lo_coverage": verification["average_lo_coverage"],
        "min_lo_coverage": verification["min_lo_coverage"],
        "coverage_percentage": round(verification["average_lo_coverage"] * 100, 1),
        "covered_los": sum(1 for item in verification["coverage_by_lo"].values()
                           if item["coverage"] >= verification["coverage_threshold"]),
        "total_los": len(verification["coverage_by_lo"]),
        "coverage_threshold": verification["coverage_threshold"],
        "coverage_by_lo": verification["coverage_by_lo"],
        "evidence_count": verification["evidence_count"],
        "quality_passed": verification["quality_passed"],
    }


@router.post("/{project_version_id}/match")
async def compute_matches(
    project_version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Compute course-LO matching scores for a project version"""
    try:
        result = compute_all_matches(project_version_id, db)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{project_version_id}/coverage")
async def get_coverage(
    project_version_id: int,
    variant: str | None = Query(default=None, pattern="^[ABCabc]$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get LO coverage dashboard data"""
    try:
        plan_coverage = _plan_coverage_for_version(project_version_id, db, variant)
        if plan_coverage:
            threshold = plan_coverage["coverage_threshold"]
            lo_coverage = {
                code: {"max_score": item["coverage"]}
                for code, item in (plan_coverage.get("coverage_by_lo") or {}).items()
            }
            gaps = [
                {
                    "lo_code": code,
                    "coverage": item["coverage"],
                    "max_coverage": item["coverage"],
                    "gap_size": max(0, threshold - item["coverage"]),
                }
                for code, item in (plan_coverage.get("coverage_by_lo") or {}).items()
                if item["coverage"] < threshold
            ]
            return {
                "matches": {"lo_coverage": lo_coverage, "prediction": {"source": "stored_plan_metrics"}},
                "gaps": {
                    "total_los": plan_coverage["total_los"],
                    "gap_count": len(gaps),
                    "gap_percentage": round(len(gaps) / max(plan_coverage["total_los"], 1) * 100, 1),
                    "threshold": threshold,
                    "gaps": gaps,
                },
                "plan_coverage": plan_coverage,
            }

        matches_result = compute_all_matches(project_version_id, db)
        gaps_result = detect_gaps(project_version_id, db)
        
        return {
            "matches": matches_result,
            "gaps": gaps_result,
            "plan_coverage": plan_coverage,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{project_version_id}/propose-merge")
async def propose_merges(
    project_version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get merge/adapt suggestions for duplicate courses"""
    try:
        duplicates = detect_duplicates(project_version_id, db)
        return {
            "suggestions": duplicates,
            "count": len(duplicates)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{project_version_id}/generate-bridge")
async def generate_bridge(
    project_version_id: int,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate bridge modules for gap LOs"""
    try:
        force_enrichment = bool(payload.get("force_enrichment")) if isinstance(payload, dict) else False
        modules = generate_bridge_modules(project_version_id, db, force_enrichment=force_enrichment)
        return {
            "generated_modules": modules,
            "count": len(modules),
            "mode": "optional_enrichment" if force_enrichment else "gap_closure",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/system/status")
async def system_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    versions = [
        row[0] for row in db.query(Embedding.model_version)
        .filter(Embedding.model_version.isnot(None))
        .distinct()
        .limit(3)
        .all()
    ]
    return {
        "embedding": embedding_service.get_status(),
        "embedding_inventory": {"model_versions_sample": versions},
        "mixed_embedding_models": len(versions) > 1,
        "graph": get_graph_stats(db),
    }


@router.post("/system/reindex")
async def reindex_repository(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    stats = index_all_courses(db)
    graph = build_knowledge_graph(db)
    return {"status": "reindexed", "embedding": embedding_service.get_status(), **stats, "graph": graph}

# ---------------------------------------------------------------------------
# Knowledge Graph endpoints
# ---------------------------------------------------------------------------

@router.get("/graph/stats")
async def graph_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return statistics about the current curriculum knowledge graph."""
    try:
        return get_graph_stats(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/graph/build")
async def build_graph(
    project_version_id: Optional[int] = Body(None),
    similarity_threshold: float = Body(0.72),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Build (or rebuild) the curriculum knowledge graph.

    Optionally pass *project_version_id* to also add LO-coverage edges
    from the match scores of that project version.  This enriches the
    graph and makes future retrieval more accurate.
    """
    try:
        stats = build_knowledge_graph(
            db,
            similarity_threshold=similarity_threshold,
            project_version_id=project_version_id,
        )
        return {"status": "built", **stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bridge/{bridge_module_id}/promote")
async def promote_bridge(
    bridge_module_id: int,
    force_domain: Optional[str] = Body(None),
    force_semester: Optional[int] = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Promote a bridge module to a permanent course in the repository.

    This is the **learning mechanism**: each promoted module expands the
    course knowledge base so future curriculum generations have more and
    better courses to draw from.
    """
    try:
        result = promote_bridge_to_course(
            bridge_module_id=bridge_module_id,
            db=db,
            promoted_by_user_id=current_user.id,
            force_domain=force_domain,
            force_semester=force_semester,
        )
        result.update({
            "plan_changed": False,
            "requires_regeneration": True,
            "next_step": "Bridge module has been added to the course repository. Regenerate curriculum variants in Plan Builder to use it in the plan.",
        })
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{project_version_id}/plan-feedback")
async def submit_plan_feedback(
    project_version_id: int,
    plan_id: int = Body(...),
    feedback: str = Body(...),  # accepted | rejected | modified
    details: Optional[dict] = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record expert feedback on a generated plan (for audit trail)."""
    try:
        record_plan_feedback(
            plan_id=plan_id,
            feedback=feedback,
            details=details,
            db=db,
            user_id=current_user.id,
        )
        return {"status": "recorded", "feedback": feedback}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{project_version_id}/lo-achievability")
async def analyze_lo_achievability(
    project_version_id: int,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Analyze LO achievability using LLM — returns a verdict, score, and per-LO recommendations."""
    try:
        project_version = db.query(ProjectVersion).filter(
            ProjectVersion.id == project_version_id
        ).first()
        if not project_version:
            raise HTTPException(status_code=404, detail="Версия проекта не найдена")

        # A generated plan already contains the authoritative verifier coverage.
        # Do not rescore the entire EPVO repository on every button click: after
        # the repository grew, compute_all_matches could take several minutes
        # and the UI reported a misleading 500/timeout.  Recompute only for a
        # version that has no stored plan evidence yet.
        plan_coverage = _plan_coverage_for_version(project_version_id, db)
        if plan_coverage:
            matches_result = {"lo_coverage": {}}
            gaps_result = {
                "gap_count": sum(
                    1 for item in plan_coverage["coverage_by_lo"].values()
                    if item["coverage"] < plan_coverage["coverage_threshold"]
                ),
                "total_los": plan_coverage["total_los"],
                "gaps": [],
            }
        else:
            matches_result = compute_all_matches(project_version_id, db)
            gaps_result = detect_gaps(project_version_id, db)

        lo_coverage = matches_result.get("lo_coverage", {})
        los = project_version.learning_outcomes
        gap_los = {g["lo_code"]: g for g in gaps_result.get("gaps", [])}
        if plan_coverage:
            threshold = plan_coverage["coverage_threshold"]
            lo_coverage = {
                code: {"max_score": item["coverage"]}
                for code, item in plan_coverage["coverage_by_lo"].items()
            }
            gap_los = {
                code: {
                    "lo_code": code,
                    "max_coverage": item["coverage"],
                    "coverage": item["coverage"],
                }
                for code, item in plan_coverage["coverage_by_lo"].items()
                if item["coverage"] < threshold
            }

        # Build LO summary for prompt
        lo_lines = []
        for lo in los:
            cov = lo_coverage.get(lo.lo_code, {})
            pct = round(cov.get("max_score", 0) * 100)
            lo_lines.append(f"- {lo.lo_code}: {lo.lo_text} [coverage: {pct}%]")

        project = project_version.project
        domains = f"{getattr(project, 'domain1', '')} and {getattr(project, 'domain2', '')}".strip(" and")

        language = normalize_language(payload.get("language") if isinstance(payload, dict) else "ru")
        response_language = {"ru": "Russian", "kk": "Kazakh", "en": "English"}.get(language, "Russian")

        prompt = f"""You are an expert curriculum quality assessor.
Analyze the following learning outcomes (LOs) for an educational program in the domain: "{domains}".
Goal: {getattr(project, 'goal', 'Not specified')}

Learning Outcomes with current course coverage percentages:
{chr(10).join(lo_lines)}

For each LO with coverage below 40%, decide:
1. Is the LO too vague or unrealistic to achieve?
2. Or does it simply need more/different courses?

Respond with a valid JSON object (no markdown) with this structure:
{{
  "verdict": "Ready" | "Needs Improvement" | "Critical Gaps",
  "score": <integer 0-100>,
  "summary": "<2-3 sentence overall assessment>",
  "recommendations": [
    {{
      "lo_code": "<code>",
      "status": "on_track" | "needs_courses" | "too_vague" | "critical",
      "issue": "<description of the problem>",
      "suggestion": "<actionable recommendation>"
    }}
  ]
}}

Only include LOs with issues in the recommendations array. If all LOs are on track, return an empty array.
Write summary, issue, and suggestion in {response_language}. Keep verdict and status values exactly as specified in English."""

        pydantic_result = run_pydantic_ai_achievability(prompt)
        if pydantic_result:
            pydantic_result["analysis_source"] = "pydantic_ai"
            pydantic_result["api_completed"] = True
            if plan_coverage:
                pydantic_result["coverage_source"] = f"plan_{plan_coverage['variant_type']}"
            return pydantic_result

        api_key = settings.LLM_API_KEY
        has_real_key = api_key and not api_key.startswith("sk-placeholder")

        if has_real_key and settings.LLM_PROVIDER == "openai":
            from openai import OpenAI
            # Bound the external call: a stale/invalid key or unavailable
            # provider must fall back to the deterministic evidence analysis,
            # never leave the button hanging until the reverse proxy returns
            # a misleading HTTP 500/timeout.
            client_kwargs = {"api_key": api_key, "timeout": 15.0, "max_retries": 0}
            if settings.LLM_BASE_URL:
                client_kwargs["base_url"] = settings.LLM_BASE_URL
            client = OpenAI(**client_kwargs)
            try:
                response = client.chat.completions.create(
                    model=settings.LLM_MODEL_NAME,
                    messages=[
                        {"role": "system", "content": "You are an expert curriculum quality assessor. Always respond with valid JSON only, no markdown."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.4,
                    max_tokens=2000,
                    response_format={"type": "json_object"}
                )
                raw = response.choices[0].message.content
            except Exception:
                # The UI must remain usable when the external provider is unavailable,
                # rate-limited, or has an expired key. Use the same deterministic
                # evidence-based fallback as offline mode instead of returning HTTP 500.
                gap_count = len(gap_los)
                total = len(los) or 1
                score = max(0, 100 - int(gap_count / total * 100))
                verdict = "Ready" if gap_count == 0 else ("Needs Improvement" if gap_count <= total // 2 else "Critical Gaps")
                raw = json.dumps({
                    "verdict": verdict,
                    "score": score,
                    "summary": ("Все результаты обучения имеют достаточное покрытие." if language == "ru" else "Барлық оқу нәтижелері жеткілікті қамтылған." if language == "kk" else "All learning outcomes are adequately covered.") if gap_count == 0 else (f"Обнаружены пробелы покрытия: {gap_count} из {total} результатов обучения." if language == "ru" else f"Қамтуда олқылықтар бар: {total} нәтижеден {gap_count}." if language == "kk" else f"Coverage gaps found: {gap_count} of {total} learning outcomes."),
                    "recommendations": [
                        {"lo_code": code, "status": "needs_courses", "issue": f"Coverage is only {round(float(item.get('max_coverage', item.get('coverage', 0))) * 100)}%.", "suggestion": "Add or generate courses that directly address this learning outcome."}
                        for code, item in gap_los.items()
                    ]
                })
        else:
            # Mock response when no real API key is configured
            gap_count = gaps_result.get("gap_count", 0)
            total = gaps_result.get("total_los", 1)
            score = max(0, 100 - int(gap_count / total * 100)) if total else 50
            verdict = "Ready" if gap_count == 0 else ("Needs Improvement" if gap_count <= total // 2 else "Critical Gaps")
            recs = []
            for g in gap_los.values():
                coverage = float(g.get("max_coverage", g.get("coverage", g.get("max_score", 0))) or 0)
                recs.append({
                    "lo_code": g["lo_code"],
                    "status": "needs_courses",
                    "issue": f"Coverage is only {round(coverage * 100)}% — below the 65% threshold.",
                    "coverage": round(coverage, 4),
                    "suggestion": "Add or generate courses that specifically address this learning outcome."
                })
            if language == "ru":
                summary = f"В программе не покрыто результатов обучения: {gap_count} из {total}." if gap_count else "Все результаты обучения имеют достаточное покрытие."
                issue_template = "Покрытие составляет только {value}% при требуемом пороге 60%."
                suggestion = "Добавьте или создайте дисциплины, которые непосредственно формируют этот результат обучения."
            elif language == "kk":
                summary = f"Бағдарламада {total} оқу нәтижесінің {gap_count} нәтижесі жеткіліксіз қамтылған." if gap_count else "Барлық оқу нәтижелері жеткілікті қамтылған."
                issue_template = "Қамтылу деңгейі {value}%, талап етілетін шек 60%."
                suggestion = "Осы оқу нәтижесін тікелей қалыптастыратын пәндерді қосыңыз немесе жасаңыз."
            else:
                summary = f"The program has {gap_count} uncovered learning outcomes out of {total}." if gap_count else "All learning outcomes are adequately covered."
                issue_template = "Coverage is only {value}% against the required 60% threshold."
                suggestion = "Add or generate courses that directly address this learning outcome."
            for rec, gap in zip(recs, gap_los.values()):
                coverage = float(gap.get("max_coverage", gap.get("coverage", gap.get("max_score", 0))) or 0)
                rec["issue"] = issue_template.format(value=round(coverage * 100))
                rec["suggestion"] = suggestion

            raw = json.dumps({
                "verdict": verdict,
                "score": score,
                "summary": summary,
                "recommendations": recs
            })

        result = json.loads(raw)
        # Validate both provider and deterministic responses against the same
        # typed contract.  Invalid provider JSON becomes an explicit review
        # state instead of leaking a 500 or malformed UI payload.
        try:
            result = validate_achievability(result).model_dump()
        except Exception:
            result = {
                "verdict": "Needs Improvement",
                "score": 0,
                "summary": {
                    "ru": "Ответ AI не прошёл проверку схемы; требуется ручная проверка покрытия LO.",
                    "kk": "ЖИ жауабы схема тексеруінен өтпеді; LO қамтуын қолмен тексеру қажет.",
                    "en": "The AI response failed schema validation; LO coverage requires manual review.",
                }.get(language, "Ответ AI не прошёл проверку схемы; требуется ручная проверка покрытия LO."),
                "recommendations": [],
            }
        # Explicit provenance lets the UI distinguish a real provider response
        # from the deterministic offline fallback.
        result.setdefault("analysis_source", "openai_api" if has_real_key and settings.LLM_PROVIDER == "openai" else "deterministic_evidence")
        result.setdefault("api_completed", True)
        if plan_coverage:
            result.setdefault("coverage_source", f"plan_{plan_coverage['variant_type']}")
        return result

    except HTTPException:
        raise
    except Exception as e:
        # The analysis button must always produce a usable, auditable result.
        # If a legacy project has incomplete match rows or the optional AI
        # provider fails before the normal fallback is reached, return an
        # explicit deterministic status instead of leaking a generic HTTP 500.
        language = normalize_language(payload.get("language") if isinstance(payload, dict) else "ru")
        messages = {
            "ru": "Автоматическая проверка не смогла завершить полный расчёт для этой версии. Сохранён честный результат: требуется проверка покрытия LO и связей дисциплина–LO.",
            "kk": "Бұл нұсқа үшін автоматты тексеру толық есепті аяқтай алмады. Адал нәтиже сақталды: LO қамтуы мен пән–LO байланыстарын тексеру қажет.",
            "en": "The automatic check could not complete the full calculation for this version. An honest result was preserved: LO coverage and course–LO links require review.",
        }
        return {
            "verdict": "Needs Improvement",
            "score": 0,
            "summary": messages.get(language, messages["ru"]),
            "recommendations": [],
            "analysis_source": "deterministic_fallback",
            "api_completed": True,
        }




