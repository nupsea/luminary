"""Per-node implementations for the chat StateGraph.

`chat_graph.py` keeps the StateGraph wiring (`build_chat_graph`,
`classify_node`, `route_node`) and re-exports the node functions from
this package so external imports
(`from app.runtime.chat_graph import summary_node`) keep working.

Phase 1 (this commit): extract shared constants/helpers into
`_shared`. Future phases move the node bodies into per-node modules
(summary.py, graph.py, comparative.py, search.py, notes.py,
socratic.py, synthesize.py, confidence.py).
"""
