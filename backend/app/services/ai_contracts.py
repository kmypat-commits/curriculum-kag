"""Typed contracts shared by LLM endpoints and the future PydanticAI adapter.

The application remains usable without the optional ``pydantic_ai`` package:
Pydantic validation is always available and rejects malformed provider output
before it reaches the UI or database.  The same models can later be passed as
PydanticAI ``output_type`` without changing endpoint contracts.
"""
from __future__ import annotations

from typing import Literal, Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator


Language = Literal["ru", "kk", "en"]
AchievabilityStatus = Literal["on_track", "needs_courses", "too_vague", "critical"]
AchievabilityVerdict = Literal["Ready", "Needs Improvement", "Critical Gaps"]


class LocalizedSuggestions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    goals: list[str] = Field(min_length=3, max_length=3)
    learning_outcomes: list[str] = Field(min_length=3, max_length=6)

    @field_validator("goals", "learning_outcomes")
    @classmethod
    def non_empty_text(cls, values: list[str]) -> list[str]:
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        if len(cleaned) != len(values):
            raise ValueError("AI content contains an empty item")
        return cleaned


class AchievabilityRecommendation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lo_code: str = Field(min_length=1, max_length=64)
    status: AchievabilityStatus
    issue: str = ""
    suggestion: str = ""
    coverage: float | None = Field(default=None, ge=0, le=1)


class AchievabilityReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    verdict: AchievabilityVerdict
    score: int = Field(ge=0, le=100)
    summary: str = ""
    recommendations: list[AchievabilityRecommendation] = Field(default_factory=list)


def validate_suggestions(data: dict, required_terms: Iterable[str] = ()) -> LocalizedSuggestions:
    """Validate and normalize a provider response before returning it."""
    result = LocalizedSuggestions.model_validate(data)
    text = " ".join(result.goals + result.learning_outcomes).casefold()
    for term in required_terms:
        tokens = [token.casefold() for token in str(term or "").split() if len(token) >= 4]
        if tokens and not any(token in text for token in tokens):
            raise ValueError(f"AI suggestions do not mention selected domain: {term}")
    return result


def validate_achievability(data: dict) -> AchievabilityReport:
    """Validate an LLM/deterministic achievability response."""
    return AchievabilityReport.model_validate(data)
