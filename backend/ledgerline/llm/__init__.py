"""LLM provider clients."""
from __future__ import annotations

from ..config import get_settings
from .base import LLMClient, LLMResponse

__all__ = ["LLMClient", "LLMResponse", "get_client", "get_escalation_client"]


def _build(provider: str, model: str) -> LLMClient:
    settings = get_settings()
    if provider == "anthropic":
        from .anthropic_client import AnthropicClient

        return AnthropicClient(settings.anthropic_api_key, model)
    if provider == "openai_compat":
        from .openai_compat import OpenAICompatClient

        return OpenAICompatClient(settings.openai_base_url, settings.openai_api_key, model)
    if provider == "fake":
        from .fake import FakeClient

        return FakeClient()
    raise ValueError(f"Unknown LLM provider {provider!r}")


def get_client() -> LLMClient:
    """The primary extraction model (LLM_PROVIDER, LLM_MODEL)."""
    settings = get_settings()
    return _build(settings.llm_provider, settings.llm_model)


def get_escalation_client() -> LLMClient | None:
    """The model used when the primary fails or its extraction fails validation (LLM_ESCALATION_MODEL, optionally on
    another provider via LLM_ESCALATION_PROVIDER, e.g. to keep working through a provider outage). None when
    escalation is not configured."""
    settings = get_settings()
    if not settings.llm_escalation_model:
        return None
    return _build(settings.llm_escalation_provider or settings.llm_provider, settings.llm_escalation_model)
