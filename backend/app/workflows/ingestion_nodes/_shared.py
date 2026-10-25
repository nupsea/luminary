"""Shared types + foundation helpers for ingestion nodes.

Holds the cross-node infrastructure that several nodes import:
- `IngestionState` TypedDict (the StateGraph state shape)
- `ENTITY_TAIL_MAX` + `build_entity_tail`
- `STAGE_PROGRESS` map
- `_update_stage` async helper that writes the document's stage column
- `_parser` shared `DocumentParser` instance
- `_background_tasks` set for fire-and-forget tasks

Re-exported from `app.workflows.ingestion` for back-compat with
existing test imports.
"""

import logging
from typing import Any, TypedDict

from app.database import get_session_factory
from app.repos.document_repo import DocumentRepo
from app.services.background import task_registry
from app.services.llm_admission import awaited
from app.services.parser import DocumentParser
from app.types import FACETS_FROM_READER, MEDIA_FORMATS, UNCLASSIFIED_FORM, DocumentProfile

# Module-level set holding fire-and-forget background tasks (objective
# extraction, pregenerate, etc.). All ingestion nodes share this so the
# tasks aren't garbage-collected mid-execution. Each task should add
# `_background_tasks.discard` as a done-callback so finished tasks don't
# accumulate.

_background_tasks = task_registry(__name__)

logger = logging.getLogger(__name__)


_parser = DocumentParser()

# cap on canonical entities included in a chunk's entity tail.
# Bounds embedding distortion and BM25 dilution from very entity-dense chunks.
ENTITY_TAIL_MAX = 12


def build_entity_tail(canonical_names: set[str] | list[str] | tuple[str, ...]) -> str:
    """Build the deterministic entity tail '[Entities: A, B, C]' for a chunk.

    Rules per AC: dedupe (case-insensitive on the canonical key), sort
    alphabetically (case-insensitive), capitalize each label, cap at
    ENTITY_TAIL_MAX entries. Returns '' for empty input so callers can store
    NULL when there are no entities.
    """
    if not canonical_names:
        return ""
    seen: dict[str, str] = {}
    for raw in canonical_names:
        if not isinstance(raw, str):
            continue
        name = raw.strip()
        if not name:
            continue
        key = name.casefold()
        if key not in seen:
            seen[key] = name
    if not seen:
        return ""
    ordered = sorted(seen.values(), key=lambda s: s.casefold())[:ENTITY_TAIL_MAX]
    capitalized = [
        " ".join(part[:1].upper() + part[1:] if part else part for part in label.split(" "))
        for label in ordered
    ]
    return f"[Entities: {', '.join(capitalized)}]"


STAGE_PROGRESS: dict[str, int] = {
    "downloading": 2,
    "parsing": 10,
    "transcribing": 15,
    "correcting": 32,
    "classifying": 25,
    "chunking": 40,
    "entity_extract": 60,
    "embedding": 70,
    "indexing": 80,
    "summarizing": 85,
    "enriching": 95,
    "complete": 100,
    "error": 0,
}

# Where a stage that reports its own progress hands over. Correction ends at
# chunking, not at "classifying": classify runs before transcription and writes no stage.
_STAGE_END: dict[str, int] = {"downloading": 10, "transcribing": 32, "correcting": 40}


def stage_progress_pct(stage: str, fraction: float | None) -> int:
    start = STAGE_PROGRESS.get(stage, 0)
    end = _STAGE_END.get(stage)
    if fraction is None or end is None:
        return start
    return start + int(fraction * (end - start))


class IngestionState(TypedDict):
    document_id: str
    file_path: str
    format: str
    parsed_document: dict[str, Any] | None
    # The kind chosen at upload; classify_node lays its facets over the measured shape.
    kind: str | None
    chunks: list[dict[str, Any]] | None
    status: str
    error: str | None
    section_summary_count: int | None
    audio_duration_seconds: float | None
    form: str | None
    domain: str | None
    structure_type: str | None
    defer_section_summaries: bool | None
    _audio_chunks: list[dict[str, Any]] | None


def profile_of_state(state: IngestionState) -> DocumentProfile:
    """`DocumentProfile.of` mid-ingest: the measured facets are in the state, not yet the row.

    Media is turns until its transcript says otherwise; classify_node measures nothing for it.
    """
    form = state.get("form")
    if form is None:
        form = "dialogue" if state.get("format") in MEDIA_FORMATS else UNCLASSIFIED_FORM
    return DocumentProfile(form=form, domain=state.get("domain"))


async def _update_stage(document_id: str, stage: str) -> None:
    async with get_session_factory()() as session:
        await DocumentRepo(session).update_fields(document_id, stage=stage)
        await session.commit()


async def detect_technical_content(raw_text: str) -> bool | None:
    """Ask the LLM whether a document's subject is technical. None when undecided.

    Read from the document, never inferred from its type: the list this replaced
    wrote a hard False for every paper and book, which stripped the technical
    entity types from "Attention Is All You Need" (70 entities, 0 technical).

    Vocabulary density cannot stand in for it. `_TECH_VOCAB` is ordinary
    computing vocabulary, so it reads an astronomy paper at 1.91 and a LaTeX
    symbol table at 0.89, below a CS blog post at 2.20.

    None on failure, never False -- an unanswered probe is not a finding.
    `scripts/remeasure_domain.py` retries those.

    Two named labels, not yes/no: on qwen3.5:4b the yes/no form called Sherlock
    Holmes, the Federalist Papers and the Gita technical (#381). Tuned on 5
    documents, one per kind; 58/58 on the 58 held out, against 54/58 before.
    """
    from app.services.content_classifier import subject_excerpt  # noqa: PLC0415
    from app.services.llm import get_llm_service  # noqa: PLC0415

    # The opening of the work, falling back to the body when the opening is a
    # contents listing. See `subject_excerpt` for why each half is needed: the
    # opening wins on talks, and the fallback is what stops a chapter's table of
    # contents deciding the subject of the chapter.
    snippet = subject_excerpt(raw_text)
    if not snippet:
        return None
    # Examples, not a closed list, on the technical side: a closed list decides
    # against every discipline it omits, invisibly, until a document from one arrives.
    prompt = (
        "What is the subject matter of this text? Answer `technical` if it is about "
        "software, engineering, mathematics, medicine, or another technical or "
        "scientific discipline. Answer `general` if it is literature, fiction, poetry, "
        "drama, history, politics, philosophy, religion, personal writing, or general "
        "interest.\n\n"
        f"Excerpt:\n{snippet}\n\n"
        "Reply with exactly one word: technical or general."
    )
    try:
        with awaited():
            raw = await get_llm_service().generate(prompt, background=True, temperature=0)
    except Exception as exc:
        logger.warning("domain detection failed (non-fatal): %s", exc)
        return None
    answer = str(raw).strip().strip("`*.").lower()
    if answer.startswith("technical"):
        return True
    if answer.startswith("general"):
        return False
    return None


async def measure_domain(form: str | None, raw_text: str) -> bool | None:
    """Whether a document's subject is technical: settled by source code, otherwise asked.

    Never from the legacy type. `tech_book` once settled it unasked, and the
    Federalist Papers uploaded as one stayed technical.
    """
    if form == "source_code":
        return True
    return await detect_technical_content(raw_text) if raw_text.strip() else None


# Kept: transcribe_node imported this name before the probe was generalised.
detect_technical_transcript = detect_technical_content


# Mid-body: a Gutenberg novel still opens on a preface after its licence is stripped.
_REGISTER_WINDOWS = (0.30, 0.50, 0.70)
_REGISTER_WINDOW_CHARS = 2000


async def detect_register(raw_text: str) -> str | None:
    """Whether the text tells a story or explains a subject. None when undecided.

    Read from the text: a story and an essay share their vocabulary, and what
    differs is what the sentences are doing, so no word list can carry it.

    A majority of separately judged body windows, at temperature 0 (#286). One
    sample decided the whole book, and a reflective passage in "The Fall of the
    House of Usher" read it as expository on 3 of 4 runs. Stops once two windows
    agree, so a consistent book costs two calls and a mixed one three.
    """
    from app.services.content_classifier import body_windows  # noqa: PLC0415

    windows = [w for w in body_windows(raw_text, _REGISTER_WINDOWS, _REGISTER_WINDOW_CHARS) if w]
    need = len(windows) // 2 + 1
    votes: list[str | None] = []
    for snippet in windows:
        votes.append(await _judge_register(snippet))
        for register in ("narrative", "expository"):
            if votes.count(register) >= need:
                logger.info("register %s by votes %s", register, votes)
                return register
    logger.info("register undecided by votes %s", votes)
    return None


async def _judge_register(snippet: str) -> str | None:
    from app.services.llm import get_llm_service  # noqa: PLC0415

    prompt = (
        "Does this text mainly tell a story, or mainly explain a subject?\n\n"
        f"Excerpt:\n{snippet}\n\n"
        "Reply with exactly one word: story or explain."
    )
    try:
        with awaited():
            raw = await get_llm_service().generate(prompt, background=True, temperature=0)
    except Exception as exc:
        logger.warning("register detection failed (non-fatal): %s", exc)
        return None
    answer = str(raw).strip().lower()
    if answer.startswith("story"):
        return "narrative"
    if answer.startswith("explain"):
        return "expository"
    return None


async def _persist_extraction_report(document_id: str, report: dict | None) -> None:
    """Store what the importer captured and what it could not.

    Null on the column means "fidelity was never measured", which is not the
    same as a clean import -- so the ingest path only writes when a parser
    actually measured. A re-import writes whatever it measured including None,
    because the stored report has to describe the import that is in the
    database, not the one it replaced.
    """
    async with get_session_factory()() as session:
        await DocumentRepo(session).update_fields(document_id, extraction_report=report)
        await session.commit()


async def _persist_structure_type(document_id: str, structure_type: str) -> None:
    """Write the layout the parser discovered ('book'|'paper'|'script'|'chat')."""
    async with get_session_factory()() as session:
        await DocumentRepo(session).update_fields(document_id, structure_type=structure_type)
        await session.commit()


async def _persist_classification(
    document_id: str, form: str, domain: str | None, register: str | None = None
) -> None:
    """Write the measured facets in one statement.

    A null domain is written as measured: an unanswered question is not "general".
    `register` is only written when supplied, so a pass that cannot measure it
    does not wipe one measured before.
    """
    values: dict[str, object] = {"form": form, "domain": domain}
    if register is not None:
        values["register"] = register
    async with get_session_factory()() as session:
        repo = DocumentRepo(session)
        if await reader_facets(repo, document_id) is not None:
            # A kind the reader chose outranks a measurement (#223).
            for key in ("form", "domain"):
                values.pop(key)
        await repo.update_fields(document_id, **values)
        await session.commit()


async def reader_facets(repo: DocumentRepo, document_id: str) -> tuple[str, str | None] | None:
    """(form, domain) when a reader chose this document's kind, else None."""
    doc = await repo.get(document_id)
    if doc is None or doc.facets_source != FACETS_FROM_READER or not doc.form:
        return None
    return doc.form, doc.domain
