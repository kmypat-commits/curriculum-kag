"""Repair the three exploratory programme records created with a bad console encoding."""

from app.database import SessionLocal
from app.models.project import Project
from app.models.bridge_module import BridgeModule


PROGRAMMES = {
    135: (
        "Цифровой агроном и аналитик умного сельского хозяйства",
        "Подготовка специалистов, создающих цифровые решения для точного земледелия и управления агропроизводством.",
        "Информационно-коммуникационные технологии",
        "Сельское хозяйство и биоресурсы",
    ),
    136: (
        "Инженер цифровых двойников и промышленных роботов",
        "Подготовка инженеров, разрабатывающих цифровые двойники и роботизированные производственные системы.",
        "Информационно-коммуникационные технологии",
        "Инженерные, обрабатывающие и строительные отрасли",
    ),
    137: (
        "Инженер киберзащиты критической инфраструктуры",
        "Подготовка специалистов по защите цифровых и промышленных систем критической инфраструктуры.",
        "Информационная безопасность",
        "Инженерные, обрабатывающие и строительные отрасли",
    ),
}

LOS = [
    "Проектировать цифровые профессиональные системы.",
    "Применять анализ данных и искусственный интеллект.",
    "Интегрировать данные, платформы и отраслевые процессы.",
    "Оценивать качество, безопасность и этические риски решений.",
    "Работать в междисциплинарной команде.",
    "Проводить прикладные исследования и обосновывать решения.",
]


def main() -> None:
    db = SessionLocal()
    try:
        for project_id, (title, goal, domain1, domain2) in PROGRAMMES.items():
            project = db.get(Project, project_id)
            if not project:
                continue
            project.title = title
            project.goal = goal
            project.domain1 = domain1
            project.domain2 = domain2
            version = sorted(project.versions, key=lambda item: item.version_number)[-1]
            for lo, text in zip(sorted(version.learning_outcomes, key=lambda item: item.order_index), LOS):
                lo.lo_text = text
            for bridge in db.query(BridgeModule).filter(BridgeModule.project_version_id == version.id).all():
                targets = ", ".join(bridge.target_los or []) or "результатов обучения"
                bridge.title = f"Интеграционный модуль {targets}: {domain1} и {domain2}"
                bridge.goal = f"Закрыть разрыв по {targets} через практическую связь направлений {domain1} и {domain2}."
                bridge.description = f"Bridge-модуль связывает {domain1} и {domain2} с результатами {targets}."
        db.commit()
        print("repaired", ",".join(map(str, PROGRAMMES)))
    finally:
        db.close()


if __name__ == "__main__":
    main()
