"""Per-node implementations for the document-ingestion StateGraph.

`workflows/ingestion.py` keeps the StateGraph wiring (`_build_graph`,
`run_ingestion`, `_route_on_status`) and re-exports the node functions
+ shared types from this package so external imports
(`from app.workflows.ingestion import IngestionState`,
`from app.workflows.ingestion import classify_node`, etc.) keep working.

Shared types and foundation helpers live in `_shared.py`. Each pipeline
stage has its own module: parse.py, chunk.py, embed.py, entity_extract.py,
transcribe.py, finalize.py.
"""
