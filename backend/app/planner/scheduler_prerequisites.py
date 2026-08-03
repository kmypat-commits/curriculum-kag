"""Text ontology used by plan-local prerequisite inference."""
from __future__ import annotations

from app.planner.scheduler_utils import title_key as _title_key


def prerequisite_concepts(title: str | None) -> set[str]:
    """Return small, explainable concept tags for a course title."""
    key = _title_key(title)
    concepts: set[str] = set()
    markers = {
        "programming": ("программир", "software development", "разработка прилож"),
        "algorithms": ("алгоритм", "структур данных", "data structures"),
        "database": ("баз данных", "database", "sql"),
        "operating_systems": ("операционн систем", "системное программ", "operating system"),
        "networks": ("компьютерн сет", "вычислительных систем и сет", "network"),
        "security": ("безопас", "кибер", "security"),
        "data_analysis": ("анализ данн", "больших данных", "big data", "аналитик"),
        "artificial_intelligence": (
            "искусственн интеллект", "машинн обуч", "нейросет",
            "интеллектуальн систем", "machine learning", "artificial intelligence",
        ),
        "information_systems": ("информационн систем", "information system", "информационных ресурсов"),
        "research": ("научн исслед", "методолог", "research method", "academic writing", "экспериментальн"),
        "project_management": ("управление проект", "проектный менедж", "project management"),
        "project_application": ("проектно исслед", "проект 1", "project 1", "курсов"),
        "web": ("web", "интернет технолог"),
        "robotics": ("робот", "robot"),
        "validation": ("тестирован", "валидац", "validation", "verification"),
        "distributed_systems": ("распредел", "distributed", "cloud", "облач"),
    }
    for concept, terms in markers.items():
        if any(term in key for term in terms):
            concepts.add(concept)
    conjunctions = {
        "artificial_intelligence": (("машин", "обуч"), ("искусствен", "интеллект"), ("интеллектуальн", "систем")),
        "networks": (("компьютер", "сет"), ("вычисл", "сет")),
        "database": (("баз", "данн"),),
        "operating_systems": (("операцион", "систем"), ("системн", "программ")),
        "data_analysis": (("анализ", "данн"), ("больш", "данн")),
        "information_systems": (("информацион", "систем"), ("информацион", "ресурс")),
        "research": (("научн", "исслед"), ("академическ", "письм")),
        "project_management": (("управлен", "проект"), ("проектн", "менедж")),
        "project_application": (("проект", "исслед"),),
    }
    for concept, alternatives in conjunctions.items():
        if any(all(stem in key for stem in stems) for stems in alternatives):
            concepts.add(concept)
    return concepts
