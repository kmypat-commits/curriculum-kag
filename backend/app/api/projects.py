from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Dict
from app.database import get_db
from app.models.user import User
from app.models.project import Project, ProjectVersion, LearningOutcome
from app.services.auth import get_current_user
from app.config import settings
from app.services.ai_contracts import validate_suggestions
from app.services.pydantic_ai_adapter import run_suggestions as run_pydantic_ai_suggestions
from app.services.language import normalize_language
import json
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


def _invalid_epvo_codes(constraints: Dict) -> List[str]:
    """Validate EPVO codes against the selected education level."""
    level = str(constraints.get("education_level") or "").lower()
    scope_prefix = {"bachelor": "6B", "master": "7M", "doctorate": "8D"}.get(level)
    group_prefix = {"bachelor": "B", "master": "M", "doctorate": "D"}.get(level)
    if not scope_prefix or not group_prefix:
        return ["education_level"]
    invalid = []
    for key in ("education_area", "direction_code", "secondary_education_area", "secondary_direction_code"):
        value = str(constraints.get(key) or "").strip()
        if value and not value.startswith(scope_prefix):
            invalid.append(key)
    for key in ("group_code", "secondary_group_code"):
        value = str(constraints.get(key) or "").strip()
        if value and not value.startswith(group_prefix):
            invalid.append(key)
    return invalid


class LearningOutcomeCreate(BaseModel):
    lo_code: str
    lo_text: str
    weight: Optional[float] = 1.0
    taxonomy_level: Optional[str] = None


class ProjectCreate(BaseModel):
    title: str
    domain1: str
    domain2: str
    goal: str
    learning_outcomes: List[LearningOutcomeCreate]
    constraints: Dict

    @model_validator(mode="after")
    def validate_complete_program(self):
        if not self.title.strip() or not self.goal.strip() or not self.domain1.strip():
            raise ValueError("Название, цель и основное направление обязательны")
        if not self.learning_outcomes or any(not lo.lo_text.strip() for lo in self.learning_outcomes):
            raise ValueError("Добавьте минимум один заполненный результат обучения")
        required = ("education_level", "education_area", "direction_code", "group_code", "program_type", "instruction_language", "total_semesters", "total_credits")
        missing = [key for key in required if self.constraints.get(key) in (None, "", 0)]
        if missing:
            raise ValueError("Не заполнены обязательные параметры программы: " + ", ".join(missing))
        invalid_codes = _invalid_epvo_codes(self.constraints)
        if invalid_codes:
            raise ValueError(
                "Выберите значения из справочника ЕПВО, а не заглушки: "
                + ", ".join(invalid_codes)
            )
        program_type = str(self.constraints.get("program_type") or "standard").lower()
        if program_type in {"interdisciplinary", "joint"}:
            secondary_required = ("secondary_education_area", "secondary_direction_code", "secondary_group_code")
            secondary_missing = [key for key in secondary_required if self.constraints.get(key) in (None, "", 0)]
            if secondary_missing:
                raise ValueError("Для междисциплинарной программы выберите второе направление: " + ", ".join(secondary_missing))
            if self.constraints.get("direction_code") == self.constraints.get("secondary_direction_code"):
                raise ValueError("Для междисциплинарной программы выберите два разных направления подготовки")
            if self.constraints.get("group_code") == self.constraints.get("secondary_group_code"):
                raise ValueError("Для междисциплинарной программы выберите две разные группы ОП")
        else:
            for key in ("secondary_education_area", "secondary_direction_code", "secondary_group_code"):
                self.constraints.pop(key, None)
            self.domain2 = ""
            self.constraints["min_domain2_percent"] = 0
        if int(self.constraints["total_semesters"]) != int(self.constraints.get("duration_years", 0)) * 2:
            raise ValueError("Количество семестров должно соответствовать сроку обучения")
        if int(self.constraints["total_credits"]) <= 0 or int(self.constraints.get("max_credits_per_semester", 0)) <= 0:
            raise ValueError("Кредиты и семестровая нагрузка должны быть положительными")
        return self


class ProjectResponse(BaseModel):
    id: int
    title: str
    domain1: str
    domain2: str
    goal: Optional[str] = None
    constraints: Optional[Dict] = None
    created_at: Optional[datetime] = None
    status: Optional[str] = "draft"
    learning_outcomes: List[str] = Field(default_factory=list)
    
    class Config:
        from_attributes = True


class ProjectConstraintsUpdate(BaseModel):
    constraints: Dict

    @model_validator(mode="after")
    def validate_epvo_constraints(self):
        constraints = self.constraints or {}
        required = ("education_level", "education_area", "direction_code", "group_code", "program_type", "instruction_language", "total_semesters", "total_credits")
        missing = [key for key in required if constraints.get(key) in (None, "", 0)]
        if missing:
            raise ValueError("Не заполнены обязательные параметры программы: " + ", ".join(missing))
        invalid_codes = _invalid_epvo_codes(constraints)
        if invalid_codes:
            raise ValueError("Выберите значения из справочника ЕПВО, а не заглушки: " + ", ".join(invalid_codes))
        program_type = str(constraints.get("program_type") or "standard").lower()
        if program_type in {"interdisciplinary", "joint"}:
            secondary_required = ("secondary_education_area", "secondary_direction_code", "secondary_group_code")
            secondary_missing = [key for key in secondary_required if constraints.get(key) in (None, "", 0)]
            if secondary_missing:
                raise ValueError("Для междисциплинарной программы выберите второе направление: " + ", ".join(secondary_missing))
            if constraints.get("direction_code") == constraints.get("secondary_direction_code"):
                raise ValueError("Для междисциплинарной программы выберите два разных направления подготовки")
            if constraints.get("group_code") == constraints.get("secondary_group_code"):
                raise ValueError("Для междисциплинарной программы выберите две разные группы ОП")
        else:
            for key in ("secondary_education_area", "secondary_direction_code", "secondary_group_code"):
                constraints.pop(key, None)
            constraints["min_domain2_percent"] = 0
        if int(constraints["total_semesters"]) != int(constraints.get("duration_years", 0)) * 2:
            raise ValueError("Количество семестров должно соответствовать сроку обучения")
        self.constraints = constraints
        return self


class SuggestionRequest(BaseModel):
    name: str = ""
    domain1: str = ""
    domain2: str = ""
    language: str = "ru"


@router.post("/suggestions")
async def suggest_program_content(payload: SuggestionRequest, current_user: User = Depends(get_current_user)):
    """Return localized starter goals and LOs for the wizard.

    This endpoint is deliberately deterministic: it remains available when an
    external LLM is unavailable, while keeping the response contract ready for
    a future reviewed AI provider.
    """
    lang = normalize_language(payload.language)
    name = payload.name.strip() or ("образовательной программы" if lang == "ru" else "білім беру бағдарламасы" if lang == "kk" else "the programme")
    d1 = payload.domain1.strip() or ("выбранной области" if lang == "ru" else "таңдалған сала" if lang == "kk" else "the selected domain")
    d2 = payload.domain2.strip()
    # Ask the configured provider on every click when credentials are present.
    # The deterministic catalog below remains the auditable fallback.
    ai_prompt = (f"Create content for an educational programme named '{name}' in '{d1}'"
                 + (f" and '{d2}'" if d2 else "")
                 + f""".
Return ONLY JSON with exactly two arrays: goals (exactly 3 concise goals) and learning_outcomes (exactly 6 measurable outcomes). Write all text in { {'ru':'Russian','kk':'Kazakh','en':'English'}.get(lang, 'Russian') }. Goals must describe the programme purpose; outcomes must start with an observable verb and be aligned with the domain(s). Do not mention AI or that you are generating suggestions unless it is part of the programme name."""
                )
    api_key = settings.LLM_API_KEY
    pydantic_result = run_pydantic_ai_suggestions(ai_prompt, required_terms=(d1, d2))
    if pydantic_result:
        return {**pydantic_result, "source": "pydantic_ai", "ai_generated": True, "language": lang}
    if api_key and not api_key.startswith("sk-placeholder"):
        try:
            from openai import OpenAI
            kwargs = {"api_key": api_key, "timeout": 20.0, "max_retries": 0}
            if settings.LLM_BASE_URL:
                kwargs["base_url"] = settings.LLM_BASE_URL
            response = OpenAI(**kwargs).chat.completions.create(
                model=settings.LLM_MODEL_NAME,
                messages=[{"role": "system", "content": "Return valid JSON only."}, {"role": "user", "content": ai_prompt}],
                temperature=0.4, max_tokens=1800, response_format={"type": "json_object"},
            )
            data = json.loads(response.choices[0].message.content or "{}")
            goals = [str(x).strip() for x in data.get("goals", []) if str(x).strip()][:3]
            los = [str(x).strip() for x in data.get("learning_outcomes", []) if str(x).strip()][:6]
            if len(goals) == 3 and len(los) >= 3:
                validated = validate_suggestions({"goals": goals, "learning_outcomes": los}, required_terms=(d1, d2))
                return {**validated.model_dump(), "source": "openai_api", "ai_generated": True, "language": lang}
        except Exception as exc:
            # Keep the endpoint available through the reviewed deterministic
            # template, but leave an actionable server-side diagnostic.  Do
            # not log prompts, credentials, or provider response bodies.
            logger.warning(
                "AI programme suggestions failed; deterministic fallback used (%s)",
                exc.__class__.__name__,
            )

    if lang == "kk":
        goals = [
            f"{name} бойынша {d1} саласында теория мен практиканы біріктіретін құзыретті мамандар даярлау.",
            f"{d1} және {d2 or 'іргелес салалар'} үшін цифрлық шешімдерді жобалау және енгізу дағдыларын қалыптастыру.",
            f"{name} түлектерінің зерттеу, инновация және жауапты кәсіби қызметке дайындығын қамтамасыз ету.",
        ]
        los = [
            f"{d1} саласының негізгі теориялары мен әдістерін түсіндіру.",
            "Кәсіби міндеттерді шешу үшін деректер мен цифрлық құралдарды қолдану.",
            "Кәсіби шешімдерді жобалау, іске асыру және нәтижесін бағалау.",
            "Зерттеу әдістерін қолданып, дәлелді қорытынды жасау.",
            "Кәсіби нәтижелерді қазақ, орыс және шетел тілдерінде ұсыну.",
            "Этикалық, қауіпсіз және тұрақты кәсіби қызмет қағидаларын сақтау.",
        ]
    elif lang == "en":
        goals = [
            f"Prepare competent graduates for {name} by integrating theory and practice in {d1}.",
            f"Develop the ability to design and implement digital solutions for {d1} and {d2 or 'related fields'}.",
            f"Enable graduates of {name} to conduct research, innovate, and work responsibly in professional settings.",
        ]
        los = [
            f"Explain the key theories and methods of {d1}.",
            "Use data and digital tools to solve professional problems.",
            "Design, implement, and evaluate professional solutions.",
            "Apply research methods and draw evidence-based conclusions.",
            "Present professional results in Kazakh, Russian, and a foreign language.",
            "Follow ethical, safe, and sustainable professional practice principles.",
        ]
    else:
        goals = [
            f"Подготовить компетентных выпускников программы «{name}», объединяя теорию и практику в области {d1}.",
            f"Сформировать навыки проектирования и внедрения цифровых решений для области {d1}{(' и ' + d2) if d2 else ''}.",
            f"Обеспечить готовность выпускников программы «{name}» к исследованиям, инновациям и ответственной профессиональной деятельности.",
        ]
        los = [
            f"Объяснять основные теории и методы области {d1}.",
            "Применять данные и цифровые инструменты для решения профессиональных задач.",
            "Проектировать, реализовывать и оценивать профессиональные решения.",
            "Применять методы исследования и формулировать обоснованные выводы.",
            "Представлять профессиональные результаты на казахском, русском и иностранном языках.",
            "Соблюдать принципы этичной, безопасной и устойчивой профессиональной деятельности.",
        ]
    validated = validate_suggestions({"goals": goals, "learning_outcomes": los}, required_terms=(d1, d2))
    return {**validated.model_dump(), "source": "deterministic_template", "ai_generated": False, "language": lang}


@router.post("", response_model=ProjectResponse)
async def create_project(
    project_data: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new educational program project"""
    
    try:
        project = Project(
            title=project_data.title,
            domain1=project_data.domain1,
            domain2=project_data.domain2,
            goal=project_data.goal,
            constraints_json=project_data.constraints,
            created_by=current_user.id
        )
        db.add(project)
        db.flush()
        version = ProjectVersion(project_id=project.id, version_number=1, status="draft")
        db.add(version)
        db.flush()
        for idx, lo_data in enumerate(project_data.learning_outcomes):
            db.add(LearningOutcome(
                project_version_id=version.id,
                lo_code=lo_data.lo_code,
                lo_text=lo_data.lo_text,
                taxonomy_level=lo_data.taxonomy_level,
                order_index=idx
            ))
        db.commit()
    except Exception as exc:
        db.rollback()
        # Return a short actionable error instead of leaving the client waiting
        # for a generic 500 after the transaction has already failed.
        raise HTTPException(status_code=422, detail=f"Не удалось сохранить программу: {exc.__class__.__name__}") from exc
    db.refresh(project)
    
    return project


@router.get("/{project_id}")
async def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get project details with latest version"""
    project = db.query(Project).filter(Project.id == project_id).first()
    
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
    
    # Get latest version
    latest_version = db.query(ProjectVersion).filter(
        ProjectVersion.project_id == project_id
    ).order_by(ProjectVersion.version_number.desc()).first()
    
    return {
        "id": project.id,
        "title": project.title,
        "domain1": project.domain1,
        "domain2": project.domain2,
        "goal": project.goal,
        "constraints": project.constraints_json,
        "latest_version": {
            "id": latest_version.id,
            "version_number": latest_version.version_number,
            "status": latest_version.status,
            "learning_outcomes": [
                {
                    "id": lo.id,
                    "lo_code": lo.lo_code,
                    "lo_text": lo.lo_text,
                    "weight": lo.weight or 1.0,
                    "taxonomy_level": lo.taxonomy_level
                }
                for lo in latest_version.learning_outcomes
            ]
        } if latest_version else None
    }


@router.patch("/{project_id}/constraints")
async def update_project_constraints(
    project_id: int,
    payload: ProjectConstraintsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update EPVO/program constraints without deleting existing plans."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
    project.constraints_json = payload.constraints
    db.commit()
    return {"status": "success", "project_id": project.id, "constraints": project.constraints_json}


@router.get("", response_model=List[ProjectResponse])
async def list_projects(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all projects"""
    projects = db.query(Project).offset(skip).limit(limit).all()
    # Ensure they have constraints and version info
    result = []
    for p in projects:
        latest = db.query(ProjectVersion).filter(ProjectVersion.project_id == p.id).order_by(ProjectVersion.version_number.desc()).first()
        result.append({
            "id": p.id,
            "title": p.title,
            "domain1": p.domain1,
            "domain2": p.domain2,
            "goal": p.goal,
            "constraints": p.constraints_json,
            "created_at": p.created_at,
            "status": latest.status if latest else "draft",
            "learning_outcomes": [lo.lo_code for lo in latest.learning_outcomes] if latest else []
        })
    return result
@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a project and all its versions"""
    # SQLite permits one writer at a time. Deleting any project while a plan
    # build writes hundreds of match rows can lock both operations.
    from app.api.planner import _plan_build_status
    running = [
        version_id for version_id, status in _plan_build_status.items()
        if status.get("state") == "running"
    ]
    if running:
        raise HTTPException(
            status_code=409,
            detail="Сейчас строится учебный план. Дождитесь завершения генерации перед удалением проектов.",
        )
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
        
    db.delete(project)
    db.commit()
    return {"message": "Project deleted successfully"}


class WeightUpdate(BaseModel):
    lo_id: int
    weight: float


@router.post("/lo/weights")
async def update_lo_weights(
    updates: List[WeightUpdate],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update weights for multiple learning outcomes"""
    for item in updates:
        db.query(LearningOutcome).filter(LearningOutcome.id == item.lo_id).update({"weight": item.weight})
    db.commit()
    return {"status": "success"}
