"""Optional PydanticAI bridge for typed curriculum-assistant responses.

The import is lazy by design.  A normal installation continues to use the
existing OpenAI/deterministic paths; enabling this adapter requires installing
``pydantic-ai`` and setting ``PYDANTIC_AI_ENABLED=true``.  All outputs are
validated by the shared contracts before they leave this module.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Type

from app.config import settings
from app.services.ai_contracts import (
    AchievabilityReport,
    LocalizedSuggestions,
    validate_achievability,
    validate_suggestions,
)


def _run(prompt: str, output_type: Type[Any], system_prompt: str) -> Any | None:
    if not settings.PYDANTIC_AI_ENABLED:
        return None
    try:
        from pydantic_ai import Agent
    except ImportError:
        return None
    if settings.LLM_API_KEY and not settings.LLM_API_KEY.startswith("sk-placeholder"):
        os.environ.setdefault("OPENAI_API_KEY", settings.LLM_API_KEY)
    model_name = settings.PYDANTIC_AI_MODEL_NAME or f"openai:{settings.LLM_MODEL_NAME}"
    try:
        try:
            agent = Agent(model_name, output_type=output_type, system_prompt=system_prompt)
        except TypeError:  # compatibility with an older PydanticAI release
            agent = Agent(model_name, result_type=output_type, system_prompt=system_prompt)
        try:
            result = agent.run_sync(prompt, retries=max(0, int(settings.PYDANTIC_AI_RETRIES)))
        except TypeError:  # compatibility with older PydanticAI releases
            result = agent.run_sync(prompt)
        return getattr(result, "output", getattr(result, "data", None))
    except Exception:
        # Optional orchestration must never turn a working endpoint into 500.
        return None


def run_suggestions(prompt: str, required_terms: Iterable[str] = ()) -> dict | None:
    output = _run(
        prompt,
        LocalizedSuggestions,
        "Return exactly three goals and three to six measurable learning outcomes.",
    )
    if output is None:
        return None
    data = output.model_dump() if hasattr(output, "model_dump") else dict(output)
    try:
        return validate_suggestions(data, required_terms=required_terms).model_dump()
    except Exception:
        return None


def run_achievability(prompt: str) -> dict | None:
    output = _run(
        prompt,
        AchievabilityReport,
        "Assess curriculum learning-outcome achievability. Return only the typed report.",
    )
    if output is None:
        return None
    data = output.model_dump() if hasattr(output, "model_dump") else dict(output)
    try:
        return validate_achievability(data).model_dump()
    except Exception:
        return None
