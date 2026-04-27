"""
llm/provider_factory.py — Factory de proveedores LLM
=====================================================
Construye el proveedor correcto según config.yaml.
El resto del sistema nunca importa un proveedor concreto directamente.

Uso:
    from backend.llm.provider_factory import get_llm_provider
    llm = get_llm_provider()
    response = await llm.complete(system, user, context)
"""

from backend.core.interfaces import LLMProvider
from backend.core.config import get_settings

_provider: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    """Retorna el proveedor LLM configurado (singleton)."""
    global _provider
    if _provider is not None:
        return _provider

    cfg = get_settings()
    provider_name = cfg.llm.provider.lower()

    if provider_name == "claude":
        from backend.llm.claude_provider import ClaudeProvider
        _provider = ClaudeProvider()

    elif provider_name == "openai":
        from backend.llm.openai_provider import OpenAIProvider
        _provider = OpenAIProvider()

    elif provider_name == "gemini":
        from backend.llm.gemini_provider import GeminiProvider
        _provider = GeminiProvider()

    elif provider_name == "ollama":
        from backend.llm.ollama_provider import OllamaProvider
        _provider = OllamaProvider()

    else:
        raise ValueError(
            f"Proveedor LLM desconocido: '{provider_name}'. "
            f"Opciones: claude, openai, gemini, ollama"
        )

    print(f"[LLM] Proveedor activo: {_provider.provider_name} / {_provider.model_name}")
    return _provider


def reset_provider() -> None:
    """Fuerza recreación del proveedor (útil al cambiar config en runtime)."""
    global _provider
    _provider = None
