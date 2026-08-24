"""Expected failures from optional LLM providers.

Provider SDKs are optional in the minimal backend profile.  Keep the
exception tuple import-safe while preventing API routes from swallowing
unrelated programming errors.
"""

from __future__ import annotations


_EXPECTED = [OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError]

try:  # OpenAI is optional in the offline profile.
    from openai import OpenAIError
except ImportError:  # pragma: no cover - exercised in minimal installs
    OpenAIError = None  # type: ignore[assignment]
else:
    _EXPECTED.append(OpenAIError)

try:  # Anthropic is optional in the offline profile.
    from anthropic import APIError as AnthropicAPIError
except ImportError:  # pragma: no cover - exercised in minimal installs
    AnthropicAPIError = None  # type: ignore[assignment]
else:
    _EXPECTED.append(AnthropicAPIError)


LLM_ERRORS = tuple(dict.fromkeys(_EXPECTED))
