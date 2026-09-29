from types import SimpleNamespace

from app.services.plan_pdf_export import build_plan_pdf


def test_pdf_carries_confirmed_profile_coverage_and_unconfirmed_gap(monkeypatch):
    project = SimpleNamespace(
        title="Проектирование изделий из древесины", goal="Подготовка специалистов по деревообработке",
        constraints_json={"total_credits": 240, "total_semesters": 8, "education_level": "bachelor"},
    )
    version = SimpleNamespace(project=project, version_number=1, learning_outcomes=[])
    plan = SimpleNamespace(variant_type="A", metrics_json={
        "verification": {"feasible": True, "hard_violation_count": 0, "total_credits": 244, "target_credits": 240},
        "core_coverage": {
            "enabled": True, "unique_core_credits": 5,
            "required_courses": {"requested": [17], "included": [17], "missing": []},
            "core_coverage": [
                {"block_id": "wood", "title": "Обработка древесины", "requirement": "required", "status": "covered", "supported_credits": 5, "selected_course_ids": [17]},
                {"block_id": "design", "title": "Проектирование мебели", "requirement": "preferred", "status": "unconfirmed", "supported_credits": 0, "unconfirmed_course_ids": [42]},
            ],
        },
    })

    captured = []
    monkeypatch.setattr(
        "app.services.plan_pdf_export.SimpleDocTemplate.build",
        lambda self, story, **kwargs: captured.extend(story),
    )
    build_plan_pdf(
        project_version=version, plan=plan, items=[], courses_by_id={}, bridges_by_id={},
        localizations={}, language="ru",
    )
    text = "\n".join(flowable.getPlainText() for flowable in captured if hasattr(flowable, "getPlainText"))
    assert "Покрытие профильного ядра" in text
    assert "Обработка древесины" in text
    assert "Проектирование мебели" in text
    assert "не подтверждён" in text
    assert "Подтверждённые профильные кредиты: 5" in text
    assert "Не является предметной экспертизой" in text
    assert "Отдельно разберите непокрытые и неподтверждённые профильные блоки" in text
