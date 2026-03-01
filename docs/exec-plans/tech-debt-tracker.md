# Technical Debt Tracker

| ID | Description | Priority | Owner | Created |
|----|-------------|----------|-------|---------|
| TD-001 | Notes data model lacks section_id — note indicators in DocumentReader cannot persist across page reloads | med | ralph | 2026-02-25 |
| TD-002 | datetime.utcnow() deprecated in Python 3.12+ — multiple routers use it; replace with datetime.now(UTC) throughout | low | ralph | 2026-02-25 |
| TD-003 | Bundle size ~1.2MB (warning threshold 500KB) — consider dynamic import() for Sigma.js/Graphology and Recharts | low | ralph | 2026-02-25 |
| TD-004 | API key storage in SQLite settings table is plaintext — migrate to OS keychain (see app/routers/settings.py TODO comment) | med | ralph | 2026-02-25 |
| TD-005 | PATCH /settings boundary_checker warning — parameter `updates` uses raw dict; replace with typed Pydantic schema | low | ralph | 2026-02-25 |
| TD-006 | S31: classify_node may crash ASGI app if Ollama is unreachable (sync LiteLLM call in async context) — needs investigation | high | ralph | 2026-02-25 |
| TD-007 | No conftest.py fixture to isolate DATA_DIR for tests — tests may conflict with dev backend Kuzu/LanceDB files | high | ralph | 2026-02-25 |
| TD-008 | Raw uploaded files (~/.luminary/raw/{doc_id}.ext) are not deleted when a document is deleted — accumulates disk usage over time | low | ralph | 2026-03-01 |
| TD-009 | `conversation` summary mode is not pre-generated during ingestion — first request triggers a full on-demand LLM call even though `_map_reduce` cache skips the map step | low | ralph | 2026-03-01 |
| TD-010 | SQLite FK pragma not enabled — cascading deletes are implemented manually in every delete endpoint; risk of orphaned rows if a new related table is added without updating all delete paths | med | ralph | 2026-03-01 |
