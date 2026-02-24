"""OpenTelemetry tracing for Luminary — Phoenix in-process when PHOENIX_ENABLED.

Exported helpers:
  setup_tracing(phoenix_enabled)  — call once at startup
  get_tracer()                    — return the app-level Tracer
  trace_llm_call(operation)       — context manager; records model, tokens, latency_ms
  trace_retrieval(operation)      — context manager; records query, chunk_count, top_score
  trace_ingestion_node(node_name) — context manager; records node_name, document_id
"""

import logging
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Span

logger = logging.getLogger(__name__)

_initialized = False


def setup_tracing(phoenix_enabled: bool) -> None:
    """Initialize the tracer provider.  Called once at application startup."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    provider = TracerProvider()

    if phoenix_enabled:
        try:
            import phoenix as px
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            def _launch() -> None:
                try:
                    px.launch_app()
                    logger.info("Phoenix UI available on port 6006")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Phoenix launch failed: %s", exc)

            threading.Thread(target=_launch, daemon=True).start()

            exporter = OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("Phoenix tracing enabled")
        except ImportError:
            logger.warning("arize-phoenix not installed; Phoenix tracing disabled")

    trace.set_tracer_provider(provider)


def get_tracer() -> trace.Tracer:
    """Return the Luminary OpenTelemetry tracer."""
    return trace.get_tracer("luminary")


# ---------------------------------------------------------------------------
# Span context managers
# ---------------------------------------------------------------------------


@contextmanager
def trace_llm_call(
    operation: str,
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> Generator[Span]:
    """Context manager that wraps an LLM call with an OTel span.

    Usage::
        with trace_llm_call("generate", model="ollama/llama3") as span:
            result = await llm.acompletion(...)
            span.set_attribute("llm.completion_tokens", ...)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"llm.{operation}") as span:
        span.set_attribute("llm.operation", operation)
        if model:
            span.set_attribute("llm.model", model)
        if prompt_tokens:
            span.set_attribute("llm.prompt_tokens", prompt_tokens)
        if completion_tokens:
            span.set_attribute("llm.completion_tokens", completion_tokens)
        t0 = time.perf_counter()
        try:
            yield span
        except Exception as exc:
            span.set_attribute("error", True)
            span.set_attribute("error.message", str(exc))
            raise
        finally:
            span.set_attribute("llm.latency_ms", round((time.perf_counter() - t0) * 1000, 1))


@contextmanager
def trace_retrieval(
    operation: str,
    query: str = "",
) -> Generator[Span]:
    """Context manager that wraps a retrieval call with an OTel span.

    Usage::
        with trace_retrieval("hybrid", query=q) as span:
            results = await retriever.retrieve(q, ...)
            span.set_attribute("retrieval.chunk_count", len(results))
            span.set_attribute("retrieval.top_score", results[0].score if results else 0)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"retrieval.{operation}") as span:
        span.set_attribute("retrieval.operation", operation)
        if query:
            span.set_attribute("retrieval.query", query[:500])
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
    """Context manager that wraps a LangGraph ingestion node with an OTel span.

    Usage::
        with trace_ingestion_node("parse", state) as span:
            result = do_work(state)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"ingestion.{node_name}") as span:
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
