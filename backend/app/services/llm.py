"""LiteLLM-backed LLM service — unified gateway for Ollama, OpenAI, Anthropic, Gemini.

All LLM completions in the codebase MUST go through this module so that telemetry
(OpenTelemetry spans) and Langfuse logging are applied uniformly. Direct calls to
litellm.acompletion in services/routers bypass observability.
"""

import logging
from collections.abc import AsyncGenerator
from typing import Any

import litellm

from app.config import Settings, get_settings
from app.telemetry import trace_llm_call

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True
litellm.telemetry = False
logging.getLogger("LiteLLM").setLevel(logging.WARNING)

LLMServiceUnavailableError = litellm.ServiceUnavailableError
LLMAPIConnectionError = litellm.APIConnectionError
LLMNotFoundError = litellm.NotFoundError
LLMRateLimitError = litellm.RateLimitError
LLMAuthenticationError = litellm.AuthenticationError
LLMTimeoutError = litellm.Timeout

LLMUnavailableError: tuple[type[BaseException], ...] = (
    LLMServiceUnavailableError,
    LLMAPIConnectionError,
    LLMNotFoundError,
    LLMRateLimitError,
    LLMAuthenticationError,
    LLMTimeoutError,
    ConnectionRefusedError,
)

# ---------------------------------------------------------------------------
# Langfuse — optional LLM call observability
# ---------------------------------------------------------------------------

_langfuse = None  # type: ignore[var-annotated]


def _init_langfuse():
    """Initialize Langfuse client if keys are configured; else return None."""
    settings = get_settings()
    if settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY:
        try:
            from langfuse import Langfuse  # noqa: PLC0415

            return Langfuse(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
            )
        except Exception:
            logger.warning("Failed to initialize Langfuse client; tracing disabled")
    return None


def get_langfuse():
    """Return singleton Langfuse client (None if not configured)."""
    global _langfuse  # noqa: PLW0603
    if _langfuse is None:
        _langfuse = _init_langfuse()
    return _langfuse


def _log_to_langfuse(
    model: str,
    prompt: str,
    completion: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Log a completed LLM generation to Langfuse (no-op when not configured)."""
    client = get_langfuse()
    if client is None:
        return
    try:
        gen = client.start_generation(
            name="llm.generate",
            model=model,
            input=prompt[:2000],
            output=completion,
            usage={"input": prompt_tokens, "output": completion_tokens},
        )
        gen.end()
    except Exception:
        logger.debug("Langfuse generation log failed", exc_info=True)


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
        self,
        model: str,
        messages: list[dict],
        settings: Settings,
        *,
        override_key: str | None = None,
        timeout: float | None = None,
    ) -> dict:
        kwargs: dict = {"model": model, "messages": messages}
        if timeout is not None:
            kwargs["request_timeout"] = timeout
            kwargs["timeout"] = timeout
        if override_key is not None:
            kwargs["api_key"] = override_key
        elif model.startswith("ollama/"):
            kwargs["api_base"] = settings.OLLAMA_URL
        elif model.startswith("openai/"):
            kwargs["api_key"] = settings.OPENAI_API_KEY
        elif model.startswith("anthropic/"):
            kwargs["api_key"] = settings.ANTHROPIC_API_KEY
        elif model.startswith("gemini/"):
            kwargs["api_key"] = settings.GOOGLE_API_KEY
        return kwargs

    def _resolve_model(
        self, model: str | None, *, background: bool
    ) -> tuple[str, str | None]:
        if model is not None:
            return model, None
        try:
            from app.services.settings_service import (  # noqa: PLC0415
                get_effective_routing,
            )

            return get_effective_routing(background=background)
        except ValueError:
            raise
        except Exception:
            return get_settings().LITELLM_DEFAULT_MODEL, None

    async def complete(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        background: bool = False,
        temperature: float | None = None,
        timeout: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        api_base: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Run a non-streaming completion against the given message list.

        Caller controls message shape (multi-turn, system+user, multimodal vision).
        Telemetry span and Langfuse logging are applied uniformly.
        """
        settings = get_settings()
        effective_model, override_key = self._resolve_model(model, background=background)

        kwargs = self._build_kwargs(
            effective_model, messages, settings, override_key=override_key, timeout=timeout
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format
        if api_base is not None:
            kwargs["api_base"] = api_base
        if extra:
            kwargs.update(extra)

        with trace_llm_call("complete", model=effective_model) as span:
            response = await litellm.acompletion(**kwargs)
            content = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            prompt_tokens = 0
            completion_tokens = 0
            if usage:
                prompt_tokens = getattr(usage, "prompt_tokens", 0)
                completion_tokens = getattr(usage, "completion_tokens", 0)
                span.set_attribute("llm.prompt_tokens", prompt_tokens)
                span.set_attribute("llm.completion_tokens", completion_tokens)
        prompt_text = _messages_to_text(messages)
        _log_to_langfuse(effective_model, prompt_text, content, prompt_tokens, completion_tokens)
        return content

    async def stream_messages(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        background: bool = False,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> AsyncGenerator[str]:
        """Stream content deltas for the given message list."""
        settings = get_settings()
        effective_model, override_key = self._resolve_model(model, background=background)
        kwargs = self._build_kwargs(
            effective_model, messages, settings, override_key=override_key, timeout=timeout
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        return self._token_stream(kwargs)

    async def generate(
        self,
        prompt: str,
        system: str = "",
        model: str | None = None,
        stream: bool = False,
        timeout: float | None = None,
        background: bool = False,
    ) -> str | AsyncGenerator[str]:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        if stream:
            return await self.stream_messages(
                messages, model=model, background=background, timeout=timeout
            )
        return await self.complete(
            messages, model=model, background=background, timeout=timeout
        )

    async def _token_stream(self, kwargs: dict) -> AsyncGenerator[str]:
        response = await litellm.acompletion(stream=True, **kwargs)
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


def _messages_to_text(messages: list[dict]) -> str:
    parts: list[str] = []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
    return "\n".join(parts)


_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
