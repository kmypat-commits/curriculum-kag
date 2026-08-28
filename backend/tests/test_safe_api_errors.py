from pathlib import Path


API_DIR = Path(__file__).resolve().parents[1] / "app" / "api"


def test_kag_api_does_not_expose_exception_details():
    source = (API_DIR / "kag.py").read_text(encoding="utf-8")

    assert "detail=str(e)" not in source
    assert "detail=f\"{str(e)}\"" not in source
    assert "logger.exception" in source


def test_planner_build_api_does_not_interpolate_exception_details():
    source = (API_DIR / "planner_build.py").read_text(encoding="utf-8")

    assert "detail=f\"Не удалось сформировать учебный план: {str(e)}\"" not in source
    assert "detail=f\"Не удалось пересчитать связи дисциплина–LO: {str(e)}\"" not in source
