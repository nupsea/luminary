"""OpenTelemetry tracing for Luminary — Phoenix in-process when PHOENIX_ENABLED.

Traces are organised under the "luminary" project in Phoenix with proper
OpenInference span kinds so the Phoenix UI renders LLM calls, retrievals,
and pipeline chains with their native rich views.

LiteLLM is auto-instrumented: every litellm.acompletion() automatically
produces an LLM span with input messages, output, model name, and token
counts — no manual wrapping needed.

Exported helpers:
  setup_tracing(phoenix_enabled)  — call once at startup
  get_tracer()                    — return the app-level Tracer
  trace_chain(name, input)        — CHAIN span (QA, flashcard gen, ingestion)
  trace_retrieval(operation)      — RETRIEVER span
  trace_ingestion_node(node_name) — CHAIN span for a LangGraph ingestion node

  trace_llm_call — kept for backwards compatibility; is now a lightweight
                   passthrough wrapper around trace_chain.
"""

import logging
import os
import socket
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes

logger = logging.getLogger(__name__)

_SPAN_KIND   = SpanAttributes.OPENINFERENCE_SPAN_KIND
_INPUT_VAL   = SpanAttributes.INPUT_VALUE
_OUTPUT_VAL  = SpanAttributes.OUTPUT_VALUE

_KIND_CHAIN     = OpenInferenceSpanKindValues.CHAIN.value
_KIND_RETRIEVER = OpenInferenceSpanKindValues.RETRIEVER.value

_initialized = False
_PHOENIX_PORT = 6006
_PHOENIX_OTLP_ENDPOINT = f"http://localhost:{_PHOENIX_PORT}/v1/traces"


def _wait_for_phoenix(timeout: float = 15.0, interval: float = 0.5) -> bool:
    """Poll localhost:6006 until Phoenix is accepting connections or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("localhost", _PHOENIX_PORT), timeout=1):
                return True
        except OSError:
            time.sleep(interval)
    return False


def setup_tracing(phoenix_enabled: bool, data_dir: str = "~/.luminary") -> None:
    """Initialize the tracer provider.  Called once at application startup.

    When phoenix_enabled is True:
    - Starts the Phoenix in-process server on port 6006, storing traces
      persistently in <data_dir>/phoenix so they survive backend restarts.
    - Waits up to 15 s for Phoenix to bind before registering the exporter,
      eliminating the startup race that caused Connection Refused errors.
    - Registers a TracerProvider that exports to the "luminary" project.
    - Auto-instruments LiteLLM so every LLM call is captured with input
      messages, output, model name, and token counts.
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    if not phoenix_enabled:
        from opentelemetry.sdk.trace import TracerProvider
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        logger.info("Phoenix tracing disabled; using no-op provider")
        return

    try:
        import phoenix as px
        from phoenix.otel import register
        from openinference.instrumentation.litellm import LiteLLMInstrumentor

        # Store Phoenix data in the app's data directory so traces persist
        # across backend restarts (not lost in a temp dir).
        phoenix_dir = Path(data_dir).expanduser() / "phoenix"
        phoenix_dir.mkdir(parents=True, exist_ok=True)
        os.environ["PHOENIX_WORKING_DIR"] = str(phoenix_dir)

        # launch_app() starts Phoenix's own internal server thread and returns
        # quickly.  We do NOT wrap this in another thread — the double-threading
        # was the source of the race condition.
        px.launch_app(use_temp_dir=False)

        # Wait for Phoenix to actually bind to the port before we register the
        # OTLP exporter.  Without this wait the first span batches are dropped
        # with "Connection refused" because the BatchSpanProcessor flushes
        # before Phoenix finishes binding.
        if _wait_for_phoenix():
            logger.info("Phoenix UI available at http://localhost:%d", _PHOENIX_PORT)
        else:
            logger.warning(
                "Phoenix did not bind within 15 s — tracing may be incomplete"
            )

        # Register the TracerProvider for the "luminary" project.
        tracer_provider = register(
            project_name="luminary",
            endpoint=_PHOENIX_OTLP_ENDPOINT,
            batch=True,
            verbose=False,
        )

        # Auto-instrument LiteLLM — every acompletion() call becomes an LLM
        # span with input messages, output, model name, and token counts.
        LiteLLMInstrumentor().instrument(tracer_provider=tracer_provider)

        logger.info("Phoenix tracing enabled — project: luminary, dir: %s", phoenix_dir)

    except ImportError as exc:
        logger.warning("Phoenix tracing setup failed (missing package): %s", exc)
        from opentelemetry.sdk.trace import TracerProvider
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Phoenix tracing setup failed: %s", exc)
        from opentelemetry.sdk.trace import TracerProvider
        provider = TracerProvider()
        trace.set_tracer_provider(provider)


def get_tracer() -> trace.Tracer:
    """Return the Luminary OpenTelemetry tracer."""
    return trace.get_tracer("luminary")


# ---------------------------------------------------------------------------
# Span context managers — all use OpenInference semantic conventions
# ---------------------------------------------------------------------------

@contextmanager
def trace_chain(
    name: str,
    input_value: str = "",
) -> Generator[Span]:
    """Wrap a logical pipeline step as a CHAIN span.

    Sets openinference.span.kind = CHAIN and optionally records input.value.
    Call span.set_attribute(OUTPUT_VALUE, ...) inside the block to record output.

    Usage::
        with trace_chain("qa.stream_answer", input_value=question) as span:
            ...
            span.set_attribute("output.value", answer_text)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        span.set_attribute(_SPAN_KIND, _KIND_CHAIN)
        if input_value:
            span.set_attribute(_INPUT_VAL, input_value[:1000])
        t0 = time.perf_counter()
        try:
            yield span
        except Exception as exc:
            span.set_attribute("error", True)
            span.set_attribute("error.message", str(exc))
            raise
        finally:
            span.set_attribute("latency_ms", round((time.perf_counter() - t0) * 1000, 1))


@contextmanager
def trace_retrieval(
    operation: str,
    query: str = "",
) -> Generator[Span]:
    """Wrap a retrieval step as a RETRIEVER span.

    Usage::
        with trace_retrieval("hybrid", query=q) as span:
            results = await retriever.retrieve(q, ...)
            span.set_attribute("retrieval.chunk_count", len(results))
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"retrieval.{operation}") as span:
        span.set_attribute(_SPAN_KIND, _KIND_RETRIEVER)
        span.set_attribute("retrieval.operation", operation)
        if query:
            span.set_attribute(_INPUT_VAL, query[:500])
        t0 = time.perf_counter()
        try:
            yield span
        except Exception as exc:
            span.set_attribute("error", True)
            span.set_attribute("error.message", str(exc))
            raise
        finally:
            span.set_attribute(
                "retrieval.latency_ms", round((time.perf_counter() - t0) * 1000, 1)
            )


@contextmanager
def trace_ingestion_node(
    node_name: str,
    state: dict[str, Any] | None = None,
) -> Generator[Span]:
    """Wrap a LangGraph ingestion node as a CHAIN span.

    Usage::
        with trace_ingestion_node("parse", state) as span:
            result = do_work(state)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"ingestion.{node_name}") as span:
        span.set_attribute(_SPAN_KIND, _KIND_CHAIN)
        span.set_attribute("ingestion.node_name", node_name)
        if state:
            span.set_attribute("ingestion.document_id", state.get("document_id", ""))
            if state.get("content_type"):
                span.set_attribute("ingestion.content_type", state["content_type"])
        t0 = time.perf_counter()
        try:
            yield span
        except Exception as exc:
            span.set_attribute("error", True)
            span.set_attribute("error.message", str(exc))
            raise
        finally:
            span.set_attribute(
                "ingestion.latency_ms", round((time.perf_counter() - t0) * 1000, 1)
            )


# Backwards-compatible alias — callers in llm.py still reference this.
# LiteLLM is now auto-instrumented so this just creates a thin CHAIN wrapper
# that gives call-site context to the auto-generated LLM child span.
@contextmanager
def trace_llm_call(
    operation: str,
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> Generator[Span]:
    """Backwards-compatible wrapper — delegates to trace_chain.

    The actual LLM span (with messages, tokens, model) is produced automatically
    by the LiteLLMInstrumentor. This wrapper provides a parent CHAIN span so the
    call appears nested under the right operation in Phoenix.
    """
    with trace_chain(f"llm.{operation}") as span:
        if model:
            span.set_attribute("llm.model", model)
        yield span
