"""Pure semester-placement rules used by the scheduler."""
from __future__ import annotations

import math
import re
from typing import Dict

from app.planner.scheduler_text import has_domain_term as _has_domain_term
from app.planner.scheduler_utils import title_key as _title_key


def late_stage_min_semester(title: str | None, num_semesters: int) -> int:
    key = _title_key(title)
    if not key:
        return 1
    if any(marker in key for marker in ("преддиплом", "диплом", "итоговая аттестация", "final attestation", "thesis", "graduation", "capstone defense")):
        return max(1, num_semesters - 1)
    if any(marker in key for marker in ("практика", "practice", "internship")):
        return max(1, num_semesters - 2)
    return 1


def complexity_min_semester(item: Dict, num_semesters: int) -> int:
    if item.get("regulatory_required") and str(item.get("type") or "").startswith("goso_"):
        return 1
    text = _title_key(" ".join([item.get("title") or "", item.get("type") or ""]))
    clinical = ("хирург", "surgery", "кардио", "гастро", "онколог", "уролог", "невролог", "паразитолог", "психиатр", "офтальм", "реаним", "терапи", "педиатр", "акуш", "гинек", "дермат", "клиническ", "внутренние болезни", "internal medicine")
    systems = ("диагност", "надежност", "надёжност", "систем автоматизац", "diagnostic", "reliability of automation")
    research = ("методология науч", "scientific methodology", "доказательная медицина", "evidence based medicine", "научных исследований", "research methods")
    advanced = ("kafka", "mqtt", "spark", "hadoop", "stream", "потоков", "микросервис", "microservice", "devops", "kubernetes", "docker", "облач", "cloud", "distributed", "распредел", "big data", "machine learning", "deep learning", "нейросет", "malware", "реверс", "reverse", "форензик", "forensic", "siem", "soc")
    if _has_domain_term(text, clinical) or _has_domain_term(text, systems):
        return max(2, min(num_semesters, math.ceil(num_semesters * 0.55)))
    if _has_domain_term(text, research):
        return 1 if num_semesters <= 6 else max(2, min(num_semesters, math.ceil(num_semesters * 0.35)))
    if "первичной медицинской помощи" in text or "primary medical care" in text:
        return max(2, min(num_semesters, math.ceil(num_semesters * 0.45)))
    if "продвинут" in text or "advanced" in text or re.search(r"\b[23]\b", text):
        return max(2, min(num_semesters, math.ceil(num_semesters * 0.45)))
    if _has_domain_term(text, advanced):
        return max(2, min(num_semesters, math.ceil(num_semesters * 0.35)))
    return 1


def cycle_min_semester(item: Dict, num_semesters: int) -> int:
    cycle = _title_key(item.get("type"))
    if cycle in {"ood", "ооd", "ооd компонент", "general education"}:
        return 1
    if cycle in {"бд", "bd", "basic disciplines", "базовые дисциплины"}:
        return max(1, min(num_semesters, math.ceil(num_semesters * 0.15)))
    if cycle in {"пд", "pd", "professional disciplines", "профильные дисциплины"}:
        return max(1, min(num_semesters, math.ceil(num_semesters * 0.25)))
    return 1


def foundation_max_semester(title: str | None, num_semesters: int) -> int:
    key = _title_key(title)
    if any(marker in key for marker in ("клиническ", "диагност", "врачебн", "хирург", "терапи", "педиатр", "акуш", "гинек", "онколог", "кардио", "clinical", "diagnostic", "surgery")):
        return num_semesters
    if any(marker in key for marker in ("информационной безопасности", "кибербезопасности", "цифровой криминалистики", "digital forensics", "cybersecurity")):
        return max(2, min(num_semesters, math.ceil(num_semesters * 0.65)))
    if any(marker in key for marker in ("доказательной медицины", "evidence based medicine")):
        return max(2, min(num_semesters, math.ceil(num_semesters * 0.9)))
    if any(marker in key for marker in ("научных исследований", "research methods", "academic writing")):
        return max(2, min(num_semesters, math.ceil(num_semesters * 0.5)))
    if key.startswith(("основы ", "введение ")) or any(marker in key for marker in ("теоретические основы", "fundamentals", "introduction", "инструментарий технологии программирования")):
        return max(1, min(num_semesters, math.ceil(num_semesters * 0.35)))
    return num_semesters


def minimum_appropriate_semester(item: Dict, num_semesters: int) -> int:
    recommended = int(item.get("recommended_semester") or 0)
    semantic_upper = foundation_max_semester(item.get("title"), num_semesters)
    if item.get("prerequisites") and recommended:
        semantic_upper = max(semantic_upper, min(num_semesters, recommended + 2))
    # ``typical_semester`` in EPVO is an observed placement across source
    # programmes, not a regulatory prerequisite. It guides the scheduler's
    # preference but must not make a well-prepared course inadmissible merely
    # because another university taught it later. A caller may opt into a
    # genuinely fixed source window (for a regulatory or explicitly locked
    # item); semantic depth and real prerequisite edges remain hard rules.
    recommended_lower = (
        max(1, recommended - 1)
        if recommended and item.get("source_semester_required")
        else 1
    )
    key = _title_key(item.get("title"))
    if key.startswith(("основы ", "введение ", "fundamentals", "introduction")) and not any(marker in key for marker in ("хирург", "surgery", "кардио", "гастро", "онколог", "уролог", "невролог", "терапи", "педиатр", "клиническ")):
        recommended_lower = 1
    # Plan-local semantic inference proves that a selected earlier course can
    # supply the prerequisite concept.  It must not turn an advisory EPVO
    # source semester into a hard lower bound after the timetable has already
    # been built.  Explicit catalogue prerequisites keep the stricter rule.
    if item.get("prerequisite_inference"):
        recommended_lower = 1
    if recommended_lower > semantic_upper:
        recommended_lower = 1
    return max(1, late_stage_min_semester(item.get("title"), num_semesters), cycle_min_semester(item, num_semesters), complexity_min_semester(item, num_semesters), recommended_lower)
