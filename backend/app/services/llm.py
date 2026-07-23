"""LiteLLM-backed LLM service — unified gateway for Ollama, OpenAI, Anthropic, Gemini.

All LLM completions in the codebase MUST go through this module so that telemetry
(OpenTelemetry spans) and Langfuse logging are applied uniformly. Direct calls to
litellm.acompletion in services/routers bypass observability.
"""

import asyncio
import logging
import socket
import warnings
from collections.abc import AsyncGenerator
from typing import Any

import litellm

from app.config import Settings, get_settings
from app.telemetry import trace_llm_call

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True
litellm.telemetry = False
# Drop provider-unsupported params instead of crashing: gpt-5 models reject
# temperature != 1 (and reasoning models reject others). Without this a chat
# routed to a gpt-5 model dies with UnsupportedParamsError -> blank screen.
# The model just falls back to its supported default for the dropped param.
litellm.drop_params = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)

# LiteLLM serializes the assembled streaming ModelResponse in its internal logging path; its
# `choices` field is typed for the streaming union (StreamingChoices) but holds the non-streaming
# Choices/Message at that point, so Pydantic v2 emits a cosmetic "serializer warnings" UserWarning
# on every streamed call. The JSON it produces is still correct -- silence just this one warning
# (matched by its distinctive message) rather than all UserWarnings.
warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
    category=UserWarning,
)

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

# The subset meaning "could not reach the provider" -- the offline case. Auth,
# rate-limit and not-found are deliberately excluded: they are configuration
# faults, and silently answering from a different model would hide them.
LLMUnreachableError: tuple[type[BaseException], ...] = (
    LLMServiceUnavailableError,
    LLMAPIConnectionError,
    LLMTimeoutError,
    ConnectionRefusedError,
)

# litellm maps a connection failure to InternalServerError ("OpenAIException -
# Connection error"), NOT APIConnectionError, so isinstance alone misses the very
# case this exists for. Walk the cause chain for the underlying socket/DNS error
# instead. InternalServerError from a genuine provider 500 has no such cause and
# is correctly left to propagate.
def _is_offline_error(exc: BaseException) -> bool:
    if isinstance(exc, LLMUnreachableError):
        return True
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, LLMUnreachableError):
            return True
        if isinstance(cur, (socket.gaierror, ConnectionError)):
            return True
        if isinstance(cur, OSError) and "Connect" in type(cur).__name__:
            return True
        cur = cur.__cause__ or cur.__context__
    return False

# Langfuse — optional LLM call observability

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
        num_ctx: int | None = None,
    ) -> dict:
        kwargs: dict = {"model": model, "messages": messages}
        if timeout is not None:
            kwargs["request_timeout"] = timeout
            kwargs["timeout"] = timeout
        if override_key is not None:
            kwargs["api_key"] = override_key
        elif model.startswith("ollama/"):
            kwargs["api_base"] = settings.OLLAMA_URL
            # Keep the model resident across requests and set the context window
            # explicitly (Ollama defaults to 2048 and silently truncates beyond it).
            # Heavy tasks (e.g. flashcard generation over a section) pass a larger num_ctx.
            kwargs["keep_alive"] = settings.OLLAMA_KEEP_ALIVE
            kwargs["num_ctx"] = num_ctx or settings.OLLAMA_NUM_CTX
            # Thinking-capable models (qwen3+) auto-enable reasoning, which
            # streams as reasoning_content (never surfaced) and burns the
            # num_ctx generation budget BEFORE any answer tokens -- on real QA
            # prompts the window dies mid-think and the answer arrives empty.
            # Luminary's prompts are all direct-answer shaped, so thinking is
            # disabled globally for local models.
            kwargs["think"] = False
        elif model.startswith("openai/"):
            kwargs["api_key"] = settings.OPENAI_API_KEY
        elif model.startswith("anthropic/"):
            kwargs["api_key"] = settings.ANTHROPIC_API_KEY
        elif model.startswith("gemini/"):
            kwargs["api_key"] = settings.GOOGLE_API_KEY
        return kwargs

    def _offline_fallback_kwargs(
        self,
        requested_model: str | None,
        effective_model: str,
        kwargs: dict,
        settings: Settings,
        *,
        num_ctx: int | None = None,
    ) -> dict | None:
        """Rebuild kwargs against the local model, or None when not applicable.

        Keeps the app usable with no internet: a cloud call that cannot reach its
        provider is retried on Ollama. Only for calls whose model came from
        routing -- an explicitly pinned model is honoured or allowed to fail, so
        evals and per-request overrides stay reproducible rather than silently
        answering from a different model.
        """
        if requested_model is not None:
            return None
        if effective_model.startswith("ollama/"):
            return None

        local_model = settings.LITELLM_DEFAULT_MODEL
        if not local_model.startswith("ollama/"):
            local_model = f"ollama/{local_model}"

        retry = self._build_kwargs(
            local_model,
            kwargs["messages"],
            settings,
            override_key=None,
            timeout=kwargs.get("timeout"),
            num_ctx=num_ctx,
        )
        for key in ("temperature", "max_tokens", "response_format", "stream"):
            if key in kwargs:
                retry[key] = kwargs[key]
        return retry

    async def _reroute_if_offline(
        self, requested_model: str | None, effective_model: str, settings: Settings
    ) -> tuple[str, str | None, bool]:
        """Swap a routed cloud model for the local one when the provider is
        unreachable, before any call is attempted.

        Returns (model, override_key, rerouted). Skipped for pinned models so
        evals and overrides stay reproducible. Doing this up front avoids the
        SDK's multi-retry stall on a dead connection.
        """
        from app.services.connectivity import is_cloud_model, provider_reachable  # noqa: PLC0415

        if requested_model is not None or not is_cloud_model(effective_model):
            return effective_model, None, False
        if await asyncio.to_thread(provider_reachable, effective_model):
            return effective_model, None, False

        local_model = settings.LITELLM_DEFAULT_MODEL
        if not local_model.startswith("ollama/"):
            local_model = f"ollama/{local_model}"
        logger.warning(
            "%s provider unreachable; routing to local model %s",
            effective_model,
            local_model,
        )
        return local_model, None, True

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
        num_ctx: int | None = None,
    ) -> str:
        """Run a non-streaming completion against the given message list.

        Caller controls message shape (multi-turn, system+user, multimodal vision).
        Telemetry span and Langfuse logging are applied uniformly.
        """
        settings = get_settings()
        effective_model, override_key = self._resolve_model(model, background=background)
        effective_model, override_key, _ = await self._reroute_if_offline(
            model, effective_model, settings
        )

        kwargs = self._build_kwargs(
            effective_model, messages, settings,
            override_key=override_key, timeout=timeout, num_ctx=num_ctx,
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
            try:
                response = await litellm.acompletion(**kwargs)
            except Exception as exc:
                retry = (
                    self._offline_fallback_kwargs(
                        model, effective_model, kwargs, settings, num_ctx=num_ctx
                    )
                    if _is_offline_error(exc)
                    else None
                )
                if retry is None:
                    raise
                logger.warning(
                    "%s unreachable (%s); retrying on local model %s",
                    effective_model,
                    type(exc).__name__,
                    retry["model"],
                )
                effective_model = retry["model"]
                span.set_attribute("llm.offline_fallback", True)
                response = await litellm.acompletion(**retry)
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
        num_ctx: int | None = None,
    ) -> AsyncGenerator[str]:
        """Stream content deltas for the given message list."""
        settings = get_settings()
        effective_model, override_key = self._resolve_model(model, background=background)
        effective_model, override_key, _ = await self._reroute_if_offline(
            model, effective_model, settings
        )
        kwargs = self._build_kwargs(
            effective_model, messages, settings,
            override_key=override_key, timeout=timeout, num_ctx=num_ctx,
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        fallback = self._offline_fallback_kwargs(
            model, effective_model, kwargs, settings, num_ctx=num_ctx
        )
        return self._token_stream(kwargs, fallback)

    async def generate(
        self,
        prompt: str,
        system: str = "",
        model: str | None = None,
        stream: bool = False,
        timeout: float | None = None,
        background: bool = False,
        response_format: dict | None = None,
        num_ctx: int | None = None,
        temperature: float | None = None,
    ) -> str | AsyncGenerator[str]:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        if stream:
            return await self.stream_messages(
                messages,
                model=model,
                background=background,
                timeout=timeout,
                num_ctx=num_ctx,
                temperature=temperature,
            )
        return await self.complete(
            messages,
            model=model,
            background=background,
            timeout=timeout,
            response_format=response_format,
            num_ctx=num_ctx,
            temperature=temperature,
        )

    async def _token_stream(
        self, kwargs: dict, fallback_kwargs: dict | None = None
    ) -> AsyncGenerator[str]:
        try:
            response = await litellm.acompletion(stream=True, **kwargs)
        except Exception as exc:
            if fallback_kwargs is None or not _is_offline_error(exc):
                raise
            logger.warning(
                "%s unreachable while streaming (%s); retrying on local model %s",
                kwargs.get("model"),
                type(exc).__name__,
                fallback_kwargs["model"],
            )
            fallback_kwargs.pop("stream", None)
            response = await litellm.acompletion(stream=True, **fallback_kwargs)
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
