"""Graph payloads for the Map tab (`pages/Viz.tsx`), assembled from the graph repos."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GraphEntityModel
from app.repos.graph_diagram_repo import GraphDiagramRepo
from app.repos.graph_entity_repo import GraphEntityRepo
from app.repos.graph_note_entity_repo import GraphNoteEntityRepo

_TECH_RELATIONS = ("IMPLEMENTS", "EXTENDS", "USES", "REPLACES", "DEPENDS_ON")
_NOTE_RELATIONS = {"written_about": "WRITTEN_ABOUT", "tag": "TAG_IS_CONCEPT"}


def _entity_node(e: GraphEntityModel) -> dict:
    return {
        "id": e.id,
        "label": e.name,
        "type": e.type,
        "size": e.frequency or 1,
        "source_image_id": "",
        "mention_count": e.mention_count or 1,
        "document_id": e.document_id,
        "document_ids": [e.document_id],
    }


async def _diagram(session: AsyncSession, document_id: str) -> tuple[list[dict], list[dict]]:
    repo = GraphDiagramRepo(session)
    nodes = [
        {
            "id": n.id,
            "label": n.name,
            "type": n.node_type,
            "size": n.frequency or 1,
            "source_image_id": n.source_image_id or "",
            "mention_count": n.frequency or 1,
            "document_id": document_id,
            "document_ids": [document_id],
        }
        for n in await repo.nodes_for_document(document_id)
    ]
    edges = [
        {"source": e.source_id, "target": e.target_id, "weight": 1.0, "relation": e.kind}
        for e in await repo.edges_for_document(document_id)
    ]
    return nodes, edges


async def _co_occurrence_edges(repo: GraphEntityRepo, document_ids: list[str]) -> list[dict]:
    return [
        {"source": e.source_id, "target": e.target_id, "weight": e.weight}
        for e in await repo.edges_for_documents(document_ids, ("CO_OCCURS",))
    ]


async def _note_graph(session: AsyncSession, entity_ids: set[str]) -> tuple[list[dict], list[dict]]:
    """Notes about entities in scope, their edges to those entities, and links among them."""
    repo = GraphNoteEntityRepo(session)
    previews: dict[str, str] = {}
    entity_edges: list[dict] = []
    for note_id, content, entity_id, confidence, kind in await repo.links_for_entities(entity_ids):
        previews.setdefault(note_id, (content or "")[:200])
        entity_edges.append(
            {
                "source": note_id,
                "target": entity_id,
                "weight": confidence if kind == "written_about" else 1.0,
                "relation": _NOTE_RELATIONS[kind],
            }
        )
    links = await repo.note_links_among(list(previews))
    outgoing: dict[str, int] = {}
    for edge in entity_edges:
        outgoing[edge["source"]] = outgoing.get(edge["source"], 0) + 1
    for source, _ in links:
        outgoing[source] = outgoing.get(source, 0) + 1
    nodes = [
        {
            "id": note_id,
            "note_id": note_id,
            "label": preview[:40] if preview else note_id[:40],
            "type": "note",
            "size": max(8, int((outgoing[note_id] ** 0.5) * 5)),
            "outgoing_link_count": outgoing[note_id],
            "source_image_id": "",
        }
        for note_id, preview in previews.items()
    ]
    link_edges = [
        {"source": s, "target": t, "weight": 1.0, "relation": "LINKS_TO"} for s, t in links
    ]
    return nodes, entity_edges + link_edges


async def document_graph(session: AsyncSession, document_id: str, include_notes: bool) -> dict:
    """Entities with their co-occurrence, tech and prerequisite edges, plus diagram nodes."""
    repo = GraphEntityRepo(session)
    entities = await repo.entities_for_document(document_id)
    nodes = [_entity_node(e) for e in entities]
    edges = await _co_occurrence_edges(repo, [document_id])
    for kind in (*_TECH_RELATIONS, "PREREQUISITE_OF"):
        for e in await repo.edges_for_documents([document_id], (kind,)):
            weight = float(e.confidence or 1.0) if kind == "PREREQUISITE_OF" else 1.0
            edges.append(
                {"source": e.source_id, "target": e.target_id, "weight": weight, "relation": kind}
            )
    diagram_nodes, diagram_edges = await _diagram(session, document_id)
    nodes += diagram_nodes
    edges += diagram_edges
    if include_notes and entities:
        note_nodes, note_edges = await _note_graph(session, {e.id for e in entities})
        nodes += note_nodes
        edges += note_edges
    return {"nodes": nodes, "edges": edges}


async def documents_graph(
    session: AsyncSession,
    document_ids: list[str],
    include_same_concept: bool,
    include_notes: bool,
) -> dict:
    """Entities and diagrams of several documents, with co-occurrence edges and,
    on request, SAME_CONCEPT links between them and the notes about them."""
    if not document_ids:
        return {"nodes": [], "edges": []}
    repo = GraphEntityRepo(session)
    nodes_map = {e.id: _entity_node(e) for e in await repo.entities_for_documents(document_ids)}
    entity_ids = set(nodes_map)
    edges = await _co_occurrence_edges(repo, document_ids)
    for doc_id in document_ids:
        diagram_nodes, diagram_edges = await _diagram(session, doc_id)
        for node in diagram_nodes:
            nodes_map.setdefault(node["id"], node)
        edges += diagram_edges
    if include_same_concept:
        edges += [
            {
                "source": link["entity_id_a"],
                "target": link["entity_id_b"],
                "weight": link["confidence"],
                "relation": "SAME_CONCEPT",
                "contradiction": link["contradiction"],
            }
            for link in await repo.links()
            if link["entity_id_a"] in nodes_map and link["entity_id_b"] in nodes_map
        ]
    if include_notes and entity_ids:
        note_nodes, note_edges = await _note_graph(session, entity_ids)
        for node in note_nodes:
            nodes_map.setdefault(node["id"], node)
        edges += note_edges
    return {"nodes": list(nodes_map.values()), "edges": edges}


async def call_graph(repo: GraphEntityRepo, document_id: str) -> dict:
    """Functions and the CALLS edges between them, for a code document."""
    entities = {e.id: e for e in await repo.entities_for_document(document_id)}
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for edge in await repo.edges_for_documents([document_id], ("CALLS",)):
        for eid in (edge.source_id, edge.target_id):
            e = entities[eid]
            nodes.setdefault(
                eid,
                {
                    "id": eid,
                    "label": e.name,
                    "type": e.type or "FUNCTION",
                    "size": e.frequency or 1,
                },
            )
        edges.append({"source": edge.source_id, "target": edge.target_id, "weight": 1.0})
    return {"nodes": list(nodes.values()), "edges": edges}


def concept_clusters(links: list[dict]) -> list[dict]:
    """Group entities joined by SAME_CONCEPT links (union-find).

    Each cluster: concept_name (its longest member name), entity_ids, entity_names,
    document_ids, has_contradiction, contradiction_note.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        if parent.setdefault(x, x) != x:
            parent[x] = find(parent[x])
        return parent[x]

    names: dict[str, str] = {}
    docs: dict[str, str] = {}
    for link in links:
        a, b = link["entity_id_a"], link["entity_id_b"]
        names[a], names[b] = link["name_a"], link["name_b"]
        docs[a], docs[b] = link["source_doc_id"], link["target_doc_id"]
        parent[find(a)] = find(b)

    groups: dict[str, list[str]] = {}
    for eid in names:
        groups.setdefault(find(eid), []).append(eid)
    contradictions: dict[str, str] = {}
    for link in links:
        if link["contradiction"]:
            contradictions.setdefault(find(link["entity_id_a"]), link["contradiction_note"])

    return [
        {
            "concept_name": max((names[eid] or "" for eid in eids), key=len),
            "entity_ids": eids,
            "entity_names": [names[eid] for eid in eids if names[eid]],
            "document_ids": sorted({docs[eid] for eid in eids if docs.get(eid)}),
            "has_contradiction": root in contradictions,
            "contradiction_note": contradictions.get(root, ""),
        }
        for root, eids in groups.items()
    ]
