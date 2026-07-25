from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func, text
from fastapi import Response
from sqlalchemy.orm import Session
import re
import csv
import io
import subprocess
import sys

from app.database import get_db
from app.models.epvo import EpvoDirection, EpvoDisciplineLoLink, EpvoDisciplineNormalized, EpvoGroup, RawEpvoLearningOutcome, RawEpvoProgram
from app.models.user import User
from app.models.plan import Plan, PlanItem
from app.models.project import LearningOutcome, Project, ProjectVersion
from app.models.course import Course, CourseLocalization
from app.models.embedding import MatchScore
from app.models.embedding import MatchFeedback
from app.services.auth import get_current_user
from app.services.epvo_repository import (
    epvo_row_is_relevant,
    epvo_row_relevance_score,
    epvo_row_matches_education_level,
)
import json
from pathlib import Path
import time


router = APIRouter()
PASSPORT_FILE = Path(__file__).resolve().parents[2] / "experiment-results" / "dataset-passport.json"
BASELINE_REPORT_FILE = Path(__file__).resolve().parents[2] / "experiment-results" / "reproducible-baseline" / "baseline-report.json"
LSTM_GNN_MANIFEST_FILE = Path(__file__).resolve().parents[2] / "experiment-results" / "lstm-gnn-controlled-run" / "manifest.json"
LSTM_GNN_RUN_DIR = Path(__file__).resolve().parents[2] / "experiment-results" / "lstm-gnn-controlled-run"
LSTM_GNN_STATUS_FILE = LSTM_GNN_RUN_DIR / "run-status.json"
LSTM_STATUS_FILE = LSTM_GNN_RUN_DIR / "lstm-run-status.json"
ARTICLE_REPORT_DIR = Path(__file__).resolve().parents[2] / "experiment-results" / "article-experiment-report"
_COMPARE_CACHE: dict[tuple[int, str, int | None], tuple[float, dict]] = {}
_COMPARE_CACHE_TTL_SECONDS = 300
_COMPARE_SCOPE_LIMIT = 600
_COMPARE_TYPICAL_LIMIT = 40
_COMPARE_PROGRAM_LIMIT = 6
_COMPARE_LO_LIMIT = 150


def _course_from_epvo(row: EpvoDisciplineNormalized, project: Project, db: Session | None = None) -> Course:
    constraints = project.constraints_json or {}
    secondary_group = str(constraints.get("secondary_group_code") or "")
    domain = project.domain1
    if secondary_group and secondary_group in (row.group_codes or []):
        domain = project.domain2 or project.domain1
    learning_outcomes = []
    if db is not None:
        links = db.query(EpvoDisciplineLoLink).filter(EpvoDisciplineLoLink.discipline_id == row.id).limit(8).all()
        raw_keys = {link.lo_source_key for link in links if link.lo_source_key}
        if raw_keys:
            raw_los = db.query(RawEpvoLearningOutcome).filter(RawEpvoLearningOutcome.source_key.in_(raw_keys)).limit(8).all()
            for raw in raw_los:
                payload = raw.payload_json or {}
                text_value = (
                    payload.get("learningOutcomeNameRu")
                    or payload.get("nameRu")
                    or payload.get("learningOutcomeNameEn")
                    or payload.get("nameEn")
                )
                if text_value and text_value not in learning_outcomes:
                    learning_outcomes.append(text_value)
    content = row.content_json or {}
    return Course(
        course_id=f"EPVO-{row.id}",
        title=row.title_ru or row.title_en or row.canonical_title,
        domain=domain,
        credits=int(row.typical_credits or 5),
        recommended_semester=row.typical_semester,
        description=(content.get("description_ru") or content.get("description") or content.get("description_en") or row.canonical_title or ""),
        topics=content.get("topics") or [],
        learning_outcomes=learning_outcomes,
        assessment_methods=[],
        language="ru",
        cycle_component="mandatory",
    )


def epvo_translation_payload(row: EpvoDisciplineNormalized) -> dict:
    content = row.content_json or {}
    return {
        "title_translations": {"ru": row.title_ru, "kk": row.title_kk, "en": row.title_en},
        "description_translations": {
            "ru": content.get("description_ru"),
            "kk": content.get("description_kk"),
            "en": content.get("description_en"),
        },
    }


def upsert_epvo_course_localizations(db: Session, course: Course, row: EpvoDisciplineNormalized) -> None:
    payload = epvo_translation_payload(row)
    descriptions = payload["description_translations"]
    for language, title in payload["title_translations"].items():
        if not title:
            continue
        localization = db.query(CourseLocalization).filter(
            CourseLocalization.course_id == course.id,
            CourseLocalization.language == language,
        ).first()
        if localization is None:
            localization = CourseLocalization(course_id=course.id, language=language)
            db.add(localization)
        localization.title = title
        localization.description = descriptions.get(language) or localization.description
        localization.source = "epvo"
        localization.status = "verified"


def _scope_disciplines(db: Session, scope_item: dict, limit: int = 800) -> tuple[list[EpvoDisciplineNormalized], str, str]:
    scope_name = "all"
    code = scope_item["group_code"] or scope_item["direction_code"]
    if scope_item["group_code"]:
        scope_name = "group"
        ids = [
            row[0]
            for row in db.execute(
                text("select id from epvo_disciplines_normalized where cast(group_codes as text) like :pattern limit :limit"),
                {"pattern": f"%{scope_item['group_code']}%", "limit": limit},
            ).fetchall()
        ]
    elif scope_item["direction_code"]:
        scope_name = "direction"
        ids = [
            row[0]
            for row in db.execute(
                text("select id from epvo_disciplines_normalized where cast(direction_codes as text) like :pattern limit :limit"),
                {"pattern": f"%{scope_item['direction_code']}%", "limit": limit},
            ).fetchall()
        ]
    else:
        ids = [
            row[0]
            for row in db.execute(
                text("select id from epvo_disciplines_normalized limit :limit"),
                {"limit": limit},
            ).fetchall()
        ]
    rows = db.query(EpvoDisciplineNormalized).filter(EpvoDisciplineNormalized.id.in_(ids or [-1])).all()
    return rows, scope_name, code
AREA_NAMES = {
    "01": {"ru": "Педагогические науки", "kk": "Педагогикалық ғылымдар", "en": "Education"},
    "02": {"ru": "Искусство и гуманитарные науки", "kk": "Өнер және гуманитарлық ғылымдар", "en": "Arts and humanities"},
    "03": {"ru": "Социальные науки, журналистика и информация", "kk": "Әлеуметтік ғылымдар, журналистика және ақпарат", "en": "Social sciences, journalism and information"},
    "04": {"ru": "Бизнес, управление и право", "kk": "Бизнес, басқару және құқық", "en": "Business, administration and law"},
    "05": {"ru": "Естественные науки, математика и статистика", "kk": "Жаратылыстану ғылымдары, математика және статистика", "en": "Natural sciences, mathematics and statistics"},
    "06": {"ru": "Информационно-коммуникационные технологии", "kk": "Ақпараттық-коммуникациялық технологиялар", "en": "Information and communication technologies"},
    "07": {"ru": "Инженерные, обрабатывающие и строительные отрасли", "kk": "Инженерлік, өңдеу және құрылыс салалары", "en": "Engineering, manufacturing and construction"},
    "08": {"ru": "Сельское хозяйство и биоресурсы", "kk": "Ауыл шаруашылығы және биоресурстар", "en": "Agriculture and bioresources"},
    "09": {"ru": "Здравоохранение и социальное обеспечение", "kk": "Денсаулық сақтау және әлеуметтік қамсыздандыру", "en": "Health and welfare"},
    "10": {"ru": "Услуги", "kk": "Қызметтер", "en": "Services"},
    "11": {"ru": "Национальная безопасность и военное дело", "kk": "Ұлттық қауіпсіздік және әскери іс", "en": "National security and military affairs"},
}

# Override area labels to match the actual EPVO direction codes present in the
# local dataset.  In this snapshot healthcare is 6B10/7M10/8D10, services are
# 6B11/7M11/8D11, and public safety is 6B12.
AREA_NAMES.update({
    "09": {"ru": "Ветеринария", "kk": "Ветеринария", "en": "Veterinary"},
    "10": {"ru": "Здравоохранение", "kk": "Денсаулық сақтау", "en": "Health care"},
    "11": {"ru": "Сфера обслуживания, социальная работа и спорт", "kk": "Қызмет көрсету, әлеуметтік жұмыс және спорт", "en": "Services, social work and sport"},
    "12": {"ru": "Общественная безопасность", "kk": "Қоғамдық қауіпсіздік", "en": "Public safety"},
})


def localized(row, language):
    language = "kk" if language in {"kk", "kz"} else language
    return getattr(row, f"title_{language}", None) or row.title_ru or row.title_en or row.code


def _norm(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _tokens(value: str | None) -> set[str]:
    return {
        token
        for token in re.findall(r"[\w\-]+", (value or "").casefold(), flags=re.UNICODE)
        if len(token) > 2
    }


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, min(len(left), len(right)))


def _payload_title(payload: dict, language: str) -> str:
    suffix = "Kz" if language in {"kk", "kz"} else "En" if language == "en" else "Ru"
    return (
        payload.get(f"eduProgramName{suffix}")
        or payload.get("eduProgramNameRu")
        or payload.get("eduProgramNameEn")
        or str(payload.get("id") or "")
    )


def _payload_goal(payload: dict, language: str) -> str:
    suffix = "Kz" if language in {"kk", "kz"} else "En" if language == "en" else "Ru"
    return payload.get(f"eduGoalName{suffix}") or payload.get("eduGoalNameRu") or payload.get("eduGoalNameEn") or ""


def _metric_delta(candidate: dict | None, baseline: dict | None) -> dict:
    candidate = candidate or {}
    baseline = baseline or {}
    keys = ("roc_auc", "pr_auc", "f1")
    deltas = {
        key: round(float(candidate.get(key) or 0) - float(baseline.get(key) or 0), 6)
        for key in keys
    }
    beats = all(deltas[key] > 0 for key in ("roc_auc", "pr_auc")) and deltas["f1"] >= 0
    return {
        "deltas": deltas,
        "beats_baseline": beats,
        "decision": "candidate_can_be_integrated" if beats else "keep_as_experiment",
        "guardrail": "Integrate only if ROC-AUC and PR-AUC improve and F1 does not decrease on the frozen split.",
    }


def _best_model_from_baseline() -> dict:
    if not BASELINE_REPORT_FILE.exists():
        return {}
    try:
        return json.loads(BASELINE_REPORT_FILE.read_text(encoding="utf-8")).get("best_model") or {}
    except (OSError, ValueError):
        return {}


@router.get("/education-areas")
async def education_areas(education_level: str = Query("bachelor"), language: str = Query("ru"), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    prefix = {"bachelor": "6B", "master": "7M", "doctorate": "8D"}.get(education_level, "")
    codes = sorted({row[0] for row in db.query(EpvoDirection.education_level).filter(EpvoDirection.code.like(f"{prefix}%")).all() if row[0]})
    lang = "kk" if language in {"kk", "kz"} else language
    return [{"code": code, "title": AREA_NAMES.get(str(code)[-2:], {}).get(lang) or code} for code in codes]


@router.get("/directions")
async def directions(education_level: str = Query(""), education_area: str = Query(""), language: str = Query("ru"), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(EpvoDirection)
    prefix = {"bachelor": "6B", "master": "7M", "doctorate": "8D"}.get(education_level, "")
    if prefix:
        query = query.filter(EpvoDirection.code.like(f"{prefix}%"))
    if education_area:
        query = query.filter(EpvoDirection.education_level == education_area)
    rows = query.order_by(EpvoDirection.code).all()
    return [{"code": row.code, "title": localized(row, language), "education_level": row.education_level} for row in rows]


@router.get("/groups")
async def groups(direction_code: str, language: str = Query("ru"), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = db.query(EpvoGroup).filter(EpvoGroup.direction_code == direction_code).order_by(EpvoGroup.code).all()
    return [{"code": row.code, "title": localized(row, language), "direction_code": row.direction_code} for row in rows]


@router.get("/stats")
async def stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return {
        "raw_programs": db.query(RawEpvoProgram).count(),
        "directions": db.query(EpvoDirection).count(),
        "groups": db.query(EpvoGroup).count(),
        "normalized_disciplines": db.query(EpvoDisciplineNormalized).count(),
        "expert_links": db.query(EpvoDisciplineLoLink).count(),
    }


@router.get("/dataset-passport")
async def dataset_passport(current_user: User = Depends(get_current_user)):
    if not PASSPORT_FILE.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dataset Passport ещё не сформирован")
    return json.loads(PASSPORT_FILE.read_text(encoding="utf-8"))


@router.get("/dataset-passport/export.csv")
async def dataset_passport_csv(current_user: User = Depends(get_current_user)):
    if not PASSPORT_FILE.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dataset Passport ещё не сформирован")
    data = json.loads(PASSPORT_FILE.read_text(encoding="utf-8"))
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["section", "metric", "value"])
    writer.writerow(["passport", "created_at", data.get("created_at")])
    writer.writerow(["passport", "dataset", data.get("dataset")])
    writer.writerow(["passport", "seed", data.get("seed")])
    for key, value in (data.get("normalized") or {}).items():
        writer.writerow(["normalized", key, value])
    for key, value in (data.get("counts") or {}).items():
        writer.writerow(["split", key, value])
    for row in data.get("benchmarks") or []:
        name = row.get("name")
        for metric in ("roc_auc", "pr_auc", "f1", "precision", "recall", "accuracy", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10", "examples"):
            writer.writerow([f"benchmark:{name}", metric, row.get(metric)])
    return Response(
        content=stream.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=dataset-passport.csv"},
    )


@router.get("/expert-feedback")
async def expert_feedback_summary(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    verdict_counts = {
        verdict: int(count)
        for verdict, count in db.query(MatchFeedback.verdict, func.count(MatchFeedback.id))
        .group_by(MatchFeedback.verdict)
        .all()
    }
    rows = db.query(MatchFeedback, Course, LearningOutcome).join(
        Course, Course.id == MatchFeedback.course_id
    ).join(
        LearningOutcome, LearningOutcome.id == MatchFeedback.lo_id
    ).order_by(MatchFeedback.created_at.desc()).limit(limit).all()
    recent = []
    for feedback, course, lo in rows:
        snapshot = feedback.model_snapshot_json or {}
        recent.append({
            "id": feedback.id,
            "project_version_id": feedback.project_version_id,
            "course_id": feedback.course_id,
            "course_title": course.title,
            "lo_id": feedback.lo_id,
            "lo_code": lo.lo_code,
            "lo_text": lo.lo_text,
            "verdict": feedback.verdict,
            "corrected_score": feedback.corrected_score,
            "comment": feedback.comment,
            "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
            "model_score": snapshot.get("score"),
            "model_name": snapshot.get("model_name"),
            "model_version": snapshot.get("model_version"),
        })
    return {"total": sum(verdict_counts.values()), "verdict_counts": verdict_counts, "recent": recent}


@router.get("/reproducible-baseline")
async def reproducible_baseline(current_user: User = Depends(get_current_user)):
    if not BASELINE_REPORT_FILE.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Reproducible baseline report ещё не сформирован")
    return json.loads(BASELINE_REPORT_FILE.read_text(encoding="utf-8"))


@router.get("/lstm-gnn-manifest")
async def lstm_gnn_manifest(current_user: User = Depends(get_current_user)):
    if not LSTM_GNN_MANIFEST_FILE.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="LSTM/GNN manifest ещё не подготовлен")
    return json.loads(LSTM_GNN_MANIFEST_FILE.read_text(encoding="utf-8"))


@router.get("/article-experiment-report")
async def article_experiment_report(current_user: User = Depends(get_current_user)):
    path = ARTICLE_REPORT_DIR / "article-experiment-report.json"
    if not path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Article experiment report ещё не сформирован")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/article-experiment-report.md")
async def article_experiment_report_markdown(current_user: User = Depends(get_current_user)):
    path = ARTICLE_REPORT_DIR / "article-experiment-report.md"
    if not path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Article experiment report ещё не сформирован")
    return Response(
        content=path.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=article-experiment-report.md"},
    )


@router.get("/lstm-gnn-smoke/status")
async def lstm_gnn_smoke_status(current_user: User = Depends(get_current_user)):
    LSTM_GNN_RUN_DIR.mkdir(parents=True, exist_ok=True)
    metrics_path = LSTM_GNN_RUN_DIR / "gnn-smoke" / "metrics.json"
    status = json.loads(LSTM_GNN_STATUS_FILE.read_text(encoding="utf-8")) if LSTM_GNN_STATUS_FILE.exists() else {
        "state": "idle",
        "message": "GNN smoke run has not been started.",
    }
    if metrics_path.exists():
        status["state"] = "complete"
        status["metrics_path"] = str(metrics_path)
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            status["test"] = (metrics.get("gnn") or {}).get("test")
            status["baseline_test"] = (metrics.get("baseline") or {}).get("test")
            best_model = _best_model_from_baseline()
            status["best_model"] = best_model
            status["comparison"] = _metric_delta(status.get("test"), best_model or status.get("baseline_test"))
            status["finished_at"] = status.get("finished_at") or metrics.get("created_at")
            status["returncode"] = 0 if status.get("returncode") is None else status.get("returncode")
        except (OSError, ValueError):
            status["metrics_error"] = "Could not read metrics.json"
    for name in ("gnn-smoke.stdout.log", "gnn-smoke.stderr.log"):
        path = LSTM_GNN_RUN_DIR / name
        if path.exists():
            try:
                status[name] = "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-12:])
            except OSError:
                pass
    return status


@router.post("/lstm-gnn-smoke/run")
async def run_lstm_gnn_smoke(
    payload: dict | None = Body(default=None),
    current_user: User = Depends(get_current_user),
):
    """Start a small local GNN smoke run. Does not start full GPU training."""
    from fastapi import HTTPException

    payload = payload or {}
    dry_run = bool(payload.get("dry_run"))
    force = bool(payload.get("force"))
    LSTM_GNN_RUN_DIR.mkdir(parents=True, exist_ok=True)
    output_dir = LSTM_GNN_RUN_DIR / "gnn-smoke"
    metrics_path = output_dir / "metrics.json"
    if metrics_path.exists() and not force and not dry_run:
        return {
            "state": "complete",
            "message": "Smoke metrics already exist. Use force=true to rerun.",
            "metrics_path": str(metrics_path),
        }
    existing = json.loads(LSTM_GNN_STATUS_FILE.read_text(encoding="utf-8")) if LSTM_GNN_STATUS_FILE.exists() else {}
    if existing.get("state") == "running" and not force and not dry_run and not metrics_path.exists():
        raise HTTPException(status_code=409, detail="GNN smoke run is already marked as running")

    root = Path(__file__).resolve().parents[3]
    script = root / "backend" / "scripts" / "train_epvo_gnn_pilot.py"
    splits_dir = root / "backend" / "experiment-results" / "epvo-ml-pilot" / "splits-v2"
    model_dir = root / "backend" / "models" / "epvo-sbert-finetuned-40k"
    command = [
        sys.executable,
        str(script),
        "--splits", str(splits_dir),
        "--model", str(model_dir),
        "--program-limit", str(int(payload.get("program_limit") or 80)),
        "--epochs", str(int(payload.get("epochs") or 10)),
        "--output", str(output_dir),
    ]
    if dry_run:
        return {"state": "dry_run", "command": command, "cwd": str(root)}

    stdout_path = LSTM_GNN_RUN_DIR / "gnn-smoke.stdout.log"
    stderr_path = LSTM_GNN_RUN_DIR / "gnn-smoke.stderr.log"
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=str(root), stdout=stdout, stderr=stderr)
    status = {
        "state": "running",
        "pid": process.pid,
        "command": command,
        "cwd": str(root),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "message": "GNN smoke run started. Watch status endpoint for metrics/logs.",
    }
    LSTM_GNN_STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


@router.get("/lstm-smoke/status")
async def lstm_smoke_status(current_user: User = Depends(get_current_user)):
    LSTM_GNN_RUN_DIR.mkdir(parents=True, exist_ok=True)
    metrics_path = LSTM_GNN_RUN_DIR / "lstm-smoke" / "metrics.json"
    status = json.loads(LSTM_STATUS_FILE.read_text(encoding="utf-8")) if LSTM_STATUS_FILE.exists() else {
        "state": "idle",
        "message": "LSTM smoke run has not been started.",
    }
    if metrics_path.exists():
        status["state"] = "complete"
        status["metrics_path"] = str(metrics_path)
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            status["test"] = (metrics.get("lstm") or {}).get("test")
            status["baseline_test"] = (metrics.get("baseline") or {}).get("test")
            best_model = _best_model_from_baseline()
            status["best_model"] = best_model
            status["comparison"] = _metric_delta(status.get("test"), best_model or status.get("baseline_test"))
            status["finished_at"] = status.get("finished_at") or metrics.get("created_at")
            status["returncode"] = 0 if status.get("returncode") is None else status.get("returncode")
        except (OSError, ValueError):
            status["metrics_error"] = "Could not read LSTM metrics.json"
    for name in ("lstm-smoke.stdout.log", "lstm-smoke.stderr.log"):
        path = LSTM_GNN_RUN_DIR / name
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                status[name] = "\n".join(text.splitlines()[-12:])
                if name.endswith("stderr.log") and status.get("state") == "running" and not metrics_path.exists() and ("Traceback" in text or "OutOfMemoryError" in text):
                    status["state"] = "failed"
                    status["message"] = "LSTM smoke failed; see stderr tail."
            except OSError:
                pass
    return status


@router.post("/lstm-smoke/run")
async def run_lstm_smoke(
    payload: dict | None = Body(default=None),
    current_user: User = Depends(get_current_user),
):
    """Start a small local LSTM smoke run. Does not start full GPU training."""
    from fastapi import HTTPException

    payload = payload or {}
    dry_run = bool(payload.get("dry_run"))
    force = bool(payload.get("force"))
    LSTM_GNN_RUN_DIR.mkdir(parents=True, exist_ok=True)
    output_dir = LSTM_GNN_RUN_DIR / "lstm-smoke"
    metrics_path = output_dir / "metrics.json"
    if metrics_path.exists() and not force and not dry_run:
        return {
            "state": "complete",
            "message": "LSTM smoke metrics already exist. Use force=true to rerun.",
            "metrics_path": str(metrics_path),
        }
    existing = json.loads(LSTM_STATUS_FILE.read_text(encoding="utf-8")) if LSTM_STATUS_FILE.exists() else {}
    if existing.get("state") == "running" and not force and not dry_run and not metrics_path.exists():
        raise HTTPException(status_code=409, detail="LSTM smoke run is already marked as running")

    root = Path(__file__).resolve().parents[3]
    script = root / "backend" / "scripts" / "train_epvo_lstm_pilot.py"
    splits_dir = root / "backend" / "experiment-results" / "epvo-ml-pilot" / "splits-v2"
    model_dir = root / "backend" / "models" / "epvo-sbert-finetuned-40k"
    command = [
        sys.executable,
        str(script),
        "--splits", str(splits_dir),
        "--model", str(model_dir),
        "--program-limit", str(int(payload.get("program_limit") or 40)),
        "--epochs", str(int(payload.get("epochs") or 3)),
        "--train-batch-size", str(int(payload.get("train_batch_size") or 16)),
        "--max-seq-len", str(int(payload.get("max_seq_len") or 12)),
        "--output", str(output_dir),
    ]
    if dry_run:
        return {"state": "dry_run", "command": command, "cwd": str(root)}

    stdout_path = LSTM_GNN_RUN_DIR / "lstm-smoke.stdout.log"
    stderr_path = LSTM_GNN_RUN_DIR / "lstm-smoke.stderr.log"
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=str(root), stdout=stdout, stderr=stderr)
    status = {
        "state": "running",
        "pid": process.pid,
        "command": command,
        "cwd": str(root),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "message": "LSTM smoke run started. Watch status endpoint for metrics/logs.",
    }
    LSTM_STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


@router.get("/compare/{project_id}")
async def compare_project(project_id: int, language: str = Query("ru"), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    started = time.perf_counter()
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Проект не найден")
    constraints = project.constraints_json or {}
    group_code = str(constraints.get("group_code") or "")
    direction_code = str(constraints.get("direction_code") or "")
    secondary_group_code = str(constraints.get("secondary_group_code") or "")
    secondary_direction_code = str(constraints.get("secondary_direction_code") or "")
    scopes = [
        {"label": "primary", "group_code": group_code, "direction_code": direction_code},
    ]
    if secondary_group_code or secondary_direction_code:
        scopes.append({"label": "secondary", "group_code": secondary_group_code, "direction_code": secondary_direction_code})

    latest = max(project.versions, key=lambda version: version.version_number, default=None)
    plan = None
    if latest:
        plan = db.query(Plan).filter(Plan.project_version_id == latest.id).order_by(Plan.is_active.desc(), Plan.id.desc()).first()
    cache_key = (project_id, language, plan.id if plan else None)
    cached = _COMPARE_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _COMPARE_CACHE_TTL_SECONDS:
        return cached[1]

    rows_by_id = {}
    scope_summary = []
    for scope_item in scopes:
        scope_rows, scope_name, code = _scope_disciplines(db, scope_item, limit=_COMPARE_SCOPE_LIMIT)
        for row in scope_rows:
            rows_by_id.setdefault(row.id, row)
        scope_summary.append({
            **scope_item,
            "scope": scope_name,
            "reference_disciplines": len(scope_rows),
            "code": code,
        })
    rows = list(rows_by_id.values())
    scope = "multi-scope" if len(scopes) > 1 else scope_summary[0]["scope"]
    project_los = db.query(LearningOutcome).filter(LearningOutcome.project_version_id == latest.id).all() if latest else []

    project_tokens = _tokens(" ".join([
        project.title or "", project.goal or "", project.domain1 or "", project.domain2 or "",
        " ".join(lo.lo_text or "" for lo in project_los),
    ]))

    def row_text(row):
        content = row.content_json or {}
        return " ".join(str(part or "") for part in [
            row.canonical_title, row.title_ru, row.title_kk, row.title_en,
            content.get("description_ru"), content.get("description_kk"), content.get("description_en"),
        ])

    rows.sort(key=lambda row: (_overlap(project_tokens, _tokens(row_text(row))), len(row.source_programs or [])), reverse=True)
    current_titles = set()
    current_epvo_ids = set()
    expert_supported_matches = 0
    total_plan_matches = 0
    if plan:
        course_ids = [item.course_id for item in db.query(PlanItem).filter(PlanItem.plan_id == plan.id, PlanItem.course_id.isnot(None)).all()]
        current_courses = db.query(Course).filter(Course.id.in_(course_ids or [-1])).all()
        current_titles = {_norm(course.title) for course in current_courses}
        for course in current_courses:
            if (course.course_id or "").startswith("EPVO-"):
                try:
                    current_epvo_ids.add(int(course.course_id.split("-", 1)[1]))
                except ValueError:
                    pass
        match_rows = db.query(MatchScore).filter(MatchScore.project_version_id == latest.id, MatchScore.course_id.in_(course_ids or [-1])).all() if latest else []
        total_plan_matches = len(match_rows)
        expert_supported_matches = sum(1 for row in match_rows if (row.evidence_json or {}).get("epvo_expert_score", 0) > 0)
    typical = []
    top_rows = rows[:_COMPARE_TYPICAL_LIMIT]
    existing_epvo_course_codes = {
        code
        for (code,) in db.query(Course.course_id)
        .filter(Course.course_id.like("EPVO-%"))
        .all()
    }
    expert_counts = {
        discipline_id: count
        for discipline_id, count in db.query(EpvoDisciplineLoLink.discipline_id, func.count(EpvoDisciplineLoLink.id))
        .filter(EpvoDisciplineLoLink.discipline_id.in_([row.id for row in top_rows] or [-1]))
        .group_by(EpvoDisciplineLoLink.discipline_id)
        .all()
    }
    for row in top_rows:
        title = localized(row, language)
        translations = epvo_translation_payload(row)
        present = row.id in current_epvo_ids or _norm(row.canonical_title) in current_titles or _norm(title) in current_titles
        expert_link_count = int(expert_counts.get(row.id, 0))
        repository_status = "in_plan" if present else "in_repository" if f"EPVO-{row.id}" in existing_epvo_course_codes else "missing"
        typical.append({
            "id": row.id,
            "title": title,
            **translations,
            "credits": row.typical_credits,
            "semester": row.typical_semester,
            "source_program_count": len(row.source_programs or []),
            "expert_link_count": expert_link_count,
            "present": present,
            "status": row.status,
            "repository_status": repository_status,
            "relevance": round(_overlap(project_tokens, _tokens(row_text(row))), 3),
        })
    source_program_ids, seen_program_ids = [], set()
    for row in rows[:80]:
        for source_id in row.source_programs or []:
            if source_id not in seen_program_ids:
                seen_program_ids.add(source_id)
                source_program_ids.append(str(source_id))
        if len(source_program_ids) >= _COMPARE_PROGRAM_LIMIT * 2:
            break
    raw_programs = db.query(RawEpvoProgram).filter(RawEpvoProgram.source_id.in_(source_program_ids[:_COMPARE_PROGRAM_LIMIT])).limit(_COMPARE_PROGRAM_LIMIT).all() if source_program_ids else []
    similar_programs, lo_counter = [], {}
    suffix = "Kz" if language in {"kk", "kz"} else "En" if language == "en" else "Ru"
    for raw in raw_programs:
        payload = raw.payload_json or {}
        title = _payload_title(payload, language)
        goal = _payload_goal(payload, language)
        disciplines = payload.get("disciplinesInfo") or []
        similar_programs.append({"source_id": raw.source_id, "title": title, "goal": goal, "credits": payload.get("creditsCount"), "discipline_count": len(disciplines), "lo_count": 0, "similarity": round(_overlap(project_tokens, _tokens(" ".join([title, goal]))), 3)})
    raw_los = db.query(RawEpvoLearningOutcome).filter(RawEpvoLearningOutcome.program_source_id.in_(source_program_ids[:_COMPARE_PROGRAM_LIMIT * 2])).limit(_COMPARE_LO_LIMIT).all() if source_program_ids else []
    lo_counts_by_program = {}
    for raw_lo in raw_los:
        lo_counts_by_program[raw_lo.program_source_id] = lo_counts_by_program.get(raw_lo.program_source_id, 0) + 1
        lo = raw_lo.payload_json or {}
        text = lo.get(f"learningOutcomeName{suffix}") or lo.get("learningOutcomeNameRu") or lo.get("learningOutcomeNameEn")
        if not text:
            text = lo.get(f"name{suffix}") or lo.get("nameRu") or lo.get("nameEn")
        key = _norm(text)
        if key:
            item = lo_counter.setdefault(key, {"text": text, "count": 0})
            item["count"] += 1
    for program in similar_programs:
        program["lo_count"] = lo_counts_by_program.get(str(program["source_id"]), 0)
    similar_programs.sort(key=lambda item: (item["similarity"], item["discipline_count"]), reverse=True)
    typical_los = sorted(lo_counter.values(), key=lambda item: item["count"], reverse=True)[:12]
    present_count = sum(item["present"] for item in typical)
    missing_count = sum(not item["present"] for item in typical)
    match_percentage = round(present_count / max(1, len(typical)) * 100, 1)
    epvo_plan_course_count = 0
    total_plan_course_count = 0
    if plan:
        plan_course_ids = [item.course_id for item in plan.items if item.course_id is not None]
        total_plan_course_count = len(plan_course_ids)
        if plan_course_ids:
            epvo_plan_course_count = db.query(Course).filter(
                Course.id.in_(plan_course_ids),
                Course.course_id.like("EPVO-%"),
            ).count()
    epvo_plan_course_percentage = round(epvo_plan_course_count / max(1, total_plan_course_count) * 100, 1)
    expert_supported_percentage = round(expert_supported_matches / max(1, total_plan_matches) * 100, 1)
    epvo_quality_score = round(match_percentage * 0.7 + expert_supported_percentage * 0.3, 1)
    if epvo_quality_score >= 75:
        epvo_quality_status = "passed"
        epvo_quality_label = "Соответствует ориентиру ЕПВО 75%+"
    elif epvo_quality_score >= 70:
        epvo_quality_status = "borderline"
        epvo_quality_label = "Близко к ориентиру ЕПВО; нужна экспертная проверка"
    else:
        epvo_quality_status = "needs_improvement"
        epvo_quality_label = "Ниже ориентира ЕПВО 70–75%"
    weak_spots = []
    if missing_count:
        weak_spots.append(f"В плане отсутствуют {missing_count} из {len(typical)} наиболее релевантных типовых дисциплин ЕПВО.")
    if not group_code:
        weak_spots.append("У проекта не выбрана группа ОП; сравнение менее точное.")
    if not plan:
        weak_spots.append("Активный учебный план ещё не сформирован.")
    recommendations = []
    missing_priority = sorted(
        [item for item in typical if not item["present"]],
        key=lambda item: (item.get("expert_link_count", 0), item.get("source_program_count", 0), item.get("relevance", 0)),
        reverse=True,
    )[:10]
    top_missing = [item["title"] for item in missing_priority[:5]]
    if top_missing:
        recommendations.append("Проверить добавление типовых дисциплин: " + ", ".join(top_missing))
    expert_missing = [item["title"] for item in missing_priority if item.get("expert_link_count", 0) > 0][:5]
    if expert_missing:
        recommendations.append("Особенно проверить дисциплины с экспертными связями ЕПВО: " + ", ".join(expert_missing))
    if typical_los:
        recommendations.append("Сверить LO программы с наиболее частыми результатами обучения ЕПВО.")
    result = {
        "project_id": project_id, "scope": scope, "direction_code": direction_code, "group_code": group_code,
        "secondary_direction_code": secondary_direction_code, "secondary_group_code": secondary_group_code,
        "scope_summary": scope_summary,
        "reference_disciplines": len(rows), "typical_disciplines": typical,
        "present_count": present_count,
        "missing_count": missing_count,
        "match_percentage": match_percentage,
        "expert_supported_matches": expert_supported_matches,
        "total_plan_matches": total_plan_matches,
        "epvo_plan_course_count": epvo_plan_course_count,
        "total_plan_course_count": total_plan_course_count,
        "epvo_plan_course_percentage": epvo_plan_course_percentage,
        "expert_supported_percentage": expert_supported_percentage,
        "epvo_quality_score": epvo_quality_score,
        "epvo_quality_status": epvo_quality_status,
        "epvo_quality_label": epvo_quality_label,
        "missing_priority": missing_priority,
        "similar_programs": similar_programs[:8],
        "typical_los": typical_los,
        "weak_spots": weak_spots,
        "recommendations": recommendations,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "limits": {
            "scope_disciplines": _COMPARE_SCOPE_LIMIT,
            "typical_disciplines": _COMPARE_TYPICAL_LIMIT,
            "similar_programs": _COMPARE_PROGRAM_LIMIT,
            "typical_los": _COMPARE_LO_LIMIT,
        },
    }
    _COMPARE_CACHE[cache_key] = (time.time(), result)
    return result


@router.post("/projects/{project_id}/apply-priority")
async def apply_epvo_priority_disciplines(
    project_id: int,
    limit: int = Query(10, ge=1, le=30),
    payload: dict | None = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve top missing EPVO disciplines as generation candidates.

    This does not rewrite existing plans. The user rebuilds A/B/C afterwards.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return {"created": 0, "existing": 0, "message": "Проект не найден"}
    version = db.query(ProjectVersion).filter(
        ProjectVersion.project_id == project_id
    ).order_by(ProjectVersion.version_number.desc()).first()
    if not version:
        return {"created": 0, "existing": 0, "message": "Версия проекта не найдена"}
    selected_ids = []
    if isinstance(payload, dict):
        selected_ids = [int(value) for value in (payload.get("discipline_ids") or []) if str(value).isdigit()]
    if selected_ids:
        # The UI already obtained these IDs from the read-only comparison.
        # Avoid recalculating the full comparison (previously ~30 s and a
        # frequent timeout/500 source) merely to approve explicit choices.
        missing = [{"id": value} for value in selected_ids[:limit]]
    else:
        comparison = await compare_project(project_id, "ru", db, current_user)
        missing = list(comparison.get("missing_priority") or [])[:limit]
    created = 0
    existing = 0
    course_ids = []
    applied = []
    for item in missing:
        row = db.query(EpvoDisciplineNormalized).filter(EpvoDisciplineNormalized.id == item.get("id")).first()
        if not row:
            continue
        if not epvo_row_matches_education_level(
            row, (project.constraints_json or {}).get("education_level")
        ):
            applied.append({
                "id": row.id,
                "title": row.title_ru or row.title_en or row.canonical_title,
                "status": "skipped_wrong_education_level",
                "score": 0.0,
            })
            continue
        if not epvo_row_is_relevant(row, version):
            applied.append({
                "id": row.id,
                "title": row.title_ru or row.title_en or row.canonical_title,
                "status": "skipped_low_relevance",
                "score": epvo_row_relevance_score(row, version),
            })
            continue
        course_code = f"EPVO-{row.id}"
        course = db.query(Course).filter(Course.course_id == course_code).first()
        if course:
            existing += 1
            status = "existing"
        else:
            course = _course_from_epvo(row, project, db)
            db.add(course)
            db.flush()
            created += 1
            status = "created"
        row.status = "approved"
        row.approved_course_id = course.id
        upsert_epvo_course_localizations(db, course, row)
        course_ids.append(course.id)
        applied.append({
            "id": row.id,
            "title": row.title_ru or row.title_en or row.canonical_title,
            **epvo_translation_payload(row),
            "status": status,
            "course_id": course.id,
        })
    db.commit()
    for key in list(_COMPARE_CACHE):
        if key[0] == project_id:
            _COMPARE_CACHE.pop(key, None)
    return {
        "created": created,
        "existing": existing,
        "course_ids": course_ids,
        "applied": applied,
        "requires_rebuild": True,
        "message": f"Добавлено кандидатов ЕПВО: {created}; уже были в репозитории: {existing}. Перестройте варианты A/B/C.",
    }
