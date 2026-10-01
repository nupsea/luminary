"""NoteGraphService: the entities a note is about.

  - written_about: entities GLiNER finds in the note's text
  - tag: entities whose name matches one of the note's tags

Links to a note's source documents live in `note_sources`, and links between notes in
`note_links`; the graph reads those tables rather than keeping copies. Edges cascade
with the note and the entity, so a deleted note leaves nothing behind (#65).
"""

import asyncio
import logging

from app.database import get_session_factory
from app.repos.graph_note_entity_repo import GraphNoteEntityRepo
from app.services import ner as _ner_module  # indirect: get_entity_extractor is patched

logger = logging.getLogger(__name__)

_note_graph_service: "NoteGraphService | None" = None


def get_note_graph_service() -> "NoteGraphService":
    global _note_graph_service
    if _note_graph_service is None:
        _note_graph_service = NoteGraphService()
    return _note_graph_service


class NoteGraphService:
    async def upsert_note_node(
        self, note_id: str, content: str, document_id: str | None, tags: list[str]
    ) -> None:
        """Replace the note's entity links from its current text and tags.

        Called fire-and-forget after a note is saved; failures are logged, never raised.
        """
        try:
            entities = await asyncio.to_thread(
                self._extract_entities, note_id, content, document_id
            )
            async with get_session_factory()() as session:
                repo = GraphNoteEntityRepo(session)
                names = [e.get("name", "") for e in entities] + list(tags)
                ids = await repo.resolve_names(names, document_id)
                rows = [
                    {
                        "entity_id": ids[e["name"].lower()],
                        "kind": "written_about",
                        "confidence": float(e.get("score", 0.8)),
                    }
                    for e in entities
                    if e.get("name") and e["name"].lower() in ids
                ]
                rows += [
                    {"entity_id": ids[t.lower()], "kind": "tag", "confidence": 1.0, "tag": t}
                    for t in tags
                    if t and t.lower() in ids
                ]
                await repo.replace(note_id, rows)
                await session.commit()
        except Exception:
            logger.warning("upsert_note_node failed (non-fatal) for %s", note_id, exc_info=True)

    def _extract_entities(self, note_id: str, content: str, document_id: str | None) -> list[dict]:
        try:
            extractor = _ner_module.get_entity_extractor()
            chunks = [{"id": note_id, "document_id": document_id or "", "text": content}]
            return extractor.extract(chunks, content_type="unknown")
        except Exception as exc:
            logger.warning("GLiNER extraction failed for note %s: %s", note_id, exc)
            return []

    async def get_entities_for_note(self, note_id: str) -> list[dict]:
        """[{name, type, confidence, edge_type}] for the note's entities."""
        async with get_session_factory()() as session:
            rows = await GraphNoteEntityRepo(session).entities_for_note(note_id)
        return [
            {
                "name": name,
                "type": etype,
                "confidence": confidence if kind == "written_about" else 1.0,
                "edge_type": "WRITTEN_ABOUT" if kind == "written_about" else "TAG_IS_CONCEPT",
            }
            for name, etype, kind, confidence in rows
        ]
