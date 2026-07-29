from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import func, or_, String, cast, select
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from app.database import get_db
from app.models.user import User
from app.models.course import Course, CourseChunk, CourseLocalization
from app.models.epvo import EpvoDisciplineNormalized
from app.services.auth import get_current_user
from app.kag.indexing import index_course, index_all_courses
from app.config import settings
from app.services.content_localization import (
    course_localization_map,
    course_localization_payload,
)
from app.services.epvo_repository import _assign_epvo_prerequisites
import pandas as pd
import json
import time

router = APIRouter()
PREREQUISITE_EXEMPT_MARKER = "__prerequisite_exempt__"
_STATS_CACHE = {"expires_at": 0.0, "payload": None}
_STATS_CACHE_TTL_SECONDS = 60


def prerequisite_exempt(course: Course) -> bool:
    return PREREQUISITE_EXEMPT_MARKER in set(course.topics or [])


def upsert_course_localizations(db: Session, course_id: int, payload: Dict, source: str = "epvo") -> None:
    titles = payload.get("title") if isinstance(payload.get("title"), dict) else {}
    descriptions = payload.get("description") if isinstance(payload.get("description"), dict) else {}
    for language in ("ru", "kk", "en"):
        title = (titles.get(language) or "").strip()
        if not title:
            continue
        row = db.query(CourseLocalization).filter(
            CourseLocalization.course_id == course_id,
            CourseLocalization.language == language,
        ).first()
        if row is None:
            row = CourseLocalization(course_id=course_id, language=language)
            db.add(row)
        row.title = title
        row.description = descriptions.get(language) or row.description
        row.source = source
        row.status = "verified"


class GenerateCoursesRequest(BaseModel):
    domain: str
    count: int = 10


class AutoAssignRequisitesRequest(BaseModel):
    domain: str = ""  # empty string means all domains
    direction_code: Optional[str] = None
    group_code: Optional[str] = None


class ReindexEpvoScopeRequest(BaseModel):
    direction_code: Optional[str] = None
    group_code: Optional[str] = None



class CourseCreate(BaseModel):
    course_id: str
    title: str
    domain: str
    credits: int
    recommended_semester: Optional[int] = None
    description: Optional[str] = None
    topics: Optional[List[str]] = None
    learning_outcomes: Optional[List[str]] = None
    cycle_component: Optional[str] = None


class CourseResponse(BaseModel):
    id: int
    course_id: str
    title: str
    title_translations: Dict = Field(default_factory=dict)
    description: Optional[str] = None
    description_translations: Dict = Field(default_factory=dict)
    translation_status: Optional[str] = None
    domain: str
    credits: int
    recommended_semester: Optional[int]
    cycle_component: Optional[str]
    prerequisites: List[Dict] = []
    postrequisites: List[Dict] = []
    prerequisite_exempt: bool = False
    
    class Config:
        from_attributes = True


@router.post("/courses/import")
async def import_courses(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Import courses from XLSX/CSV/JSON file"""
    
    if not file.filename:
        raise HTTPException(status_code=400, detail="Файл не выбран")
    
    file_ext = file.filename.split(".")[-1].lower()
    
    try:
        if file_ext == "xlsx":
            df = pd.read_excel(file.file)
        elif file_ext == "csv":
            df = pd.read_csv(file.file)
        elif file_ext == "json":
            data = json.load(file.file)
            df = pd.DataFrame(data)
        else:
            raise HTTPException(status_code=400, detail="Формат файла не поддерживается")
        
        # Validate required columns
        required_cols = ["course_id", "title", "domain", "credits"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise HTTPException(
                status_code=400,
                detail=f"Отсутствуют обязательные столбцы: {missing_cols}"
            )
        
        imported_count = 0
        errors = []
        
        for idx, row in df.iterrows():
            try:
                # Check if course already exists
                existing = db.query(Course).filter(
                    Course.course_id == row["course_id"]
                ).first()
                
                if existing:
                    errors.append(f"Row {idx}: Course {row['course_id']} already exists")
                    continue
                
                # Parse topics and LOs if they're strings
                topics = row.get("topics")
                if isinstance(topics, str):
                    topics = [t.strip() for t in topics.split("|")]
                
                los = row.get("learning_outcomes")
                if isinstance(los, str):
                    los = [lo.strip() for lo in los.split("|")]
                
                course = Course(
                    course_id=row["course_id"],
                    title=row["title"],
                    domain=row["domain"],
                    credits=int(row["credits"]),
                    recommended_semester=int(row["recommended_semester"]) if pd.notna(row.get("recommended_semester")) else None,
                    description=row.get("description"),
                    topics=topics,
                    learning_outcomes=los,
                    cycle_component=row.get("cycle_component")
                )
                
                db.add(course)
                db.flush()
                
                # Index the course
                index_course(course, db)
                
                imported_count += 1
                
            except Exception as e:
                errors.append(f"Row {idx}: {str(e)}")
        
        db.commit()
        
        return {
            "imported": imported_count,
            "errors": errors,
            "total_rows": len(df)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Не удалось импортировать данные: {str(e)}")


@router.get("/stats")
async def repository_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    now = time.monotonic()
    if _STATS_CACHE["payload"] is not None and now < float(_STATS_CACHE["expires_at"]):
        return _STATS_CACHE["payload"]
    total = db.query(func.count(Course.id)).scalar() or 0
    domains = [
        {"domain": domain or "unknown", "count": int(count)}
        for domain, count in db.query(Course.domain, func.count(Course.id)).group_by(Course.domain).all()
    ]
    payload = {"total_courses": int(total), "domains": domains, "cached_for_seconds": _STATS_CACHE_TTL_SECONDS}
    _STATS_CACHE["payload"] = payload
    _STATS_CACHE["expires_at"] = now + _STATS_CACHE_TTL_SECONDS
    return payload


@router.get("/courses", response_model=List[CourseResponse])
async def list_courses(
    domain: Optional[str] = None,
    direction_code: Optional[str] = None,
    group_code: Optional[str] = None,
    search: Optional[str] = None,
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    include_descriptions: bool = False,
    include_relations: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List courses with optional filtering"""
    if page_size is not None:
        limit = max(1, min(int(page_size), 200))
    if page is not None:
        skip = max(0, int(page) - 1) * limit
    query = db.query(Course)
    
    if domain:
        query = query.filter(Course.domain == domain)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(or_(Course.title.ilike(pattern), Course.course_id.ilike(pattern)))

    if direction_code or group_code:
        # Canonical repository courses can represent many normalized EPVO rows.
        # Filter through approved_course_id, not through the legacy EPVO-{row}
        # code; otherwise whole directions such as 7M083 appeared empty.
        normalized_query = db.query(EpvoDisciplineNormalized.approved_course_id).filter(
            EpvoDisciplineNormalized.approved_course_id.isnot(None)
        )
        if direction_code:
            normalized_query = normalized_query.filter(
                cast(EpvoDisciplineNormalized.direction_codes, String).like(f'%"{direction_code}"%')
            )
        if group_code:
            normalized_query = normalized_query.filter(
                cast(EpvoDisciplineNormalized.group_codes, String).like(f'%"{group_code}"%')
            )
        allowed_subquery = normalized_query.distinct().subquery()
        courses = query.filter(
            Course.id.in_(select(allowed_subquery.c.approved_course_id))
        ).order_by(Course.id.desc()).offset(skip).limit(limit).all()
    else:
        courses = query.order_by(Course.id.desc()).offset(skip).limit(limit).all()
    # Format for response
    results = []
    localization_by_course = course_localization_map(db, [c.id for c in courses], include_descriptions=include_descriptions)
    for c in courses:
        localization = localization_by_course.get(c.id, {})
        results.append({
            "id": c.id,
            "course_id": c.course_id,
            "title": c.title,
            "title_translations": localization.get("title_translations", {}),
            "description_translations": localization.get("description_translations", {}) if include_descriptions else {},
            "translation_status": localization.get("translation_status"),
            "domain": c.domain,
            "credits": c.credits,
            "description": c.description if include_descriptions else None,
            "recommended_semester": c.recommended_semester,
            "prerequisite_exempt": prerequisite_exempt(c),
            "cycle_component": c.cycle_component,
            "prerequisites": [{"id": p.id, "course_id": p.course_id, "title": p.title} for p in c.prerequisites] if include_relations else [],
            "postrequisites": [{"id": p.id, "course_id": p.course_id, "title": p.title} for p in c.postrequisites] if include_relations else []
        })
    return results


@router.post("/courses")
async def create_course(
    course_data: CourseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a single course manually"""
    # Check for duplicate course_id
    existing = db.query(Course).filter(Course.course_id == course_data.course_id).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Дисциплина с кодом «{course_data.course_id}» уже существует")

    course = Course(
        course_id=course_data.course_id,
        title=course_data.title,
        domain=course_data.domain,
        credits=course_data.credits,
        cycle_component=course_data.cycle_component,
        description=getattr(course_data, 'description', None),
        recommended_semester=getattr(course_data, 'recommended_semester', None),
        topics=[],
        learning_outcomes=[],
    )
    db.add(course)
    db.flush()
    try:
        index_course(course, db)
    except Exception:
        pass
    db.commit()
    localization = course_localization_payload(db, course.id)
    return {
        "id": course.id,
        "course_id": course.course_id,
        "title": course.title,
        "title_translations": localization.get("title_translations", {}),
        "description_translations": localization.get("description_translations", {}),
        "domain": course.domain,
        "credits": course.credits,
        "description": course.description,
        "cycle_component": course.cycle_component,
        "recommended_semester": course.recommended_semester,
        "prerequisite_exempt": prerequisite_exempt(course),
        "prerequisites": [],
        "postrequisites": []
    }


@router.post("/reindex-epvo-scope")
async def reindex_epvo_scope(
    request: ReindexEpvoScopeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Promote one normalized EPVO scope into the approved repository.

    Raw EPVO records remain untouched; this only creates/links canonical courses
    for the direction or group currently requested in the repository screen.
    """
    direction_code = (request.direction_code or "").strip()
    group_code = (request.group_code or "").strip()
    if not direction_code and not group_code:
        raise HTTPException(status_code=400, detail="Выберите направление подготовки или группу ОП")

    rows_query = db.query(EpvoDisciplineNormalized)
    scope_filters = []
    if direction_code:
        scope_filters.append(cast(EpvoDisciplineNormalized.direction_codes, String).like(f'%"{direction_code}"%'))
    if group_code:
        scope_filters.append(cast(EpvoDisciplineNormalized.group_codes, String).like(f'%"{group_code}"%'))
    rows = rows_query.filter(or_(*scope_filters)).all()
    if not rows:
        raise HTTPException(status_code=404, detail="В нормализованном слое ЕПВО дисциплины не найдены")

    existing = db.query(Course).all()
    by_title = {" ".join((course.title or "").lower().split()): course for course in existing if course.title}
    by_code = {course.course_id: course for course in existing}
    translations, approved_courses, created, linked = {}, [], 0, 0
    scope_label = group_code or direction_code
    for row in rows:
        content = row.content_json or {}
        title = row.title_ru or row.title_kk or row.title_en or row.canonical_title
        if not title or len(title.strip()) < 3:
            continue
        key = " ".join(title.lower().split())
        course = by_code.get(f"EPVO-{row.id}") or by_title.get(key)
        description_ru = content.get("description_ru") or content.get("description") or ""
        if course is None:
            course = Course(
                course_id=f"EPVO-{row.id}", title=title.strip(), domain=direction_code or group_code,
                credits=min(10, max(2, int(round(float(row.typical_credits or 5))))),
                recommended_semester=max(1, int(row.typical_semester or 1)),
                description=description_ru or f"Дисциплина из нормализованного репозитория ЕПВО ({scope_label}).",
                topics=[], learning_outcomes=[], cycle_component="дисциплина ЕПВО", language="ru",
            )
            db.add(course)
            db.flush()
            db.add(CourseChunk(course_id=course.id, chunk_type="description", chunk_text=course.description, chunk_index=0))
            by_code[course.course_id] = course
            by_title[key] = course
            created += 1
        else:
            linked += 1
        row.approved_course_id = course.id
        row.status = "approved"
        translations[course.id] = {
            "title": {"ru": row.title_ru, "kk": row.title_kk, "en": row.title_en},
            "description": {
                "ru": description_ru or course.description,
                "kk": content.get("description_kk") or description_ru or course.description,
                "en": content.get("description_en") or description_ru or course.description,
            },
            "review_status": "verified_epvo", "source": "epvo_normalized_repository",
        }
        upsert_course_localizations(db, course.id, translations[course.id], "epvo")
        approved_courses.append(course)

    _assign_epvo_prerequisites(list({course.id: course for course in approved_courses}.values()))
    db.commit()
    return {"scope": scope_label, "normalized": len(rows), "created": created, "linked": linked, "available": len(approved_courses)}


@router.get("/courses/{course_id}")
async def get_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get course details"""
    course = db.query(Course).filter(Course.id == course_id).first()
    
    if not course:
        raise HTTPException(status_code=404, detail="Дисциплина не найдена")
    
    localization = course_localization_payload(db, course.id)
    return {
        "id": course.id,
        "course_id": course.course_id,
        "title": course.title,
        "title_translations": localization.get("title_translations", {}),
        "domain": course.domain,
        "credits": course.credits,
        "description": course.description,
        "description_translations": localization.get("description_translations", {}),
        "translation_status": localization.get("translation_status"),
        "prerequisite_exempt": prerequisite_exempt(course),
        "cycle_component": course.cycle_component,
        "prerequisites": [{"id": p.id, "course_id": p.course_id, "title": p.title} for p in course.prerequisites],
        "postrequisites": [{"id": p.id, "course_id": p.course_id, "title": p.title} for p in course.postrequisites]
    }
@router.put("/courses/{course_id}")
async def update_course(
    course_id: int,
    course_data: Dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update course details and prerequisites"""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Дисциплина не найдена")
    
    if "title" in course_data: course.title = course_data["title"]
    if "domain" in course_data: course.domain = course_data["domain"]
    if "credits" in course_data: course.credits = course_data["credits"]
    if "cycle_component" in course_data: course.cycle_component = course_data["cycle_component"]
    if "prerequisite_exempt" in course_data:
        topics = [topic for topic in (course.topics or []) if topic != PREREQUISITE_EXEMPT_MARKER]
        if course_data["prerequisite_exempt"]:
            topics.append(PREREQUISITE_EXEMPT_MARKER)
            course.prerequisites = []
        course.topics = topics
    
    # Prerequisite management
    if "prerequisites" in course_data: # List of course_ids (internal IDs)
        course.prerequisites = []
        for p_id in course_data["prerequisites"]:
            pre = db.query(Course).filter(Course.id == p_id).first()
            if pre:
                course.prerequisites.append(pre)
    
    db.commit()
    # Re-index course after update
    index_course(course, db)
    return course


@router.delete("/courses/{course_id}")
async def delete_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a course and its chunks/embeddings"""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Дисциплина не найдена")
    
    db.delete(course)
    db.commit()
    return {"message": "Course deleted successfully"}


@router.post("/generate-courses")
async def generate_courses_with_llm(
    request: GenerateCoursesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate courses using LLM for a given domain and save them to the repository."""
    count = max(1, min(50, request.count))
    domain = request.domain.strip()
    if not domain:
        raise HTTPException(status_code=400, detail="Область подготовки не может быть пустой")

    api_key = settings.LLM_API_KEY
    has_real_key = api_key and not api_key.startswith("sk-placeholder")

    prompt = f"""You are an expert curriculum designer.
Generate exactly {count} university course descriptions for the domain: "{domain}".

Return a JSON object with a single key "courses" containing an array of {count} course objects.
Each course object must have these fields:
- course_id: unique code like "CS101", "DA301", etc. (no duplicates)
- title: descriptive course title in English
- domain: "{domain}"
- credits: integer between 3 and 6
- description: 2-3 sentence description of the course
- topics: list of 6-10 topic strings
- learning_outcomes: list of 4-6 outcomes (what students will be able to do)
- cycle_component: one of "mandatory", "elective", "university"
- recommended_semester: integer 1-8

Important: Return ONLY valid JSON, no markdown formatting."""

    if has_real_key and settings.LLM_PROVIDER == "openai":
        try:
            from openai import OpenAI
            client_kwargs = {"api_key": api_key}
            if settings.LLM_BASE_URL:
                client_kwargs["base_url"] = settings.LLM_BASE_URL
            client = OpenAI(**client_kwargs)

            # Batch into groups of 10 to avoid token limit truncation
            BATCH_SIZE = 10
            all_courses_raw = []
            batches = [list(range(i, min(i + BATCH_SIZE, count))) for i in range(0, count, BATCH_SIZE)]

            for batch_idx, batch in enumerate(batches):
                batch_count = len(batch)
                batch_start = batch_idx * BATCH_SIZE + 1
                batch_prompt = f"""You are an expert curriculum designer.
Generate exactly {batch_count} university course descriptions for the domain: "{domain}".
This is batch {batch_idx + 1} of {len(batches)} — courses number {batch_start} to {batch_start + batch_count - 1}.
Use unique course codes that don't conflict with other batches (e.g. use prefix like \"{domain[:2].upper()}{batch_idx}{batch_idx+1}##\").

Return a JSON object with a single key "courses" containing an array of exactly {batch_count} course objects.
Each course object must have:
- course_id: unique short code (e.g. "EE101")
- title: descriptive course title in English
- domain: "{domain}"
- credits: integer 3-6
- description: 2-3 sentence course description
- topics: list of 4-8 topic strings
- learning_outcomes: list of 3-5 outcome strings
- cycle_component: one of "mandatory", "elective", "university"
- recommended_semester: integer 1-8

Return ONLY valid JSON, no markdown."""

                resp = client.chat.completions.create(
                    model=settings.LLM_MODEL_NAME,
                    messages=[
                        {"role": "system", "content": "You are an expert curriculum designer. Always respond with valid JSON only."},
                        {"role": "user", "content": batch_prompt}
                    ],
                    temperature=0.8,
                    max_tokens=6000,
                    response_format={"type": "json_object"}
                )
                batch_raw = resp.choices[0].message.content
                batch_parsed = json.loads(batch_raw)
                all_courses_raw.extend(batch_parsed.get("courses", []))

            raw = json.dumps({"courses": all_courses_raw})
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=500, detail=f"Языковая модель вернула некорректные данные: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Не удалось обратиться к языковой модели: {str(e)}")

    else:
        # Mock response when no real API key is configured
        def _make_mock_course(i: int):
            return {
                "course_id": f"{domain[:2].upper()}{100 + i}",
                "title": f"{domain} Fundamentals {i}",
                "domain": domain,
                "credits": 4,
                "description": f"An introduction to core principles and practices of {domain}.",
                "topics": ["Introduction", "Core Concepts", "Practical Applications", "Case Studies", "Project Work"],
                "learning_outcomes": [f"Understand key concepts of {domain}", "Apply theoretical knowledge practically"],
                "cycle_component": "elective",
                "recommended_semester": (i % 8) + 1
            }
        raw = json.dumps({"courses": [_make_mock_course(i) for i in range(count)]})

    try:
        parsed = json.loads(raw)
        courses_data = parsed.get("courses", [])
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Языковая модель вернула некорректные данные")

    created = []
    for c_data in courses_data:
        base_id = c_data.get("course_id", f"{domain[:3].upper()}000")
        # Ensure unique course_id in DB
        course_id = base_id
        suffix = 1
        while db.query(Course).filter(Course.course_id == course_id).first():
            course_id = f"{base_id}_{suffix}"
            suffix += 1

        course = Course(
            course_id=course_id,
            title=c_data.get("title", "Generated Course"),
            domain=c_data.get("domain", domain),
            credits=int(c_data.get("credits", 4)),
            description=c_data.get("description"),
            topics=c_data.get("topics", []),
            learning_outcomes=c_data.get("learning_outcomes", []),
            cycle_component=c_data.get("cycle_component"),
            recommended_semester=c_data.get("recommended_semester"),
        )
        db.add(course)
        db.flush()
        try:
            index_course(course, db)
        except Exception:
            pass
        created.append({
            "id": course.id,
            "course_id": course.course_id,
            "title": course.title,
            "domain": course.domain,
            "credits": course.credits,
            "cycle_component": course.cycle_component,
        })

    db.commit()
    return {"generated": len(created), "courses": created}


@router.post("/auto-assign-requisites")
async def auto_assign_requisites(
    request: AutoAssignRequisitesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Use AI to automatically assign prerequisites for courses in a domain."""
    api_key = settings.LLM_API_KEY
    has_real_key = api_key and not api_key.startswith("sk-placeholder")

    all_db_courses = db.query(Course).all()
    domain = request.domain.strip()
    if request.direction_code or request.group_code:
        normalized_query = db.query(EpvoDisciplineNormalized.approved_course_id).filter(
            EpvoDisciplineNormalized.approved_course_id.isnot(None)
        )
        if request.direction_code:
            normalized_query = normalized_query.filter(cast(EpvoDisciplineNormalized.direction_codes, String).like(f'%"{request.direction_code}"%'))
        if request.group_code:
            normalized_query = normalized_query.filter(cast(EpvoDisciplineNormalized.group_codes, String).like(f'%"{request.group_code}"%'))
        approved_ids = {row[0] for row in normalized_query.distinct().all() if row[0] is not None}
        all_courses = [course for course in all_db_courses if course.id in approved_ids]
    elif domain:
        domain_norm = domain.lower().strip().strip('"').strip("'")
        all_courses = [c for c in all_db_courses
                       if c.domain and c.domain.lower().strip().strip('"').strip("'") == domain_norm]
    else:
        all_courses = all_db_courses

    if not all_courses:
        raise HTTPException(status_code=404, detail="Для этой области подготовки дисциплины не найдены")

    all_courses = [course for course in all_courses if not prerequisite_exempt(course)]
    if not all_courses:
        return {"updated": 0, "total_courses": 0, "skipped_exempt": True, "domain": domain or request.direction_code or request.group_code or "all"}
    if request.direction_code or request.group_code:
        updated = _assign_epvo_prerequisites(all_courses)
        db.commit()
        return {
            "updated": updated,
            "total_courses": len(all_courses),
            "domain": request.direction_code or request.group_code,
            "method": "epvo_semester_and_subject_overlap",
            "message": "Добавлены только связи с более ранними и содержательно близкими дисциплинами.",
        }
    courses_for_ai = [
        {
            "course_id": c.course_id,
            "title": c.title,
            "credits": c.credits,
            "recommended_semester": c.recommended_semester,
            "description": (c.description or "")[:150],
            "topics": [topic for topic in (c.topics or []) if topic != PREREQUISITE_EXEMPT_MARKER][:5]
        }
        for c in all_courses
    ]

    prompt = (
        f'''You are an expert curriculum designer.\n'''
        f'''Below is a list of university courses in the domain: "{domain or 'Mixed domains'}".\n'''
        """Assign logical prerequisites for each course. Create coherent progression.

Courses:
"""
        + json.dumps(courses_for_ai, ensure_ascii=False, indent=2)
        + """

Return JSON with key "assignments" — array of objects:
- "course_id": exact course code from list
- "prerequisites": list of course_id strings to take BEFORE this course ([] if none)

Rules: no self-prereqs, only use listed ids, semester 1 courses get [].
Return ONLY valid JSON."""
    )

    if has_real_key and settings.LLM_PROVIDER == "openai":
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            resp = client.chat.completions.create(
                model=settings.LLM_MODEL_NAME,
                messages=[
                    {"role": "system", "content": "You are a curriculum expert. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=8000,
                response_format={"type": "json_object"}
            )
            raw = resp.choices[0].message.content
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Не удалось обратиться к языковой модели: {str(e)}")
    else:
        sorted_c = sorted(all_courses, key=lambda c: (c.recommended_semester or 9, c.course_id))
        mock_assigns = []
        for i, c in enumerate(sorted_c):
            prereqs = []
            if i > 0 and (c.recommended_semester or 1) > (sorted_c[i-1].recommended_semester or 1):
                prereqs = [sorted_c[i-1].course_id]
            mock_assigns.append({"course_id": c.course_id, "prerequisites": prereqs})
        raw = json.dumps({"assignments": mock_assigns})

    try:
        parsed = json.loads(raw)
        assignments = parsed.get("assignments", [])
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="ИИ вернул некорректные данные")

    course_map = {c.course_id: c for c in all_courses}
    updated = 0
    for item in assignments:
        cid = item.get("course_id")
        prereq_ids = item.get("prerequisites", [])
        course_obj = course_map.get(cid)
        if not course_obj or prerequisite_exempt(course_obj):
            continue
        course_obj.prerequisites = [
            course_map[pid] for pid in prereq_ids
            if pid != cid and pid in course_map
        ]
        updated += 1

    db.commit()
    return {"updated": updated, "total_courses": len(all_courses), "domain": domain or request.direction_code or request.group_code or "all"}
