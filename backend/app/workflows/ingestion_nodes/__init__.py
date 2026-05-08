"""Per-node implementations for the document-ingestion StateGraph.

`workflows/ingestion.py` keeps the StateGraph wiring (`_build_graph`,
`run_ingestion`, `_route_on_status`) and re-exports the node functions
+ shared types from this package so external imports
(`from app.workflows.ingestion import IngestionState`,
`from app.workflows.ingestion import classify_node`, etc.) keep
working.

Phased extraction mirrors `runtime/chat_nodes/`. Phase 1 (this commit):
shared types + foundation helpers in `_shared.py`. Future phases lift
each node body into its own module.
"""
