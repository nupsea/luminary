"""LiteLLM-backed LLM service — unified gateway for Ollama, OpenAI, Anthropic, Gemini."""

import logging
from collections.abc import AsyncGenerator

import litellm

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Silence litellm's verbose success logging
litellm.suppress_debug_info = True


class LLMService:
    """Single call-site for all LLM completions.

    Usage::
        service = get_llm_service()
        text = await service.generate("Summarise this", system="Be brief")
        # streaming:
        gen = await service.generate("Explain X", stream=True)
        async for token in gen:
            print(token, end="", flush=True)
    """

    def _build_kwargs(
        self, model: str, messages: list[dict], settings: Settings
    ) -> dict:
        kwargs: dict = {"model": model, "messages": messages}
        if model.startswith("ollama/"):
            kwargs["api_base"] = settings.OLLAMA_URL
        elif model.startswith("openai/"):
            kwargs["api_key"] = settings.OPENAI_API_KEY
        elif model.startswith("anthropic/"):
            kwargs["api_key"] = settings.ANTHROPIC_API_KEY
        elif model.startswith("gemini/"):
            kwargs["api_key"] = settings.GOOGLE_API_KEY
        return kwargs

    async def generate(
        self,
        prompt: str,
        system: str = "",
        model: str | None = None,
        stream: bool = False,
    ) -> str | AsyncGenerator[str]:
        settings = get_settings()
        effective_model = model or settings.LITELLM_DEFAULT_MODEL

        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs = self._build_kwargs(effective_model, messages, settings)

        if not stream:
            response = await litellm.acompletion(**kwargs)
            return response.choices[0].message.content or ""

        return self._token_stream(kwargs)

    async def _token_stream(self, kwargs: dict) -> AsyncGenerator[str]:
        response = await litellm.acompletion(stream=True, **kwargs)
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
