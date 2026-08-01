"""Repair the three exploratory programme records created with a bad console encoding."""

from app.database import SessionLocal
from app.models.project import Project


PROGRAMMES = {
    135: (
        "Цифровой агроном и аналитик умного сельского хозяйства",
        "Подготовка специалистов, создающих цифровые решения для точного земледелия и управления агропроизводством.",
    ),
    136: (
        "Инженер цифровых двойников и промышленных роботов",
        "Подготовка инженеров, разрабатывающих цифровые двойники и роботизированные производственные системы.",
    ),
    137: (
        "Инженер киберзащиты критической инфраструктуры",
        "Подготовка специалистов по защите цифровых и промышленных систем критической инфраструктуры.",
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
        for project_id, (title, goal) in PROGRAMMES.items():
            project = db.get(Project, project_id)
            if not project:
                continue
            project.title = title
            project.goal = goal
            version = sorted(project.versions, key=lambda item: item.version_number)[-1]
            for lo, text in zip(sorted(version.learning_outcomes, key=lambda item: item.order_index), LOS):
                lo.lo_text = text
        db.commit()
        print("repaired", ",".join(map(str, PROGRAMMES)))
    finally:
        db.close()


if __name__ == "__main__":
    main()
