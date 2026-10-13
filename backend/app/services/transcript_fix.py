"""The learner's own transcript fixes and the vocabulary they keep for every import."""

import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import Conflict, InvalidInput
from app.repos.transcript_repo import TranscriptRepo
from app.services.transcript_correction import normalize_terms, replace_heard
from app.types import PREVIEW_CHARS

# A document mid-ingest is still writing the rows a fix rewrites.
_SETTLED_STAGES = {"complete", "enriching"}


@dataclass(frozen=True)
class FixResult:
    occurrences: int
    chunks: int
    sections: int
    vocabulary_added: bool


async def personal_vocabulary(session: AsyncSession) -> list[str]:
    return await TranscriptRepo(session).personal_vocabulary()


async def set_personal_vocabulary(session: AsyncSession, terms: list[str]) -> list[str]:
    repo = TranscriptRepo(session)
    kept = normalize_terms(terms)
    await repo.set_personal_vocabulary(kept)
    await repo.commit()
    return kept


def _record(corrections: list[dict] | None, heard: str, term: str, count: int) -> list[dict]:
    kept = [
        c
        for c in corrections or []
        if not (c.get("source") == "user" and c.get("heard", "").casefold() == heard.casefold())
    ]
    return [*kept, {"heard": heard, "term": term, "source": "user", "count": count}]


async def _reembed(chunks: list) -> None:
    from app.services.embedder import get_embedding_service  # noqa: PLC0415
    from app.services.vector_store import get_lancedb_service  # noqa: PLC0415

    # Embedded as embed_node does: display text plus the entity tail.
    texts = [c.text + ("\n" + c.entities_text if c.entities_text else "") for c in chunks]
    vectors = await asyncio.to_thread(get_embedding_service().encode, texts)
    updates = {c.id: (c.text, vectors[i]) for i, c in enumerate(chunks)}
    await asyncio.to_thread(get_lancedb_service().replace_chunk_text, updates)


def _validated(doc, heard: str, term: str) -> None:
    if not heard or not term or heard == term:
        raise InvalidInput("Give the words as transcribed and a different correction.")
    # Transcription sets the duration on every recording, imported before this or not.
    if doc.audio_duration_seconds is None:
        raise InvalidInput("Only a transcript can be corrected this way.")
    if doc.stage not in _SETTLED_STAGES:
        raise Conflict("This document is still being imported; correct it once it finishes.")


async def _rewrite(repo: TranscriptRepo, document_id: str, heard: str, term: str):
    """(occurrences, changed chunks, changed sections), with the rows edited in session."""
    occurrences, changed = 0, []
    for chunk in await repo.chunks(document_id):
        chunk.text, n = replace_heard(chunk.text, heard, term)
        if n:
            occurrences += n
            changed.append(chunk)
    sections = 0
    for section in await repo.sections(document_id):
        body, n = replace_heard(section.body or "", heard, term)
        if n:
            section.body, section.preview = body, body[:PREVIEW_CHARS]
            sections += 1
    return occurrences, changed, sections


async def _remember(repo: TranscriptRepo, term: str) -> bool:
    current = await repo.personal_vocabulary()
    await repo.set_personal_vocabulary(normalize_terms([*current, term]))
    return term.casefold() not in {t.casefold() for t in current}


async def fix_term(
    session: AsyncSession, document_id: str, heard: str, term: str, *, remember: bool
) -> FixResult:
    """Replace `heard` with `term` throughout a transcript and every index built from it.

    Recorded on the document so a re-import applies it again. Summaries and cards
    already written from the old text are not rewritten.
    """
    heard, term = " ".join(heard.split()), " ".join(term.split())
    repo = TranscriptRepo(session)
    doc = await repo.document(document_id)
    _validated(doc, heard, term)
    occurrences, changed, sections = await _rewrite(repo, document_id, heard, term)
    if not occurrences and not sections:
        return FixResult(0, 0, 0, False)

    doc.transcript_corrections = _record(doc.transcript_corrections, heard, term, occurrences)
    added = await _remember(repo, term) if remember else False
    await repo.commit()
    await repo.reindex_keywords(document_id)
    await repo.commit()
    if changed:
        await _reembed(changed)
    return FixResult(occurrences, len(changed), sections, added)
