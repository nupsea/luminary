# Reliability — SLOs

## Service Level Objectives

| Operation                  | SLO Target  | Measurement        |
|----------------------------|-------------|---------------------|
| Document ingestion (p95)   | < 30s       | per document        |
| Q&A response (p95)         | < 3s        | end-to-end          |
| Embedding batch (p95)      | < 60s       | per 100 chunks      |
| Flashcard generation (p95) | < 5s        | per document        |
| Hybrid search (p95)        | < 500ms     | RRF query           |

## Reliability Requirements

- **Local-first**: All core functionality must work without internet (Ollama local LLM)
- **Data safety**: Writes are atomic; incomplete ingestion must not corrupt existing data
- **Graceful degradation**: If Ollama is unreachable, return error; do not hang
- **Storage limits**: Warn user when DATA_DIR exceeds 10 GB

## Monitoring

- Arize Phoenix (port 6006) captures all LangGraph node latencies via OpenTelemetry
- Langfuse records evaluation runs and golden dataset results
- Structured logs (JSON) written to DATA_DIR/logs/ with rotation
