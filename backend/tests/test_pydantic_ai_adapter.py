from app.services.ai_contracts import validate_achievability, validate_suggestions
from app.services.pydantic_ai_adapter import run_achievability


def test_pydantic_contracts_accept_valid_structured_output():
    suggestions = validate_suggestions(
        {
            "goals": ["AI governance", "Data quality", "Responsible deployment"],
            "learning_outcomes": ["Audit data quality", "Explain model risks", "Document decisions"],
        },
        required_terms=["AI"],
    )
    report = validate_achievability(
        {
            "verdict": "Ready",
            "score": 88,
            "summary": "The outcomes are measurable.",
            "recommendations": [],
        }
    )
    assert len(suggestions.goals) == 3
    assert report.score == 88


def test_pydantic_adapter_is_safe_when_disabled():
    assert run_achievability("smoke") is None
