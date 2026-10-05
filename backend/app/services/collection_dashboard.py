"""The study dashboard for one collection: its whole subtree rolled up.

A fixed number of queries whatever the tree's depth or tag count: the tree is
loaded once and walked in Python, and card counts come from grouped aggregates.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repos.collection_repo import CollectionRepo
from app.repos.document_repo import DocumentRepo
from app.repos.flashcard_repo import FlashcardRepo
from app.repos.note_repo import NoteRepo
from app.schemas.study import (
    CollectionSource,
    CollectionSubCollection,
    CollectionTopic,
    StudyCollectionDashboardResponse,
)
from app.services.documents_service import safe_tags

# FSRS stability, in days, past which a card counts as mastered.
_MASTERED_STABILITY = 30.0
_TOP_TOPICS = 10
# Notes are weighed in chunk-equivalents so they share a unit with documents.
_CHARS_PER_CHUNK = 1500


@dataclass
class _Members:
    document_ids: set[str]
    note_ids: set[str]


def _descendants(children_of: dict[str | None, list[str]], root: str) -> set[str]:
    out = {root}
    stack = [root]
    while stack:
        for child in children_of.get(stack.pop(), ()):
            if child not in out:
                out.add(child)
                stack.append(child)
    return out


def _bucket(rows: list[tuple[str, str, str]], collection_ids: set[str]) -> _Members:
    members = _Members(set(), set())
    for coll_id, member_id, kind in rows:
        if coll_id not in collection_ids:
            continue
        if kind == "document":
            members.document_ids.add(member_id)
        elif kind == "note":
            members.note_ids.add(member_id)
    return members


def _card_total(
    members: _Members, cards_per_doc: dict[str, int], cards_per_note: dict[str, int]
) -> int:
    return sum(cards_per_doc.get(d, 0) for d in members.document_ids) + sum(
        cards_per_note.get(n, 0) for n in members.note_ids
    )


async def _topics(
    session: AsyncSession,
    members: _Members,
    cards_per_doc: dict[str, int],
    cards_per_note: dict[str, int],
) -> list[CollectionTopic]:
    by_tag: dict[str, _Members] = defaultdict(lambda: _Members(set(), set()))
    for doc_id, tags in await DocumentRepo(session).tags_by_id(list(members.document_ids)):
        for tag in safe_tags(tags):
            by_tag[tag].document_ids.add(doc_id)
    for tag, note_id in await NoteRepo(session).tag_pairs(list(members.note_ids)):
        by_tag[tag].note_ids.add(note_id)

    topics = [
        CollectionTopic(
            tag=tag,
            card_count=_card_total(tagged, cards_per_doc, cards_per_note),
            note_count=len(tagged.note_ids),
        )
        for tag, tagged in by_tag.items()
    ]
    topics = [t for t in topics if t.card_count > 0 or t.note_count > 0]
    topics.sort(key=lambda t: (t.card_count, t.note_count), reverse=True)
    return topics[:_TOP_TOPICS]


async def _sources(session: AsyncSession, members: _Members) -> list[CollectionSource]:
    sources = [
        CollectionSource(id=doc_id, title=title, type="document", weight=chunks)
        for doc_id, title, chunks in await DocumentRepo(session).titles_with_chunk_counts(
            list(members.document_ids)
        )
    ]
    for note_id, snippet, chars in await NoteRepo(session).snippets(list(members.note_ids), 120):
        title = snippet.split("\n")[0][:60] or "Untitled Note"
        weight = max(1, chars // _CHARS_PER_CHUNK) if chars else 0
        sources.append(CollectionSource(id=note_id, title=title, type="note", weight=weight))
    return sources


async def collection_dashboard(
    session: AsyncSession, collection_id: str
) -> StudyCollectionDashboardResponse:
    collections = CollectionRepo(session)
    collection = await collections.get_or_404(collection_id)

    children_of: dict[str | None, list[str]] = defaultdict(list)
    for cid, parent_id in await collections.parent_links():
        children_of[parent_id].append(cid)
    subtree = _descendants(children_of, collection_id)
    direct_children = children_of.get(collection_id, [])

    rows = await collections.memberships(list(subtree))
    members = _bucket(rows, subtree)

    cards = FlashcardRepo(session)
    total, due, new, mastered = await cards.scope_stats(
        list(members.document_ids), list(members.note_ids), mastered_above=_MASTERED_STABILITY
    )
    cards_per_doc = await cards.counts_by_document(list(members.document_ids))
    cards_per_note = await cards.counts_by_note(list(members.note_ids))

    child_names = await collections.names(direct_children)
    sub_collections = [
        CollectionSubCollection(
            id=child_id,
            name=child_names.get(child_id, ""),
            card_count=_card_total(
                _bucket(rows, _descendants(children_of, child_id)), cards_per_doc, cards_per_note
            ),
        )
        for child_id in direct_children
    ]

    return StudyCollectionDashboardResponse(
        collection_id=collection_id,
        collection_name=collection.name,
        due_today=due,
        new_today=new,
        mastery_pct=round(mastered / total * 100, 1) if total else 0.0,
        topics=await _topics(session, members, cards_per_doc, cards_per_note),
        sources=await _sources(session, members),
        sub_collections=sub_collections,
    )
