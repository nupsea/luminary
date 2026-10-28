"""Re-embed every vector table of a library from its database, resumably (#390).

Vectors are derived. Chunks, notes and image descriptions are embedded again from the text
the database holds, and a concept's vector is the centroid of its evidence chunks
(docs/concepts.md). The rebuild writes a folder beside the live one a fixed page at a time,
so a killed run resumes where it stopped and embeds the same pages a clean run would. When
every table holds what the database does, the new folder replaces the live one, which is kept
as `vectors.previous`. Run with the app stopped: a vector it writes meanwhile refuses the swap.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.database import get_session_factory
from app.exceptions import Conflict
from app.repos.concept_repo import ConceptRepo
from app.repos.document_repo import DocumentRepo
from app.repos.image_repo import ImageRepo
from app.repos.note_repo import NoteRepo
from app.services.embedder import chunk_embedding_text, get_embedding_service
from app.services.library_snapshot import EMBEDDER
from app.services.vector_store import (
    CONCEPT_TABLE_NAME,
    IMAGE_TABLE_NAME,
    NOTE_TABLE_NAME,
    TABLE_NAME,
    TABLES,
    LanceDBService,
    get_lancedb_service,
    lancedb_service_beside,
)
from app.storage import library_root

logger = logging.getLogger(__name__)

LIVE = "vectors"
NEXT = "vectors.next"
PREVIOUS = "vectors.previous"
STATE = "reembed.json"
PAGE = 256

# (key, text to embed, the row's other fields)
Item = tuple[str, str, dict[str, Any]]


@dataclass
class ReembedReport:
    rows: dict[str, int] = field(default_factory=dict)
    # Rows this run wrote: fewer than `rows` when it resumed an earlier run.
    written: dict[str, int] = field(default_factory=dict)
    previous: str = ""


async def reembed() -> ReembedReport:
    """Rebuild the current library's vectors from its database and swap them in."""
    root = library_root()
    state = _read_state(root)
    if state.get("verified") and not (root / LIVE).exists():
        # Stopped between the two renames: the rebuild was already verified.
        return _swap(root, ReembedReport(rows=state["rows"]))
    if (root / PREVIOUS).exists():
        raise Conflict(f"{root / PREVIOUS} is left from an earlier re-embed; remove it first")
    if (root / NEXT).exists() and state.get("embedder") != EMBEDDER:
        raise Conflict(
            f"{root / NEXT} was not built with {EMBEDDER}; remove it to re-embed from the start"
        )
    async with get_session_factory()() as session:
        ingesting = await DocumentRepo(session).ingesting_count()
    if ingesting:
        raise Conflict(f"{ingesting} document(s) are still being ingested; re-embed after")

    live = get_lancedb_service()
    before = await asyncio.to_thread(live.table_versions)
    written = state.get("pages", {}) if (root / NEXT).exists() else {}
    progress = {"embedder": EMBEDDER, "verified": False, "pages": written}
    _write_state(root, progress)
    target = lancedb_service_beside(NEXT)
    report = ReembedReport()
    for table, pages in (
        (TABLE_NAME, _chunk_pages),
        (NOTE_TABLE_NAME, _note_pages),
        (IMAGE_TABLE_NAME, _image_pages),
    ):
        await _rebuild(target, table, pages, report, progress)
    await _rebuild_concepts(target, report)
    await asyncio.to_thread(target.compact)
    del target

    if await asyncio.to_thread(live.table_versions) != before:
        raise Conflict(
            "the app wrote vectors while the re-embed ran; stop it and run again to resume"
        )
    _write_state(root, {"embedder": EMBEDDER, "verified": True, "rows": report.rows})
    return _swap(root, report)


async def _rebuild(
    target: LanceDBService,
    table: str,
    pages: Callable[[], AsyncIterator[list[Item]]],
    report: ReembedReport,
    progress: dict[str, Any],
) -> None:
    key = TABLES[table][0]
    have = await asyncio.to_thread(target.keys, table)
    done = progress["pages"].setdefault(table, [])
    embedder = get_embedding_service()
    seen: set[str] = set()
    written = 0
    async for page in pages():
        seen.update(k for k, _, _ in page)
        # A page is kept only as the batch it was written in: a vector depends on its batch in
        # the last bits, so a page shifted by a deletion, or with a changed row, is encoded again.
        digest = hashlib.sha256(json.dumps(page, sort_keys=True).encode()).hexdigest()
        if digest in done:
            continue
        vectors = await asyncio.to_thread(embedder.encode, [text for _, text, _ in page])
        rows = [
            {key: k, **fields, "vector": vector}
            for (k, _, fields), vector in zip(page, vectors, strict=True)
        ]
        await asyncio.to_thread(target.upsert_rows, table, rows)
        done.append(digest)
        _write_state(library_root(), progress)
        written += len(rows)
        logger.info("re-embed %s: %d rows seen, %d written", table, len(seen), written)
    await _settle(target, table, have - seen, seen, written, report)


async def _rebuild_concepts(target: LanceDBService, report: ReembedReport) -> None:
    async with get_session_factory()() as session:
        evidence = await ConceptRepo(session).all_evidence()
    rows = []
    for concept_id, items in evidence:
        chunk_ids = _evidence_chunks(items)
        centroid = await asyncio.to_thread(target.compute_centroid, chunk_ids)
        if centroid is not None:
            rows.append({"concept_id": concept_id, "vector": centroid})
    have = await asyncio.to_thread(target.keys, CONCEPT_TABLE_NAME)
    for i in range(0, len(rows), PAGE):
        await asyncio.to_thread(target.upsert_rows, CONCEPT_TABLE_NAME, rows[i : i + PAGE])
    seen = {r["concept_id"] for r in rows}
    await _settle(target, CONCEPT_TABLE_NAME, have - seen, seen, len(rows), report)


def _evidence_chunks(items: list) -> list[str]:
    # Concept generation writes `chunk_ids`; a concept made by hand carries one `chunk_id`.
    ids: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            ids.update(item.get("chunk_ids") or [])
            if item.get("chunk_id"):
                ids.add(item["chunk_id"])
    return sorted(ids)


async def _settle(
    target: LanceDBService,
    table: str,
    stale: set[str],
    seen: set[str],
    written: int,
    report: ReembedReport,
) -> None:
    """Drop what the database no longer holds, then check the table holds exactly the rest."""
    if stale:
        await asyncio.to_thread(target.delete_keys, table, sorted(stale))
    held = await asyncio.to_thread(target.keys, table)
    if held != seen:
        raise Conflict(f"rebuilt {table} holds {len(held)} rows, the database {len(seen)}")
    report.rows[table] = len(held)
    report.written[table] = written


async def _chunk_pages() -> AsyncIterator[list[Item]]:
    after = ""
    while True:
        async with get_session_factory()() as session:
            rows = await DocumentRepo(session).chunks_after(after, PAGE)
        if not rows:
            return
        # The row embed_node writes.
        yield [
            (
                chunk_id,
                chunk_embedding_text(text, entities_text),
                {
                    "document_id": document_id,
                    "section_heading": "",
                    "page": 0,
                    "chunk_index": index,
                    "speaker": "",
                    "text": text,
                },
            )
            for chunk_id, document_id, text, entities_text, index in rows
        ]
        after = rows[-1][0]


async def _note_pages() -> AsyncIterator[list[Item]]:
    async with get_session_factory()() as session:
        notes = sorted(await NoteRepo(session).contents_with_documents())
    items = [
        (note_id, content, {"document_id": document_id or "", "content": content})
        for note_id, content, document_id in notes
    ]
    for i in range(0, len(items), PAGE):
        yield items[i : i + PAGE]


async def _image_pages() -> AsyncIterator[list[Item]]:
    async with get_session_factory()() as session:
        images = await ImageRepo(session).all_descriptions()
    items = [
        (image_id, description, {"document_id": document_id, "description": description})
        for image_id, document_id, description in images
    ]
    for i in range(0, len(items), PAGE):
        yield items[i : i + PAGE]


def _swap(root: Path, report: ReembedReport) -> ReembedReport:
    live, previous = root / LIVE, root / PREVIOUS
    if live.exists():
        live.rename(previous)
    (root / NEXT).rename(live)
    (root / STATE).unlink()
    report.previous = str(previous) if previous.exists() else ""
    return report


def _read_state(root: Path) -> dict[str, Any]:
    path = root / STATE
    return json.loads(path.read_text()) if path.exists() else {}


def _write_state(root: Path, state: dict[str, Any]) -> None:
    tmp = root / f"{STATE}.tmp"
    tmp.write_text(json.dumps(state))
    tmp.replace(root / STATE)
