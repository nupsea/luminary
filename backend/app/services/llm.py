"""LiteLLM-backed LLM service — unified gateway for Ollama, OpenAI, Anthropic, Gemini."""

import logging
from collections.abc import AsyncGenerator

import litellm

from app.config import Settings, get_settings
from app.telemetry import trace_llm_call

logger = logging.getLogger(__name__)

# Silence litellm's verbose success logging
litellm.suppress_debug_info = True
litellm.telemetry = False
# Suppress the per-call INFO log ("LiteLLM completion() model= ...") — too noisy
logging.getLogger("LiteLLM").setLevel(logging.WARNING)

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

    async def generate(
        self,
        prompt: str,
        system: str = "",
        model: str | None = None,
        stream: bool = False,
        timeout: float | None = None,
        background: bool = False,
    ) -> str | AsyncGenerator[str]:
        settings = get_settings()
        override_key: str | None = None

        if model is None:
            try:
                from app.services.settings_service import (  # noqa: PLC0415
                    get_effective_routing,
                )

                effective_model, override_key = get_effective_routing(background=background)
            except ValueError:
                raise
            except Exception:
                effective_model = settings.LITELLM_DEFAULT_MODEL
        else:
            effective_model = model

        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs = self._build_kwargs(
            effective_model, messages, settings, override_key=override_key, timeout=timeout
        )

        if not stream:
            with trace_llm_call("generate", model=effective_model) as span:
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
            _log_to_langfuse(effective_model, prompt, content, prompt_tokens, completion_tokens)
            return content

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
