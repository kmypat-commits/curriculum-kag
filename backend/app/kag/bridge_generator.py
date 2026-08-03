from typing import Dict, List, Optional
from sqlalchemy.orm import Session
import secrets
from app.models.project import ProjectVersion, LearningOutcome
from app.models.bridge_module import BridgeModule
from app.models.course import Course
from app.kag.gap_detector import detect_gaps
from app.kag.retrieval import retrieve_similar_chunks
from app.config import settings
import json
import logging

logger = logging.getLogger(__name__)


def _normalize_bridge_response(response: str, context: Dict) -> Optional[str]:
    """Validate provider JSON and enforce evidence for both selected domains."""
    try:
        payload = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    domain1 = str(context.get("domain1") or "Primary Discipline")
    domain2 = str(context.get("domain2") or "Secondary Discipline")
    title = str(payload.get("title") or "")
    if domain1.casefold() not in title.casefold() or domain2.casefold() not in title.casefold():
        payload["title"] = f"Integrated {domain1} and {domain2}"
    outcomes = payload.get("learning_outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        return None
    lo_mapping = payload.get("lo_mapping")
    if not isinstance(lo_mapping, dict):
        lo_mapping = {}
    for gap in context.get("gap_los") or []:
        code = gap.get("lo_code")
        if code and not lo_mapping.get(code):
            lo_mapping[code] = outcomes[:2]
    payload["lo_mapping"] = lo_mapping
    return json.dumps(payload, ensure_ascii=False)


def generate_bridge_module_with_llm(
    gap_los: List[Dict],
    project_version: ProjectVersion,
    db: Session,
) -> Dict:
    """
    Generate bridge module content using LLM with KAG context.

    Retrieval pipeline:
    1. Semantic search for evidence chunks related to each gap LO.
    2. Graph-neighbor expansion to find structurally related courses.
    3. Both are injected into the LLM prompt as knowledge context.
    """
    # 1. Collect evidence chunks (semantic retrieval)
    evidence_chunks: List[Dict] = []
    for gap_lo in gap_los:
        chunks = retrieve_similar_chunks(gap_lo["lo_text"], db, k=3)
        evidence_chunks.extend(chunks)

    # 2. Graph context: find courses structurally related to the top evidence
    graph_context: List[Dict] = []
    from app.models.embedding import GraphEdge
    graph_has_edges = db.query(GraphEdge).limit(1).count() > 0
    if graph_has_edges and evidence_chunks:
        from app.kag.knowledge_graph import get_graph_neighbors
        # Use the course_id of the best evidence chunk as seed
        seed_chunk = evidence_chunks[0]
        # Resolve course_id (int) from course_code (string)
        seed_course = db.query(Course).filter(
            Course.course_id == seed_chunk.get("course_code")
        ).first()
        if seed_course:
            neighbors = get_graph_neighbors(seed_course.id, db, max_hops=1, max_neighbors=5)
            for nb in neighbors:
                nc = db.query(Course).filter(Course.id == nb["course_id"]).first()
                if nc:
                    graph_context.append({
                        "title": nc.title,
                        "domain": nc.domain,
                        "credits": nc.credits,
                    })

    # 3. Build prompt with both evidence and graph context
    prompt = build_bridge_module_prompt(
        gap_los, evidence_chunks, project_version, graph_context=graph_context
    )

    # 4. Call LLM
    generated_content = call_llm(prompt, {"domain1": project_version.project.domain1, "domain2": project_version.project.domain2, "gap_los": gap_los})
    structured_content = parse_llm_response(generated_content)

    # 5. Attach provenance
    structured_content["source_chunks"] = [
        {
            "chunk_id": chunk.get("chunk_id"),
            "course_code": chunk.get("course_code"),
            "similarity": chunk.get("similarity"),
        }
        for chunk in evidence_chunks[:10]
    ]
    structured_content["graph_context_used"] = len(graph_context)

    return structured_content


def build_bridge_module_prompt(
    gap_los: List[Dict],
    evidence_chunks: List[Dict],
    project_version: ProjectVersion,
    graph_context: Optional[List[Dict]] = None,
) -> str:
    """Build prompt for LLM to generate bridge module.

    *graph_context* is an optional list of graph-neighbor course summaries
    that provide structural curriculum knowledge to the LLM (KAG pattern).
    """
    project = project_version.project

    prompt = (
        f"You are an expert curriculum designer. "
        f"Create a new interdisciplinary course that bridges "
        f"{project.domain1} and {project.domain2}.\n\n"
        f"Program Goal: {project.goal}\n\n"
        f"The following learning outcomes are NOT adequately covered:\n"
    )

    for gap_lo in gap_los:
        coverage = gap_lo.get("coverage", gap_lo.get("probabilistic_coverage", gap_lo.get("max_coverage", 0.0)))
        prompt += (            f"\n- {gap_lo['lo_code']}: {gap_lo['lo_text']} "
            f"(coverage: {coverage:.1%})"
        )

    prompt += "\n\nRelevant content from existing courses (evidence):\n"
    for chunk in evidence_chunks[:6]:
        prompt += f"\n- [{chunk['course_code']}]: {chunk['chunk_text'][:160]}..."

    if graph_context:
        prompt += "\n\nKnowledge graph context (structurally related courses):\n"
        for gc in graph_context[:5]:
            prompt += f"\n- {gc.get('title','?')} ({gc.get('domain','?')}, {gc.get('credits','?')} cr)"

    prompt += """

Create a new bridge course in JSON with these exact keys:
{
  "title": "...",
  "goal": "2-3 sentences",
  "credits": <3-6>,
  "learning_outcomes": ["...", ...],
  "topics": ["Week 1: ...", ...],
  "prerequisites": [],
  "assessment_methods": ["..."],
  "lo_mapping": {"<lo_code>": ["<outcome>", ...]}
}

Requirements:
- 5-8 learning outcomes
- 12-15 weekly topics
- Cite which program LOs each outcome addresses in lo_mapping
- Return ONLY valid JSON, no markdown
"""
    return prompt


def call_llm(prompt: str, fallback_context: Optional[Dict] = None) -> str:
    """Call the configured LLM or return a domain-aware deterministic fallback."""
    api_key = settings.LLM_API_KEY
    has_real_key = api_key and not api_key.startswith("sk-placeholder")
    if has_real_key and settings.LLM_PROVIDER == "openai":
        try:
            from openai import OpenAI
            kwargs = {"api_key": api_key}
            if settings.LLM_BASE_URL: kwargs["base_url"] = settings.LLM_BASE_URL
            response = OpenAI(**kwargs).chat.completions.create(model=settings.LLM_MODEL_NAME, messages=[{"role": "system", "content": "Return valid JSON only."}, {"role": "user", "content": prompt}], temperature=0.5, max_tokens=2500, response_format={"type": "json_object"})
            normalized = _normalize_bridge_response(response.choices[0].message.content, fallback_context or {})
            if normalized:
                return normalized
        except Exception as exc:
            logger.warning("OpenAI bridge generation failed; using deterministic fallback: %s", exc)
    elif has_real_key and settings.LLM_PROVIDER == "anthropic":
        try:
            from anthropic import Anthropic
            response = Anthropic(api_key=api_key).messages.create(model=settings.LLM_MODEL_NAME or "claude-sonnet-4-6", max_tokens=2500, system="Return valid JSON only.", messages=[{"role": "user", "content": prompt}])
            normalized = _normalize_bridge_response(response.content[0].text, fallback_context or {})
            if normalized:
                return normalized
        except Exception as exc:
            logger.warning("Anthropic bridge generation failed; using deterministic fallback: %s", exc)
    context = fallback_context or {}
    domain1, domain2 = context.get("domain1", "Primary Discipline"), context.get("domain2", "Secondary Discipline")
    gap_los = context.get("gap_los", [])
    codes = [g.get("lo_code") for g in gap_los if g.get("lo_code")]
    outcomes = [f"Integrate concepts and methods from {domain1} and {domain2}", f"Apply digital and analytical tools from {domain2} to problems in {domain1}", "Evaluate evidence, risks, regulation, and stakeholder requirements", "Design an interdisciplinary implementation solution", "Present and defend an evidence-based project"]
    return json.dumps({"title": f"Integrated {domain1} and {domain2}", "goal": f"This bridge course integrates {domain1} with {domain2} and addresses identified programme learning-outcome gaps through applied interdisciplinary work.", "credits": 5, "learning_outcomes": outcomes, "topics": [f"Foundations of {domain1}", f"Foundations of {domain2}", "Interdisciplinary problem framing", "Data and evidence quality", "Digital workflows", "Policy and ethical constraints", "Stakeholder analysis", "Systems modelling", "Risk assessment", "Decision support", "Interoperability", "Case study workshop", "Project development", "Project defence"], "prerequisites": [], "assessment_methods": ["Applied assignments (30%)", "Case analysis (30%)", "Interdisciplinary project (40%)"], "lo_mapping": {code: [outcomes[0], outcomes[4]] for code in codes}}, ensure_ascii=False)


def parse_llm_response(response: str) -> Dict:
    """Parse LLM JSON response"""
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        # Fallback parsing if LLM doesn't return valid JSON
        return {
            "title": "Generated Bridge Module",
            "goal": "Interdisciplinary course",
            "credits": 5,
            "learning_outcomes": [],
            "topics": [],
            "prerequisites": [],
            "assessment_methods": []
        }


def generate_bridge_modules(
    project_version_id: int,
    db: Session,
    max_modules: int = None,
    force_enrichment: bool = False,
) -> List[Dict]:
    """
    Generate bridge modules for gaps in a project
    Returns list of generated modules
    """
    if max_modules is None:
        max_modules = settings.MAX_BRIDGE_MODULES
    
    # Detect gaps
    gap_analysis = detect_gaps(project_version_id, db)
    project_version = db.query(ProjectVersion).filter(
        ProjectVersion.id == project_version_id
    ).first()
    if not project_version:
        raise ValueError(f"Project version {project_version_id} not found")

    if force_enrichment:
        candidate_los = [{
            "lo_id": lo.id, "lo_code": lo.lo_code, "lo_text": lo.lo_text,
            "coverage": 1.0, "probabilistic_coverage": 1.0, "max_coverage": 1.0,
        } for lo in project_version.learning_outcomes]
    else:
        candidate_los = gap_analysis["gaps"]
    if not candidate_los:
        return []
    
    # Group gaps by similarity (simplified - generate one module for all gaps)
    # In production, would cluster gaps and generate multiple modules
    
    generated_modules = []
    
    # Generate one bridge module addressing top gaps
    top_gaps = candidate_los[:5]
    
    if top_gaps:
        content = generate_bridge_module_with_llm(top_gaps, project_version, db)
        # Use timestamp suffix for uniqueness
        import time
        prefix = "ENRICHMENT" if force_enrichment else "BRIDGE"
        unique_id = f"{prefix}_{project_version_id}_{int(time.time()) % 100000}"
        if force_enrichment:
            content["title"] = f"Advanced Interdisciplinary Integration: {project_version.project.domain1} + {project_version.project.domain2}"
            content["goal"] = "Provide optional advanced interdisciplinary practice beyond the minimum programme LO coverage."
        
        # Save to database. Avoid second-based IDs: repeated clicks can happen
        # inside one second and SQLite then raises UNIQUE constraint errors.
        content.setdefault("title", "Generated Bridge Module")
        content.setdefault("goal", "Interdisciplinary bridge module")
        content.setdefault("credits", 5)
        content.setdefault("learning_outcomes", [])
        content.setdefault("topics", [])
        content.setdefault("prerequisites", [])
        content.setdefault("assessment_methods", [])
        credits = int(content.get("credits") or 5)
        credits = min(6, max(3, credits))
        bridge_module = BridgeModule(
            project_version_id=project_version_id,
            course_id=unique_id,
            title=content["title"],
            goal=content["goal"],
            credits=credits,
            learning_outcomes=content["learning_outcomes"],
            topics=content["topics"],
            prerequisites=content.get("prerequisites", []),
            assessment_methods=content.get("assessment_methods", []),
            source_chunks_json=content.get("source_chunks", []),
            generation_params_json={
                "model": settings.LLM_MODEL_NAME,
                "provider": settings.LLM_PROVIDER,
                "gap_los": [g["lo_code"] for g in top_gaps]
                , "mode": "optional_enrichment" if force_enrichment else "gap_closure"
            },
            target_los=[g["lo_code"] for g in top_gaps]
        )
        
        db.add(bridge_module)
        try:
            db.commit()
        except Exception:
            db.rollback()
            bridge_module.course_id = f"{prefix}_{project_version_id}_{secrets.token_hex(4).upper()}"
            db.add(bridge_module)
            db.commit()
        db.refresh(bridge_module)
        
        generated_modules.append({
            "id": bridge_module.id,
            "course_id": bridge_module.course_id,
            "title": bridge_module.title,
            "credits": bridge_module.credits,
            "target_los": bridge_module.target_los,
            "content": content
            , "optional_enrichment": force_enrichment
        })
    
    return generated_modules





