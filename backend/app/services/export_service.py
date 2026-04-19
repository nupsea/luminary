"""ExportService -- exports note collections to Obsidian-compatible Markdown vault or Anki deck.

Two formats supported:
  markdown  -- zip of .md files with YAML frontmatter; [[id|text]] links -> Obsidian [[title]]
  anki      -- .apkg file (genanki) with one card per FlashcardModel in the collection's deck
"""

import hashlib
import io
import logging
import re
import zipfile

import genanki
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CollectionMemberModel,
    CollectionModel,
    DocumentModel,
    FlashcardModel,
    NoteModel,
)

logger = logging.getLogger(__name__)

# Regex for [[note_id|display text]] markers (S171 note links)
_LINK_RE = re.compile(r"\[\[([a-f0-9\-]{36})\|([^\]]+)\]\]")

# Anki note model -- standard Basic model fields: Front, Back
_ANKI_MODEL_ID = 1607392319  # fixed; avoids regenerating model each export
_ANKI_MODEL = genanki.Model(
    _ANKI_MODEL_ID,
    "Luminary Basic",
    fields=[
        {"name": "Front"},
        {"name": "Back"},
    ],
    templates=[
        {
            "name": "Card 1",
            "qfmt": "{{Front}}",
            "afmt": "{{FrontSide}}<hr id=answer>{{Back}}",
        }
    ],
)


def _slugify(text: str) -> str:
    """Convert text to a safe filename slug."""
    slug = text.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:60] or "note"


def _build_yaml_frontmatter(
    note: NoteModel,
    collection_path: list[str],
    doc_title: str | None,
) -> str:
    """Build YAML frontmatter block for a note."""
    created = note.created_at.isoformat() if note.created_at else ""
    lines = ["---", "tags:"]
    if note.tags:
        lines += [f"  - {t}" for t in note.tags]
    else:
        lines.append("  []")
    lines.append("collections:")
    if collection_path:
        lines += [f"  - {p}" for p in collection_path]
    else:
        lines.append("  []")
    lines.append(f"created_at: {created}")
    if doc_title:
        lines.append(f"source_document: {doc_title}")
    lines.append("---")
    return "\n".join(lines)


def _resolve_links(content: str, id_to_title: dict[str, str]) -> str:
    """Replace [[note_id|text]] markers with Obsidian [[target title]] wikilinks.

    Unresolvable IDs (not in id_to_title) are rendered as plain text.
    """

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        note_id = m.group(1)
        display_text = m.group(2)
        target_title = id_to_title.get(note_id)
        if target_title:
            return f"[[{target_title}]]"
        # unresolvable -- render as plain text
        return display_text

    return _LINK_RE.sub(_replace, content)


def _note_title(note: NoteModel) -> str:
    """Derive a display title from the first non-empty line of note content."""
    for line in note.content.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:80]
    return note.id[:8]


class ExportService:
    """Service for exporting collections to external formats."""

    async def _fetch_collection_notes(
        self,
        collection_id: str,
        session: AsyncSession,
    ) -> tuple[CollectionModel, list[str], list[NoteModel]]:
        """Return (collection, collection_path, notes_in_collection_and_children)."""
        col = (
            await session.execute(
                select(CollectionModel).where(CollectionModel.id == collection_id)
            )
        ).scalar_one_or_none()
        if col is None:
            raise ValueError(f"Collection not found: {collection_id}")

        # Build collection path list (parent name / child name)
        if col.parent_collection_id:
            parent = (
                await session.execute(
                    select(CollectionModel).where(CollectionModel.id == col.parent_collection_id)
                )
            ).scalar_one_or_none()
            collection_path = [parent.name if parent else "", col.name]
        else:
            collection_path = [col.name]

        # Gather all relevant collection_ids: the collection itself + child collections
        child_ids_result = await session.execute(
            select(CollectionModel.id).where(CollectionModel.parent_collection_id == collection_id)
        )
        child_ids = [row[0] for row in child_ids_result.all()]
        all_collection_ids = [collection_id, *child_ids]

        # Load all note_ids in these collections
        member_rows = (
            await session.execute(
                select(CollectionMemberModel.member_id).where(
                    CollectionMemberModel.collection_id.in_(all_collection_ids),
                    CollectionMemberModel.member_type == "note",
                )
            )
        ).all()
        note_ids = list({row[0] for row in member_rows})

        if not note_ids:
            return col, collection_path, []

        notes = list(
            (await session.execute(select(NoteModel).where(NoteModel.id.in_(note_ids))))
            .scalars()
            .all()
        )
        return col, collection_path, notes

    async def export_collection_markdown(
        self,
        collection_id: str,
        session: AsyncSession,
    ) -> bytes:
        """Return a zip archive of .md files for all notes in the collection.

        Each file has YAML frontmatter and Obsidian [[title]] wikilinks.
        """
        col, collection_path, notes = await self._fetch_collection_notes(collection_id, session)

        # Batch-fetch document titles for notes that have a document_id
        doc_ids = list({n.document_id for n in notes if n.document_id})
        doc_title_map: dict[str, str] = {}
        if doc_ids:
            doc_rows = (
                await session.execute(
                    select(DocumentModel.id, DocumentModel.title).where(
                        DocumentModel.id.in_(doc_ids)
                    )
                )
            ).all()
            doc_title_map = {row[0]: row[1] for row in doc_rows}

        # Build id -> title map for wikilink resolution
        id_to_title: dict[str, str] = {n.id: _note_title(n) for n in notes}

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            used_filenames: set[str] = set()
            for note in notes:
                doc_title = doc_title_map.get(note.document_id) if note.document_id else None
                frontmatter = _build_yaml_frontmatter(note, collection_path, doc_title)
                body = _resolve_links(note.content, id_to_title)
                md_content = f"{frontmatter}\n\n{body}"

                # Build unique filename
                title_slug = _slugify(_note_title(note))
                base_name = f"{note.id[:8]}-{title_slug}.md"
                filename = base_name
                counter = 1
                while filename in used_filenames:
                    filename = f"{note.id[:8]}-{title_slug}-{counter}.md"
                    counter += 1
                used_filenames.add(filename)

                zf.writestr(filename, md_content)

        return buf.getvalue()

    async def export_collection_anki(
        self,
        collection_id: str,
        session: AsyncSession,
    ) -> tuple[bytes, int]:
        """Return (apkg_bytes, card_count) for all flashcards in the collection's deck.

        card_count == 0 means no flashcards exist (caller should warn user).
        The .apkg is always a valid zip even when empty.
        """
        col = (
            await session.execute(
                select(CollectionModel).where(CollectionModel.id == collection_id)
            )
        ).scalar_one_or_none()
        if col is None:
            raise ValueError(f"Collection not found: {collection_id}")

        # Fetch flashcards where deck matches the collection name
        cards = list(
            (await session.execute(select(FlashcardModel).where(FlashcardModel.deck == col.name)))
            .scalars()
            .all()
        )

        # Build a stable deck_id from the collection name hash
        deck_id = int(hashlib.sha256(col.name.encode()).hexdigest()[:8], 16)
        deck = genanki.Deck(deck_id, col.name)
        for card in cards:
            deck.add_note(
                genanki.Note(
                    model=_ANKI_MODEL,
                    fields=[card.question, card.answer],
                )
            )

        package = genanki.Package(deck)
        buf = io.BytesIO()
        package.write_to_file(buf)
        return buf.getvalue(), len(cards)


_export_service: ExportService | None = None


def get_export_service() -> ExportService:
    global _export_service
    if _export_service is None:
        _export_service = ExportService()
    return _export_service
