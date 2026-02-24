"""Tests for OTel instrumentation — verify span attributes without a live Phoenix."""

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.telemetry import trace_ingestion_node, trace_llm_call, trace_retrieval

# ---------------------------------------------------------------------------
# In-memory OTel exporter fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def in_memory_tracer(monkeypatch):
    """Inject an in-memory tracer into app.telemetry for each test.

    OTel's global TracerProvider cannot be overridden once set, so we
    monkeypatch get_tracer() to return a tracer backed by our exporter.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    test_tracer = provider.get_tracer("test")
    monkeypatch.setattr("app.telemetry.get_tracer", lambda: test_tracer)
    yield exporter
    exporter.clear()


# ---------------------------------------------------------------------------
# trace_llm_call
# ---------------------------------------------------------------------------


def test_trace_llm_call_creates_span_with_model(in_memory_tracer):
    """trace_llm_call creates a span with llm.model attribute."""
    with trace_llm_call("generate", model="ollama/llama3"):
        pass

    spans = in_memory_tracer.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "llm.generate"
    assert span.attributes.get("llm.model") == "ollama/llama3"
    assert span.attributes.get("llm.operation") == "generate"


def test_trace_llm_call_records_latency(in_memory_tracer):
    """trace_llm_call sets llm.latency_ms attribute."""
    with trace_llm_call("generate", model="test-model"):
        pass

    spans = in_memory_tracer.get_finished_spans()
    assert len(spans) == 1
    latency = spans[0].attributes.get("llm.latency_ms")
    assert latency is not None
    assert latency >= 0.0


def test_trace_llm_call_records_error(in_memory_tracer):
    """trace_llm_call sets error attribute on exception."""
    with pytest.raises(ValueError):
        with trace_llm_call("generate", model="bad-model"):
            raise ValueError("LLM timeout")

    spans = in_memory_tracer.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes.get("error") is True
    assert "LLM timeout" in span.attributes.get("error.message", "")


def test_trace_llm_call_sets_token_attributes(in_memory_tracer):
    """trace_llm_call propagates prompt_tokens and completion_tokens."""
    with trace_llm_call("generate", model="m", prompt_tokens=50, completion_tokens=20) as span:
        span.set_attribute("llm.prompt_tokens", 50)
        span.set_attribute("llm.completion_tokens", 20)

    spans = in_memory_tracer.get_finished_spans()
    assert spans[0].attributes.get("llm.prompt_tokens") == 50
    assert spans[0].attributes.get("llm.completion_tokens") == 20


# ---------------------------------------------------------------------------
# trace_retrieval
# ---------------------------------------------------------------------------


def test_trace_retrieval_creates_span_with_query(in_memory_tracer):
    """trace_retrieval creates a span with retrieval.query attribute."""
    with trace_retrieval("hybrid", query="What is deep learning?"):
        pass

    spans = in_memory_tracer.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "retrieval.hybrid"
    assert "deep learning" in span.attributes.get("retrieval.query", "")


def test_trace_retrieval_allows_setting_chunk_count(in_memory_tracer):
    """trace_retrieval span can have chunk_count and top_score set manually."""
    with trace_retrieval("hybrid", query="test") as span:
        span.set_attribute("retrieval.chunk_count", 5)
        span.set_attribute("retrieval.top_score", 0.92)

    spans = in_memory_tracer.get_finished_spans()
    span = spans[0]
    assert span.attributes.get("retrieval.chunk_count") == 5
    assert abs(span.attributes.get("retrieval.top_score", 0) - 0.92) < 0.001


def test_trace_retrieval_records_latency(in_memory_tracer):
    """trace_retrieval sets retrieval.latency_ms."""
    with trace_retrieval("hybrid"):
        pass

    spans = in_memory_tracer.get_finished_spans()
    assert spans[0].attributes.get("retrieval.latency_ms") is not None


# ---------------------------------------------------------------------------
# trace_ingestion_node
# ---------------------------------------------------------------------------


def test_trace_ingestion_node_creates_span_with_node_name(in_memory_tracer):
    """trace_ingestion_node creates a span with ingestion.node_name."""
    state = {"document_id": "doc-123", "content_type": "notes", "file_path": "/tmp/x.pdf"}
    with trace_ingestion_node("parse", state):
        pass

    spans = in_memory_tracer.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "ingestion.parse"
    assert span.attributes.get("ingestion.node_name") == "parse"
    assert span.attributes.get("ingestion.document_id") == "doc-123"
    assert span.attributes.get("ingestion.content_type") == "notes"


def test_trace_ingestion_node_no_state(in_memory_tracer):
    """trace_ingestion_node works without state."""
    with trace_ingestion_node("embed"):
        pass

    spans = in_memory_tracer.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes.get("ingestion.node_name") == "embed"


def test_trace_ingestion_node_records_latency(in_memory_tracer):
    """trace_ingestion_node sets ingestion.latency_ms."""
    with trace_ingestion_node("chunk", {"document_id": "d1"}):
        pass

    spans = in_memory_tracer.get_finished_spans()
    assert spans[0].attributes.get("ingestion.latency_ms") is not None
