"""Shared types + foundation helpers for ingestion nodes.

Holds the cross-node infrastructure that several nodes import:
- `IngestionState` TypedDict (the StateGraph state shape)
- `ContentType` literal
- `CHUNK_CONFIGS` per-content-type chunker settings
- `ENTITY_TAIL_MAX` + `build_entity_tail`
- `STAGE_PROGRESS` map
- `_classify` heuristic that picks the content type
- `_update_stage` async helper that writes the document's stage column
- `_parser` shared `DocumentParser` instance
- `_background_tasks` set for fire-and-forget tasks

Re-exported from `app.workflows.ingestion` for back-compat with
existing test imports.
"""

import asyncio
import logging
from typing import Any, TypedDict

from app.database import get_session_factory
from app.services.parser import DocumentParser
from app.types import ContentType  # noqa: F401  re-exported via app.workflows.ingestion

# Module-level set holding fire-and-forget background tasks (objective
# extraction, pregenerate, etc.). All ingestion nodes share this so the
# tasks aren't garbage-collected mid-execution. Each task should add
# `_background_tasks.discard` as a done-callback so finished tasks don't
# accumulate.
_background_tasks: set[asyncio.Task] = set()

logger = logging.getLogger(__name__)



_parser = DocumentParser()

# No longer read by the chunkers -- `DocumentProfile.chunk_config` decides
# sizing now. Kept as the pinned record of what each content type used to get,
# and `tests/test_document_profile.py` asserts the profile still reproduces it.
# Deleting this as dead code would silently void that comparison. It goes when
# content_type does.
CHUNK_CONFIGS: dict[str, dict[str, int]] = {
    # Papers are the densest content type and previously had the smallest budget,
    # tight enough that splits fell past word boundaries into mid-word cuts. The
    # chunk embedder (bge-small-en-v1.5) carries 512 tokens (~2000 chars), so this
    # still leaves headroom.
    "paper": {"chunk_size": 900, "chunk_overlap": 150},
    "book": {"chunk_size": 600, "chunk_overlap": 120},
    "conversation": {"chunk_size": 450, "chunk_overlap": 90},
    "notes": {"chunk_size": 300, "chunk_overlap": 75},
    "code": {"chunk_size": 300, "chunk_overlap": 75},
    "tech_book": {"chunk_size": 500, "chunk_overlap": 80},
    "tech_article": {"chunk_size": 350, "chunk_overlap": 60},
    "epub": {"chunk_size": 600, "chunk_overlap": 120},
    "kindle_clippings": {"chunk_size": 300, "chunk_overlap": 75},
}

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
    "parsing": 10,
    "transcribing": 15,
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


class IngestionState(TypedDict):
    document_id: str
    file_path: str
    format: str
    parsed_document: dict[str, Any] | None
    content_type: str | None
    chunks: list[dict[str, Any]] | None
    status: str
    error: str | None
    section_summary_count: int | None
    audio_duration_seconds: float | None
    is_technical: bool | None
    structure_type: str | None
    defer_section_summaries: bool | None
    _audio_chunks: list[dict[str, Any]] | None


def resolve_technical_variant(raw_text: str, word_count: int | None = None) -> str:
    """Resolve the merged 'technical' upload choice into the sizing variant
    the chunker expects. The two variants share every other pipeline branch.

    Length decides it, because the choice is a chunk size and nothing else.
    Structure overrides length only for a short document that is plainly a
    manual. Each threshold is bracketed by the two library documents that
    decide it:

    - 5,000 words: `luminary_conceptual_foundations` at 5,312 is a book,
      `radiology_chexnet_cxr` at 3,764 is a paper.
    - 8 sections: below the length gate, `radiology_chexnet_cxr` is the only
      document with any numbered sections at all, at 6 -- and it must stay an
      article, so a threshold of 3 would misfile it.
    - 6 fence lines (3 blocks): keeps the previous rule's fence intent.
      `retrieval-and-memory-tutorial` at 4,920 words and 26 fences is a book;
      `Introducing Contextual Retrieval` at 4 fences is not.

    The previous rule read the first 5,000 characters and never looked at
    length. On a book that window is the title page and the table of contents,
    which is the same defect `classify_content` was rewritten to remove: it put
    a 120,000-word IAEA manual and `d2l_dive_into_deep_learning` in the article
    bucket, and a 3,764-word paper in the book one.
    """
    from app.services.content_classifier import (  # noqa: PLC0415
        _CODE_FENCE,
        count_numbered_sections,
        strip_boilerplate,
    )

    body = strip_boilerplate(raw_text)
    words = word_count if word_count is not None else len(body.split())
    if words >= 5000 or len(_CODE_FENCE.findall(body)) >= 6 or count_numbered_sections(body) >= 8:
        return "tech_book"
    return "tech_article"


def _classify(
    raw_text: str, sections: list[dict], word_count: int, file_ext: str, filename: str = ""
) -> str:
    """Deprecated alias for `classify_content`, kept for existing importers.

    The rules that used to live here scored 4 of 13 on the repo's own corpus:
    they read the first 5,000 characters (a Gutenberg licence, not the book),
    matched single words anywhere, and returned on the first hit so ordering
    decided the answer. `app.services.content_classifier` replaces them and
    scores 13 of 13 against `tests/fixtures/content_type_labels.json`.
    """
    from app.services.content_classifier import classify_content  # noqa: PLC0415

    return classify_content(raw_text, sections, word_count, file_ext, filename)


async def _update_stage(document_id: str, stage: str) -> None:
    from sqlalchemy import update  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415

    async with get_session_factory()() as session:
        await session.execute(
            update(DocumentModel).where(DocumentModel.id == document_id).values(stage=stage)
        )
        await session.commit()


async def detect_technical_content(raw_text: str) -> bool | None:
    """Ask the LLM whether a document's subject is technical. None when undecided.

    **The domain has to be read from the document, not inferred from its type.**
    The type list this replaced (`content_type in TECHNICAL_CONTENT_TYPES`) wrote
    a hard False for every paper and book, so "Attention Is All You Need" was
    recorded as non-technical and lost every ALGORITHM, TECHNOLOGY and PROTOCOL
    entity it should have had -- 70 entities extracted, 0 technical. So did
    `d2l_dive_into_deep_learning`, at 165 and 0.

    A vocabulary-density heuristic cannot stand in for this. `_TECH_VOCAB` is
    ordinary computing vocabulary, so it reads an astronomy paper at 1.91 and a
    LaTeX symbol table at 0.89 -- below a threshold that a CS blog post clears at
    2.20. Any density floor that admits the blog post excludes the physics.

    None on failure, never False: an unanswered probe is not a finding, and
    `DocumentProfile` shows it as unclassified rather than as "general".
    Re-runnable by `scripts/remeasure_domain.py`.

    Repeats identically across five runs on the same input. Four framings were
    measured against hand labels; this one scores 22/23 and the others were
    rejected on the numbers, not on taste:

        open category + examples + exclusions   22/23   (this one)
        closed list of fields                   18/19
        contrast with no examples               17/19
        naming what the flag gates              14/22

    The last collapsed because it asked for "specific technologies, algorithms,
    systems" and an opening excerpt rarely names any. The bare contrast read
    Hegel as technical and a vibe-coding talk as general interest.

    **Do not tune this on the library.** ~20 documents is a sample, not an
    accuracy figure. The one miss is `art_of_unix`, whose opening is design
    philosophy rather than engineering -- a genuine borderline. Chasing it with
    wording is how a prompt starts fitting the corpus in front of it.
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
    # The fields are examples and the category is left open. A closed list is a
    # taxonomy smuggled into a prompt -- it decides against every discipline the
    # list omits, and the omission is invisible until a document from one
    # arrives. Naming what the category excludes does the separating work that
    # an exhaustive list would otherwise have to do.
    prompt = (
        "Is this text's subject matter technical or scientific in nature — for "
        "example software, engineering, mathematics, medicine, or any other "
        "technical or scientific discipline — rather than literary, historical, "
        "philosophical, or general interest?\n\n"
        f"Excerpt:\n{snippet}\n\n"
        "Reply with exactly one word: yes or no."
    )
    try:
        raw = await get_llm_service().generate(prompt, background=True)
    except Exception as exc:
        logger.warning("domain detection failed (non-fatal): %s", exc)
        return None
    answer = str(raw).strip().lower()
    if answer.startswith("yes"):
        return True
    if answer.startswith("no"):
        return False
    return None


# Kept: transcribe_node imported this name before the probe was generalised.
detect_technical_transcript = detect_technical_content


async def detect_register(raw_text: str) -> str | None:
    """Whether the text tells a story or explains a subject. None when undecided.

    The axis two hacks were reaching for. Without it `card_genre` cannot tell an
    epic from an essay, and both fall to the same fallback: "The Odyssey" was
    shown to the reader as non-fiction, which is a default wearing a
    classification's clothes.

    Read from the text, like the domain probe, and for the same reason -- no
    word list and no threshold can carry it. A story and an essay share their
    vocabulary; what differs is what the sentences are doing.

    **Sampled from the body, where the domain probe reads the opening.** The two
    axes want different windows and the reason is mechanical: a work states its
    subject early, but it opens with front matter. After the licence is stripped
    a Gutenberg novel still begins with a preface or a translator's note, which
    is expository however the book reads. Measured on 19 hand-labelled
    documents: sampling the body scores 18/19 against 15/19 for the opening, and
    the four it recovers are "The Odyssey", "Sherlock Holmes", "The Time
    Machine" and "The Gita" -- every one a narrative behind an essay.
    """
    from app.services.content_classifier import sample_body  # noqa: PLC0415
    from app.services.llm import get_llm_service  # noqa: PLC0415

    snippet = sample_body(raw_text, window=2000).strip()
    if not snippet:
        return None
    prompt = (
        "Does this text mainly tell a story, or mainly explain a subject?\n\n"
        f"Excerpt:\n{snippet}\n\n"
        "Reply with exactly one word: story or explain."
    )
    try:
        raw = await get_llm_service().generate(prompt, background=True)
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
    from sqlalchemy import update  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415

    async with get_session_factory()() as session:
        await session.execute(
            update(DocumentModel)
            .where(DocumentModel.id == document_id)
            .values(extraction_report=report)
        )
        await session.commit()


async def _persist_structure_type(document_id: str, structure_type: str) -> None:
    """Write the layout the parser discovered ('book'|'paper'|'script'|'chat')."""
    from sqlalchemy import update  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415

    async with get_session_factory()() as session:
        await session.execute(
            update(DocumentModel)
            .where(DocumentModel.id == document_id)
            .values(structure_type=structure_type)
        )
        await session.commit()


async def _persist_classification(
    document_id: str,
    content_type: str,
    is_technical: bool | None,
    register: str | None = None,
) -> None:
    """Write the content type, the technical flag and the facets they imply.

    One statement rather than several: `form` and `domain` are a function of the
    other columns, so writing them separately leaves a window in which the row
    disagrees with itself.

    `register` is only written when it was measured. Passing None leaves the
    stored value alone rather than clearing it, so a later pass that measures
    only the domain cannot wipe a register somebody already established.
    """
    from sqlalchemy import update  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415
    from app.types import DocumentProfile  # noqa: PLC0415

    profile = DocumentProfile.from_legacy(content_type, is_technical)
    values: dict[str, object] = {
        "content_type": content_type,
        "is_technical": is_technical,
        "form": profile.form,
        "domain": profile.domain,
    }
    if register is not None:
        values["register"] = register
    async with get_session_factory()() as session:
        await session.execute(
            update(DocumentModel).where(DocumentModel.id == document_id).values(**values)
        )
        await session.commit()
