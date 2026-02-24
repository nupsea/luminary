"""OpenTelemetry tracing for Luminary — Phoenix in-process when PHOENIX_ENABLED."""

import logging
import threading

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

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
