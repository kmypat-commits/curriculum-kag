"""Deterministic, domain-aware titles used when optional LLM assistance fails."""

from __future__ import annotations

from app.models.bridge_module import BridgeModule
from app.models.project import ProjectVersion
from app.planner.planner_utils import compact_lo_label, title_key


def bridge_candidate_fallbacks(
    version: ProjectVersion,
    bridge: BridgeModule,
    target_los: list[str],
    semester: int,
) -> list[str]:
    domain1 = version.project.domain1 or "область 1"
    domain2 = version.project.domain2 or "область 2"
    professional_los = [code for code in target_los if not str(code or "").startswith("LO-GOSO-")]
    lo_label = compact_lo_label(target_los)
    bridge_key = title_key(bridge.title)
    bridge_text = " ".join(str(value or "") for value in (bridge.title, bridge.description, bridge.goal)).lower()
    if "данн" in bridge_key or "data" in bridge_key:
        focus = "данных и аналитических процессов"
    elif "интеграц" in bridge_key or "integration" in bridge_key:
        focus = "интеграции решений"
    elif "основ" in bridge_key or "foundation" in bridge_key:
        focus = "профессиональных основ"
    elif "практик" in bridge_key or "project" in bridge_key:
        focus = "проектной практики"
    else:
        focus = f"компетенций {lo_label}"
    if professional_los:
        focus = " и ".join(f"компетенции {code}" for code in professional_los[:2])

    if any(marker in bridge_text for marker in ("безопас", "риск", "угроз", "защит")):
        themes = ["Управление цифровыми рисками", "Безопасность и надёжность профессиональных решений", "Практикум анализа угроз и контроля качества"]
    elif any(marker in bridge_text for marker in ("медицин", "клинич", "пациент", "здоров")):
        themes = ["Клинические данные и процессы", "Основы медицинской информатики", "Цифровые технологии в здравоохранении"]
    elif any(marker in bridge_text for marker in ("агро", "сельск", "растен", "почв", "урож")):
        themes = ["Цифровая агрономия", "Аналитика агропромышленных данных", "Интеллектуальные технологии в АПК"]
    elif any(marker in bridge_text for marker in ("киберслед", "кримин", "forensic", "расслед", "цифровых доказ")):
        themes = ["Цифровая криминалистика", "Правовые основы цифровых расследований", "Анализ цифровых доказательств"]
    elif any(marker in bridge_text for marker in ("робот", "мехатрон", "кинемат")):
        themes = ["Основы робототехнических систем", "Моделирование и управление роботами", "Интеллектуальная мехатроника"]
    elif any(marker in bridge_text for marker in ("ии", "ai", "модель", "алгоритм")):
        themes = ["Прикладной искусственный интеллект", "Аудит и качество ИИ-систем", "Управление данными и моделями"]
    else:
        themes = [
            f"Прикладной анализ области {domain2}",
            f"Профессиональный практикум {domain1} и {domain2}",
            f"Проектирование решений для {domain2}",
        ]
    rotations = [themes, [themes[1], themes[2], themes[0]], [themes[2], themes[0], themes[1]]]
    themes = rotations[int(getattr(bridge, "id", 0) or 0) % len(rotations)]
    return [
        f"{themes[0]}: {lo_label} (этап {semester})",
        f"{themes[1]} для программы «{version.project.title}» (семестр {semester})",
        f"{themes[2]} (семестр {semester}; {focus})",
    ]
