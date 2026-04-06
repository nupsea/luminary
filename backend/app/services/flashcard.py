"""Flashcard generation service — LLM-based QA flashcard generation."""

import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import litellm
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChunkModel,
    DocumentModel,
    FlashcardModel,
    NoteCollectionMemberModel,
    NoteCollectionModel,
    NoteModel,
    SectionModel,
)
from app.services.llm import get_llm_service
from app.telemetry import trace_chain

logger = logging.getLogger(__name__)

FLASHCARD_SYSTEM = (
    "You are a learning assistant creating flashcards for active recall. "
    "Generate questions that test understanding, not surface recall. "
    "Match the question structure to the type of knowledge being tested: "
    "causal knowledge -> ask why or what causes; "
    "comparative knowledge -> ask how two things differ or what distinguishes them; "
    "process or role knowledge -> ask what role X plays in Y or how X enables Y; "
    "definitional knowledge -> ask what X is or what characterises X; "
    "speculative or argued knowledge -> ask what the argument or evidence for X is. "
    "AVOID: list-regurgitation questions whose answer is just an enumeration of items; "
    "trivia about exact wording; yes/no questions; "
    "questions whose answer is not derivable from the provided text. "
    "CRITICAL -- NEVER use deictic or source-referencing words in a question: "
    "'in this passage', 'in this text', 'in this excerpt', 'in this book', "
    "'in this document', 'according to the text', 'as described', 'as stated', "
    "'this scenario', 'the scenario', 'this situation', 'this case', 'this context', "
    "'this example', 'the author', 'the writer'. "
    "These make no sense on a flashcard viewed without the source. "
    "Instead, name the specific concept, entity, technology, or idea directly in the question. "
    "CRITICAL -- question framing must match the answer exactly: "
    "if the answer explains a cause, the question must ask for that cause; "
    "if the answer describes a role, the question must ask for that role. "
    "The answer must be a concise explanation in 1-3 sentences -- never a bare list of items. "
    "Before writing each question, verify: does someone without the source text understand "
    "exactly what is being asked, and does the answer directly satisfy the question? "
    "Output a JSON array starting with [ and ending with ]. "
    "Write no explanation, preamble, or markdown fences."
)

FLASHCARD_USER_TMPL = (
    "Generate {count} {difficulty}-level flashcard pairs from the text below.\n"
    "Difficulty guidelines: {difficulty_guidelines}\n"
    "{extra_instructions}"
    "Each card must be answerable from the provided text only.\n"
    "Format: "
    '[{{"question": "...", "answer": "...", "source_excerpt": "...",'
    ' "bloom_level": N}}]\n'
    "bloom_level is an integer 1-6 "
    "(1=remember, 2=understand, 3=apply, "
    "4=analyze, 5=evaluate, 6=create).\n"
    "The \"answer\" field may use Markdown (bold, lists) for clarity.\n\n"
    "Text:\n{text}\n\n"
    "JSON array:"
)

NOTES_CONCEPT_EXTRACT_SYSTEM = (
    "You are a learning analyst. Given a learner's notes, your job is two steps. "
    "STEP 1 -- DOMAIN: Identify the primary subject domain of the notes in a single short phrase. "
    "The domain is what the learner is actively trying to understand or remember. "
    "It is never the setting, date, location, or context in which the notes were written. "
    "STEP 2 -- CONCEPTS: Extract atomic, learnable concepts that are directly about that domain. "
    "A concept must be an insight, claim, argument, principle, or relationship within the domain. "
    "STRICT GROUNDING: extract only what is explicitly stated or directly implied by the notes. "
    "Never introduce knowledge from outside the notes. "
    "REJECT any concept that is about: "
    "the physical setting (weather, environment, location, surroundings); "
    "people or events incidental to the subject; "
    "bare enumerations with no explanatory content; "
    "meta-commentary about the notes. "
    "For each accepted concept, assign a type: "
    "causal-claim, comparison, process-role, factual-definition, or speculative-claim. "
    "Output ONLY a JSON object with keys \"domain\" (string) and "
    "\"concepts\" (array of {\"concept\": \"...\", \"type\": \"...\"}). "
    "No explanation, no preamble, no markdown fences."
)

NOTES_CONCEPT_EXTRACT_TMPL = (
    "Identify the domain and extract up to {max_concepts} learnable concepts from these notes.\n\n"
    "Notes:\n{text}\n\n"
    "JSON object:"
)

NOTES_CARD_FROM_CONCEPTS_SYSTEM = (
    "You are a flashcard designer. You receive a subject domain, a list of typed concepts, "
    "and the original notes they were drawn from. "
    "DOMAIN GATE: only generate cards for concepts that are directly about the stated domain. "
    "Skip any concept outside the domain even if it appears in the notes. "
    "GROUNDING GATE: only generate a card if the answer can be written using the notes alone. "
    "If the notes do not contain sufficient information, skip that concept. "
    "Never hallucinate or use external knowledge. "
    "The question structure MUST match the knowledge type: "
    "causal-claim -> ask why X leads to Y, or what causes X; "
    "comparison -> ask how X and Y differ, or what distinguishes X from Y; "
    "process-role -> ask what X collectively enables or achieves within Y "
    "(not: list the components of X); "
    "factual-definition -> ask what X is or what characterises X; "
    "speculative-claim -> ask what the argument or reasoning behind X is. "
    "The question must name the specific concept directly. "
    "NEVER use context-dependent words: 'this scenario', 'the scenario', 'this situation', "
    "'this case', 'this context', 'this example', 'the author', 'the text', 'these notes', "
    "'the man', 'the person', 'the writer'. "
    "The question must stand alone -- understandable without the notes. "
    "The answer must be derived from the notes in 1-3 sentences. "
    "For process-role: explain what the collective activity achieves or why it matters -- "
    "never enumerate the individual components as the answer. "
    'Output ONLY a JSON array: [{{"question": "...", "answer": "...", "source_excerpt": ""}}]. '
    "No explanation, no preamble, no markdown fences."
)

NOTES_CARD_FROM_CONCEPTS_TMPL = (
    "Subject domain: {domain}\n"
    "Difficulty: {difficulty}. {difficulty_guidelines}\n\n"
    "Concepts:\n{concepts_json}\n\n"
    "Notes:\n{text}\n\n"
    "JSON array:"
)

_DIFFICULTY_GUIDELINES = {
    "easy": (
        "Focus on basic recall, key characters, main plot points, and obvious facts. "
        "Questions should be straightforward."
    ),
    "medium": (
        "Focus on comprehension, connecting ideas, identifying themes, and explaining 'why'. "
        "Questions should require some thought and understanding."
    ),
    "hard": (
        "Focus on analysis, evaluation, complex relationships, subtle themes, and application "
        "to new contexts. Questions should be challenging and require deep insight."
    ),
}

_BOOK_CONTENT_GUIDELINE = (
    "IMPORTANT: Focus exclusively on the primary narrative or subject matter "
    "(story, characters, plot, themes, or core arguments). "
    "STRICTLY AVOID generating any flashcard about: "
    "Project Gutenberg, publication details, copyright notices, licensing, "
    "translators, editors, publishers, prefaces, forewords, introductions, "
    "the purpose of publishing the work, or any other front/back matter. "
    "These are irrelevant to learning the content and must be completely ignored. "
    "If the provided text starts with publisher boilerplate or editorial notes, "
    "skip past them entirely and generate questions only from the actual narrative or subject.\n"
)


# Keep well within mistral's 8K-token context (~4 chars/token, reserve ~2K for prompt+response)
_CHUNK_CHAR_LIMIT = 10_000

# S188: Bloom L3+ instruction appended to the genre system prompt
_BLOOM_L3_INSTRUCTION = (
    "\nBLOOM LEVEL TARGETING: Generate questions at Bloom's Taxonomy Level 3 or higher "
    "(application, analysis, synthesis, evaluation). At least 50% of questions must require "
    "the learner to apply, analyze, or evaluate -- not merely recall or describe. "
    "For each card, include a \"bloom_level\" integer (1-6) indicating the cognitive level. "
    "ANSWER CITATION: Each answer must reference the section or chapter where the concept "
    "appears (e.g., 'In Chapter XII...', 'In the section on X...'). "
)


async def _get_section_context_for_chunks(
    chunks: list[ChunkModel],
    session: AsyncSession,
) -> dict[str, tuple[str, str | None]]:
    """Return a map of section_id -> (section_heading, parent_heading).

    Used to enrich prompt text with section/chapter context.
    """
    section_ids = list({c.section_id for c in chunks if c.section_id})
    if not section_ids:
        return {}

    result = await session.execute(
        select(SectionModel).where(SectionModel.id.in_(section_ids))
    )
    sections = {s.id: s for s in result.scalars().all()}

    # Resolve parent headings (one level up = chapter)
    parent_ids = [s.parent_section_id for s in sections.values() if s.parent_section_id]
    parents: dict[str, SectionModel] = {}
    if parent_ids:
        parent_result = await session.execute(
            select(SectionModel).where(SectionModel.id.in_(parent_ids))
        )
        parents = {s.id: s for s in parent_result.scalars().all()}

    context_map: dict[str, tuple[str, str | None]] = {}
    for sid, sec in sections.items():
        parent_heading = (
            parents[sec.parent_section_id].heading
            if sec.parent_section_id and sec.parent_section_id in parents
            else None
        )
        context_map[sid] = (sec.heading, parent_heading)
    return context_map


async def _get_entity_names_for_document(
    document_id: str,
    types: list[str] | None = None,
    limit: int = 5,
) -> list[str]:
    """Query Kuzu for top entity names for a document, filtered by type.

    Returns up to *limit* names. Non-fatal: returns [] on error.
    """
    try:
        from app.services.graph import get_graph_service  # noqa: PLC0415

        graph_svc = get_graph_service()
        by_type = await asyncio.to_thread(
            graph_svc.get_entities_by_type_for_document, document_id
        )
        names: list[str] = []
        target_types = types or ["PERSON", "PLACE"]
        for t in target_types:
            names.extend(by_type.get(t, []))
        # Deduplicate while preserving order, take top N
        seen: set[str] = set()
        unique: list[str] = []
        for n in names:
            if n not in seen:
                seen.add(n)
                unique.append(n)
        return unique[:limit]
    except Exception:
        logger.debug(
            "Entity lookup failed for %s; skipping enrichment",
            document_id, exc_info=True,
        )
        return []


def _build_enriched_text(
    chunks: list[ChunkModel],
    section_ctx: dict[str, tuple[str, str | None]],
) -> tuple[str, str]:
    """Build combined text with section heading prefixes for context.

    Returns (enriched_text, first_chunk_id).
    """
    if not chunks:
        return "", ""

    parts: list[str] = []
    total = 0
    for c in chunks:
        if total >= _CHUNK_CHAR_LIMIT:
            break
        prefix = ""
        if c.section_id and c.section_id in section_ctx:
            heading, parent = section_ctx[c.section_id]
            if parent:
                prefix = f"[{parent} > {heading}]\n"
            else:
                prefix = f"[{heading}]\n"
        part = prefix + c.text
        parts.append(part)
        total += len(part)

    return "\n\n".join(parts), chunks[0].id


def _resolve_section_heading(
    chunk: ChunkModel,
    section_ctx: dict[str, tuple[str, str | None]],
) -> str | None:
    """Build a display-friendly section heading for a card from its chunk's section context."""
    if not chunk.section_id or chunk.section_id not in section_ctx:
        return None
    heading, parent = section_ctx[chunk.section_id]
    if parent:
        return f"{parent} - {heading}"
    return heading


async def _fetch_chunks(
    document_id: str,
    scope: Literal["full", "section"],
    section_heading: str | None,
    session: AsyncSession,
    content_type: str = "unknown",
) -> list[ChunkModel]:
    """Return ordered chunks for the document, filtered by section when scope='section'.

    If scope='full' and content_type='book', it tries to skip preface/introduction sections
    to avoid metadata-heavy flashcards.
    """
    if scope == "section" and section_heading:
        sec_result = await session.execute(
            select(SectionModel)
            .where(SectionModel.document_id == document_id)
            .where(SectionModel.heading == section_heading)
            .limit(1)
        )
        section = sec_result.scalar_one_or_none()
        if section:
            result = await session.execute(
                select(ChunkModel)
                .where(ChunkModel.document_id == document_id)
                .where(ChunkModel.section_id == section.id)
                .order_by(ChunkModel.chunk_index)
            )
            return list(result.scalars().all())

    # Full scope
    if content_type == "book":
        # Identify sections to skip (preface, intro, etc.)
        skip_terms = [
            "preface", "introduction", "prologue", "foreword",
            "about the author", "copyright", "translator",
            "table of contents", "appendix", "index", "bibliography"
        ]
        sections_result = await session.execute(
            select(SectionModel)
            .where(SectionModel.document_id == document_id)
            .order_by(SectionModel.section_order)
        )
        sections = list(sections_result.scalars().all())

        if sections:
            valid_section_ids = [
                s.id for s in sections
                if not any(term in s.heading.lower() for term in skip_terms)
            ]
            # If we filtered everything out, fall back to all sections
            if not valid_section_ids:
                valid_section_ids = [s.id for s in sections]

            result = await session.execute(
                select(ChunkModel)
                .where(ChunkModel.document_id == document_id)
                .where(ChunkModel.section_id.in_(valid_section_ids))
                .order_by(ChunkModel.chunk_index)
            )
            return list(result.scalars().all())

    result = await session.execute(
        select(ChunkModel)
        .where(ChunkModel.document_id == document_id)
        .order_by(ChunkModel.chunk_index)
    )
    all_chunks = list(result.scalars().all())

    # If it's a book and we don't have sections (or skip logic didn't trigger),
    # skip the first 5% which is usually front matter/preface.
    if content_type == "book" and all_chunks:
        # Check if first chunk has a section heading that was missed
        # If no sections at all, skip first 5%
        sections_count_result = await session.execute(
            select(text("COUNT(*)"))
            .select_from(SectionModel)
            .where(SectionModel.document_id == document_id)
        )
        count = sections_count_result.scalar()
        if count == 0:
            skip_count = max(1, len(all_chunks) // 20)
            return all_chunks[skip_count:]

    return all_chunks


def _build_text(chunks: list[ChunkModel]) -> tuple[str, str]:
    """Build combined text from chunks.

    If the total text exceeds _CHUNK_CHAR_LIMIT, it samples chunks from the
    beginning, middle, and end to provide better coverage of the entire document.
    Returns (combined_text, first_chunk_id).
    """
    if not chunks:
        return "", ""

    total_chars = sum(len(c.text) for c in chunks)
    if total_chars <= _CHUNK_CHAR_LIMIT:
        return "\n\n".join(c.text for c in chunks), chunks[0].id

    # Sampling strategy:
    # 1. Take first 25% of the limit from the beginning
    # 2. Take 50% from the middle
    # 3. Take 25% from the end
    target_len = _CHUNK_CHAR_LIMIT
    segment_size = target_len // 4

    def get_segment(chunk_list: list[ChunkModel], max_chars: int) -> str:
        parts: list[str] = []
        current = 0
        for c in chunk_list:
            if current + len(c.text) > max_chars:
                break
            parts.append(c.text)
            current += len(c.text)
        return "\n\n".join(parts)

    # Beginning
    beginning = get_segment(chunks, segment_size)

    # Middle
    mid_idx = len(chunks) // 2
    middle = get_segment(chunks[mid_idx:], segment_size * 2)

    # End
    # For the end, we iterate backwards to get a segment, then reverse it
    end_parts: list[str] = []
    end_current = 0
    for c in reversed(chunks):
        if end_current + len(c.text) > segment_size:
            break
        end_parts.append(c.text)
        end_current += len(c.text)
    end = "\n\n".join(reversed(end_parts))

    combined = f"{beginning}\n\n[...]\n\n{middle}\n\n[...]\n\n{end}"
    return combined, chunks[0].id


def _parse_concept_extract(raw: str) -> tuple[str, list[dict]]:
    """Parse the concept-extraction response: {"domain": "...", "concepts": [...]}.

    Returns (domain, concepts). Falls back gracefully if the LLM deviates from the format.
    """
    raw = raw.strip()
    # Strip markdown fences if present.
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0].strip()
    # Try to find the outermost JSON object.
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        try:
            obj = json.loads(raw[start:end])
            domain = str(obj.get("domain", "")).strip()
            concepts = [
                c for c in obj.get("concepts", [])
                if isinstance(c, dict) and c.get("concept")
            ]
            return domain, concepts
        except (json.JSONDecodeError, ValueError):
            pass
    # Fallback: try to extract a bare array (old format compatibility).
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start != -1 and end > start:
        try:
            concepts = json.loads(raw[start:end])
            return "", [c for c in concepts if isinstance(c, dict) and c.get("concept")]
        except (json.JSONDecodeError, ValueError):
            pass
    logger.warning("Concept extract parse failed: %r", raw[:200])
    return "", []


def _parse_llm_response(raw: str, document_id: str) -> list[dict]:
    """Extract a JSON array from the LLM response.

    Handles:
    - Clean JSON array responses
    - Responses wrapped in markdown code fences
    - Responses with preamble prose before the array
    - Responses with trailing text after the array
    """
    raw = raw.strip()

    # Strip markdown code fences
    raw = re.sub(r"^```[^\n]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    raw = raw.strip()

    # If it already looks like a clean array, try parsing directly
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    # Fall back: find the first '[' and last ']' and parse that slice
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    logger.warning("Flashcard JSON parse failed for doc %s: %r", document_id, raw[:200])
    return []


TECH_FLASHCARD_SYSTEM = (
    "You are a technical learning assistant creating flashcards based on Bloom's Taxonomy. "
    "For each card choose exactly one of these flashcard types: "
    "definition (L1), syntax_recall (L1), concept_explanation (L2), analogy (L2), "
    "code_completion (L3), api_signature (L3), trace (L4), pattern_recognition (L4), "
    "design_decision (L5), complexity (L5), implementation (L6). "
    "Choose the type that best matches what the card asks the learner to do. "
    "For code_completion cards: show a code block with a blank rendered as ____ where the "
    "learner must supply the missing part. "
    "For trace cards: show a code snippet and ask the learner to predict its output. "
    "For design_decision cards: ask the learner to justify a technical choice. "
    "For complexity cards: ask the learner to state and justify Big-O for an algorithm. "
    "Questions must be self-contained. "
    "NEVER use phrases like 'in this passage' or 'in this text'. "
    "Output a JSON array starting with [ and ending with ]. "
    'Each element: {"question": "...", "answer": "...", '
    '"source_excerpt": "...", "flashcard_type": "...", "bloom_level": N}. '
    "bloom_level is an integer 1-6. "
    "Write no explanation, preamble, or markdown fences."
)

TECH_FLASHCARD_USER_TMPL = (
    "Generate {count} technical flashcards from the text below.\n"
    "Prefer higher Bloom levels (trace, code_completion, design_decision) when the text "
    "contains code blocks, API signatures, or trade-off discussions.\n"
    "When the section heading contains 'vs' or 'trade-off', generate at least one "
    "design_decision card (bloom_level=5).\n"
    "When the text contains an admonition type of 'warning', generate at least one "
    "definition card (bloom_level=1) that captures the warning.\n"
    "Each card must be answerable from the provided text only.\n"
    'Format: [{{"question": "...", "answer": "...", "source_excerpt": "...", '
    '"flashcard_type": "...", "bloom_level": N}}]\n\n'
    "Section heading: {section_heading}\n"
    "Has code blocks: {has_code}\n"
    "Admonition type: {admonition_type}\n\n"
    "Text:\n{text}\n\n"
    "JSON array:"
)


GAP_FLASHCARD_SYSTEM = (
    "You are a learning assistant. Generate exactly ONE flashcard for the given knowledge gap. "
    'Output ONLY a JSON object with two keys: {"front": "...", "back": "..."} '
    "where 'front' is the question and 'back' is a concise answer. "
    "Write no explanation, preamble, or markdown fences. Output only the JSON object."
)

GAP_FLASHCARD_USER_TMPL = (
    'Knowledge gap: "{gap}"\n\n'
    'Generate one flashcard as JSON: {{"front": "question", "back": "answer"}}'
)

GRAPH_FLASHCARD_SYSTEM = (
    "You are a learning assistant creating flashcards that test understanding of relationships "
    "between concepts. Each question must ask how two named entities are connected, "
    "what one entity means in the context of the other, "
    "or what role one plays relative to the other. "
    "NEVER frame a question as a definition question ('What is X?'). "
    "NEVER use phrases like 'in this passage' or 'according to this text'. "
    "Questions must be self-contained. "
    "Output a JSON array starting with [ and ending with ]. "
    "Write no explanation, preamble, or markdown fences."
)

GRAPH_FLASHCARD_USER_TMPL = (
    "Entity A: {name_a}\n"
    "Entity B: {name_b}\n"
    "Relationship hint: {relation_label}\n\n"
    "Context passages:\n{context}\n\n"
    "Generate {count} flashcard(s) testing the relationship between '{name_a}' and '{name_b}'.\n"
    "Each question must be framed as a relationship question "
    "('How does X relate to Y?', 'What connects X and Y?', 'What role does X play in Y?').\n"
    'Format: [{{"question": "...", "answer": "...", "source_excerpt": "..."}}]\n'
    "JSON array:"
)


def _parse_gap_flashcard(raw: str, gap: str) -> dict | None:
    """Parse a single {front, back} JSON object from LLM response for one gap."""
    raw = raw.strip()
    raw = re.sub(r"^```[^\n]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    raw = raw.strip()

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
            if isinstance(data, dict) and data.get("front") and data.get("back"):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    logger.warning("Gap flashcard JSON parse failed for gap %r: %r", gap[:50], raw[:200])
    return None


# ---------------------------------------------------------------------------
# S154: Cloze deletion helpers and prompts
# ---------------------------------------------------------------------------

CLOZE_SYSTEM = (
    "You are a learning assistant creating cloze deletion (fill-in-the-blank) flashcards. "
    "Extract 3-5 key technical terms or concepts from the section text. "
    "For each term, produce a sentence that embeds the term using {{term}} syntax. "
    "Each sentence must make sense without the blank and use one or two blanks only. "
    "Output a JSON array starting with [ and ending with ]. "
    'Each element: {"cloze_text": "...", "source_excerpt": "..."}. '
    "cloze_text uses {{term}} markers. source_excerpt is a verbatim passage from the text. "
    "Write no explanation, preamble, or markdown fences."
)

CLOZE_USER_TMPL = (
    "Generate {count} cloze deletion cards from the text below.\n"
    "Each card must contain at least one {{{{term}}}} blank. "
    "Use exactly one or two blanks per sentence.\n"
    "Text:\n{text}\n\n"
    "JSON array:"
)

_CLOZE_BLANK_RE = re.compile(r"\{\{(.+?)\}\}")


def _parse_cloze_text(cloze_text: str) -> list[str]:
    """Return list of blank terms extracted from {{term}} markers in order."""
    return _CLOZE_BLANK_RE.findall(cloze_text)


def _build_cloze_question(cloze_text: str) -> str:
    """Replace {{term}} markers with [____] for list-view display."""
    return _CLOZE_BLANK_RE.sub("[____]", cloze_text)


def _parse_cloze_llm_response(raw: str) -> list[dict]:
    """Parse the LLM JSON array response for cloze cards.

    Filters out any element whose cloze_text has no {{}} markers (malformed).
    Returns only valid elements.
    """
    items = _parse_llm_response(raw, "cloze")
    valid = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cloze_text = str(item.get("cloze_text", "")).strip()
        if not cloze_text:
            continue
        blanks = _parse_cloze_text(cloze_text)
        if not blanks:
            logger.warning("Cloze item has no {{}} markers, skipping: %r", cloze_text[:100])
            continue
        valid.append(item)
    return valid


# ---------------------------------------------------------------------------
# S179: Chunk classifier and genre-aware prompt helpers
# ---------------------------------------------------------------------------

_ANALOGY_PATTERNS = re.compile(
    r"\b(like a|similar to|imagine|think of it as|is like|just as|as if|as though"
    r"|analogous to|metaphor|by analogy)\b",
    re.IGNORECASE,
)
_EXAMPLE_PATTERNS = re.compile(
    r"\b(for example|for instance|e\.g\.|consider this|such as|to illustrate"
    r"|as an example|as a case)\b",
    re.IGNORECASE,
)
_DEFINITION_PATTERNS = re.compile(
    r"(is defined as|refers to|means that|is the process of|is a term|"
    r"can be defined|:\s*a\s+\w|:\s*the\s+\w)",
    re.IGNORECASE,
)
_CONCEPT_PATTERNS = re.compile(
    r"\b(therefore|as a result|the key idea|the principle|this means|the reason"
    r"|this enables|this causes|the mechanism|the implication|the effect|"
    r"crucially|fundamentally|essentially)\b",
    re.IGNORECASE,
)
_TRANSITION_PATTERNS = re.compile(
    r"\b(in the next|in the following|as we saw|moving on|in summary|"
    r"to recap|we have seen|in this chapter)\b",
    re.IGNORECASE,
)

_TECH_TITLE_KEYWORDS = re.compile(
    r"\b(programming|systems|distributed|database|algorithm|machine learning"
    r"|software|engineering|computer|kubernetes|docker|linux|network|security"
    r"|data structures|operating system)\b",
    re.IGNORECASE,
)

_CHUNK_CLASSIFICATION_LABELS = frozenset(
    {"concept", "definition", "example", "analogy", "narrative", "transition"}
)
_ELIGIBLE_LABELS = frozenset({"concept", "definition"})


def _classify_chunk(text: str) -> str:
    """Classify a chunk of text into one of six categories.

    Rules applied in order -- first match wins:
      definition > concept > analogy > example > transition > narrative
    """
    if _DEFINITION_PATTERNS.search(text):
        return "definition"
    if _CONCEPT_PATTERNS.search(text):
        return "concept"
    if _ANALOGY_PATTERNS.search(text):
        return "analogy"
    if _EXAMPLE_PATTERNS.search(text):
        return "example"
    if len(text.strip()) < 80 or _TRANSITION_PATTERNS.search(text):
        return "transition"
    return "narrative"


def _filter_chunks_by_classification(
    chunks: list[ChunkModel],
) -> list[tuple[ChunkModel, str]]:
    """Return (chunk, label) pairs for chunks eligible for flashcard generation.

    Eligible: concept or definition chunks, plus any immediately adjacent
    example/analogy chunk that elaborates a concept/definition chunk.
    """
    if not chunks:
        return []

    labels = [_classify_chunk(c.text) for c in chunks]
    eligible_indices: set[int] = set()

    for i, label in enumerate(labels):
        if label in _ELIGIBLE_LABELS:
            eligible_indices.add(i)
            # Adjacent elaborators
            if i > 0 and labels[i - 1] in ("example", "analogy"):
                eligible_indices.add(i - 1)
            if i < len(chunks) - 1 and labels[i + 1] in ("example", "analogy"):
                eligible_indices.add(i + 1)

    return [(chunks[i], labels[i]) for i in sorted(eligible_indices)]


def _infer_genre(doc: "DocumentModel | None") -> str:  # type: ignore[name-defined]
    """Infer document genre for system prompt tuning."""
    if doc is None:
        return "narrative"
    content_type = (doc.content_type or "").lower()
    title = (doc.title or "").lower()
    if content_type == "book":
        if _TECH_TITLE_KEYWORDS.search(title):
            return "technical"
        return "non-fiction"
    if content_type in ("pdf", "web"):
        return "academic"
    return "narrative"


def _build_genre_system_prompt(genre: str) -> str:
    """Build a genre-aware flashcard generation system prompt."""
    genre_hint = (
        f"This is a {genre} document. "
        if genre != "narrative"
        else ""
    )
    quality_rules = (
        "QUALITY RULES for concept-focused questions:\n"
        "- Do NOT write questions whose answer is a proper noun drawn from an analogy or "
        "illustrative story used to explain a concept (e.g., do not ask 'What animal did the "
        "author compare X to?').\n"
        "- Questions must be answerable by someone who understands the underlying concept but "
        "has NOT read the specific analogy or illustration.\n"
        "- Prefer 'Explain X in your own words' and 'What is the practical implication of Y' "
        "over 'According to the text, what does Z do'.\n"
        "- Frame questions in terms of WHY or HOW, not WHAT was mentioned in an example.\n"
    )
    return (
        genre_hint
        + "You are a learning assistant creating flashcards for active recall. "
        "Generate questions that test understanding of core concepts and principles. "
        "Prefer questions that: (1) ask the learner to explain a concept in their own words, "
        "(2) apply a concept to a new situation, "
        "(3) distinguish between similar concepts, "
        "or (4) evaluate a claim or argument. "
        "AVOID: trivia questions about exact wording, hypothetical questions not grounded "
        "in the content, questions whose answer is not in the text, yes/no questions. "
        "CRITICAL -- questions must be fully self-contained. "
        "NEVER use phrases like 'in this passage', 'according to this text', 'in this excerpt', "
        "'in this book', 'in this document', or any similar reference to the source material. "
        "A flashcard question must make complete sense on its own without seeing the original"
        " text. "
        + quality_rules
        + "Output a JSON array starting with [ and ending with ]. "
        "Write no explanation, preamble, or markdown fences."
    )



async def _fetch_existing_embeddings(
    deck: str, session: AsyncSession
) -> "tuple[list[str], list] | tuple[list, None]":
    """Fetch all existing questions in *deck* and embed them in one batch.

    Returns (questions, vectors) or ([], None) when the deck is empty or embedding fails.
    """
    import numpy as np  # noqa: PLC0415

    from app.services.embedder import get_embedding_service  # noqa: PLC0415

    result = await session.execute(
        select(FlashcardModel.question).where(FlashcardModel.deck == deck)
    )
    existing_questions = [row[0] for row in result.all()]
    if not existing_questions:
        return [], None

    embedder = get_embedding_service()
    try:
        vecs = await asyncio.to_thread(embedder.encode, existing_questions)
        return existing_questions, np.array(vecs)
    except Exception:
        logger.warning(
            "Embedding dedup: failed to encode existing questions; skipping dedup", exc_info=True
        )
        return [], None


def _is_near_duplicate(
    candidate_vec: "Any",
    existing_vecs: "Any",
    threshold: float = 0.85,
) -> bool:
    """Return True if candidate_vec is within *threshold* cosine similarity of any existing_vec."""
    import numpy as np  # noqa: PLC0415

    candidate_norm = candidate_vec / (np.linalg.norm(candidate_vec) + 1e-10)
    existing_norms = existing_vecs / (np.linalg.norm(existing_vecs, axis=1, keepdims=True) + 1e-10)
    sims = existing_norms @ candidate_norm
    return bool(np.any(sims >= threshold))


# ---------------------------------------------------------------------------
# S206: Sanitize FTS5 query to prevent syntax errors from special characters
# ---------------------------------------------------------------------------

_FTS5_SPECIAL = re.compile(r'[(){}*:^~"\[\]<>]')


def _sanitize_fts5_query(raw: str) -> str:
    """Strip FTS5 operators and join tokens with AND for multi-word queries.

    Returns empty string if nothing useful remains after sanitization.
    """
    cleaned = _FTS5_SPECIAL.sub(" ", raw)
    # Remove FTS5 boolean operators that users might accidentally type
    tokens = [t for t in cleaned.split() if t.upper() not in ("AND", "OR", "NOT", "NEAR")]
    if not tokens:
        return ""
    # Wrap each token in double quotes for literal matching, join with AND
    return " AND ".join(f'"{t}"' for t in tokens)


# ---------------------------------------------------------------------------
# S184: FTS5 sync helpers for flashcards_fts
# ---------------------------------------------------------------------------


async def _sync_flashcard_fts(card: FlashcardModel, session: AsyncSession) -> None:
    """Insert or update a flashcard's question+answer in the FTS5 index.

    FTS5 UNINDEXED columns don't support OR REPLACE semantics.
    Delete any existing row first (via shadow table rowid lookup per I-4),
    then insert the new row.
    """
    # Delete existing row if any (idempotent)
    row = (
        await session.execute(
            text("SELECT rowid FROM flashcards_fts_content WHERE c2 = :fid"),
            {"fid": card.id},
        )
    ).first()
    if row:
        await session.execute(
            text("DELETE FROM flashcards_fts WHERE rowid = :rid"),
            {"rid": row[0]},
        )
    # Insert fresh row
    await session.execute(
        text(
            "INSERT INTO flashcards_fts(flashcard_id, question, answer) "
            "VALUES (:fid, :q, :a)"
        ),
        {"fid": card.id, "q": card.question, "a": card.answer},
    )


async def _delete_flashcard_fts(card_id: str, session: AsyncSession) -> None:
    """Delete a flashcard from the FTS5 index using shadow table rowid lookup (I-4 safe)."""
    row = (
        await session.execute(
            text("SELECT rowid FROM flashcards_fts_content WHERE c2 = :fid"),
            {"fid": card_id},
        )
    ).first()
    if row:
        await session.execute(
            text("DELETE FROM flashcards_fts WHERE rowid = :rid"),
            {"rid": row[0]},
        )


class FlashcardService:
    async def search(
        self,
        session: AsyncSession,
        query: str | None = None,
        document_id: str | None = None,
        collection_id: str | None = None,
        tag: str | None = None,
        bloom_level_min: int | None = None,
        bloom_level_max: int | None = None,
        fsrs_state: str | None = None,
        flashcard_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[FlashcardModel], int]:
        """Search flashcards with optional FTS query and structured filters (S184).

        All filters combine with AND. Returns (cards, total_count).
        """
        from sqlalchemy import or_  # noqa: PLC0415

        from app.models import NoteCollectionMemberModel, NoteTagIndexModel  # noqa: PLC0415

        stmt = select(FlashcardModel)
        _fts_query_used = False
        _raw_query = query.strip() if query else ""

        if _raw_query:
            sanitized = _sanitize_fts5_query(_raw_query)
            if sanitized:
                fts_sub = (
                    select(text("flashcard_id"))
                    .select_from(text("flashcards_fts"))
                    .where(text("flashcards_fts MATCH :q"))
                )
                stmt = stmt.where(FlashcardModel.id.in_(fts_sub)).params(q=sanitized)
                _fts_query_used = True
            else:
                # All tokens were FTS5 operators; use LIKE directly
                like_pat = f"%{_raw_query}%"
                stmt = stmt.where(
                    or_(
                        FlashcardModel.question.ilike(like_pat),
                        FlashcardModel.answer.ilike(like_pat),
                    )
                )

        if document_id:
            stmt = stmt.where(FlashcardModel.document_id == document_id)

        if collection_id:
            member_sub = select(NoteCollectionMemberModel.note_id).where(
                NoteCollectionMemberModel.collection_id == collection_id
            )
            stmt = stmt.where(FlashcardModel.note_id.in_(member_sub))

        if tag:
            tag_sub = select(NoteTagIndexModel.note_id).where(
                or_(
                    NoteTagIndexModel.tag_full == tag,
                    NoteTagIndexModel.tag_full.like(tag + "/%"),
                )
            )
            stmt = stmt.where(FlashcardModel.note_id.in_(tag_sub))

        if bloom_level_min is not None:
            stmt = stmt.where(
                FlashcardModel.bloom_level.is_not(None),
                FlashcardModel.bloom_level >= bloom_level_min,
            )

        if bloom_level_max is not None:
            stmt = stmt.where(
                FlashcardModel.bloom_level.is_not(None),
                FlashcardModel.bloom_level <= bloom_level_max,
            )

        if fsrs_state:
            stmt = stmt.where(FlashcardModel.fsrs_state == fsrs_state)

        if flashcard_type:
            stmt = stmt.where(FlashcardModel.flashcard_type == flashcard_type)

        # Count total matches
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar_one()

        # S206: LIKE fallback when FTS5 returns 0 results
        if total == 0 and _fts_query_used and query:
            like_pat = f"%{query.strip()}%"
            stmt_fallback = select(FlashcardModel).where(
                or_(
                    FlashcardModel.question.ilike(like_pat),
                    FlashcardModel.answer.ilike(like_pat),
                )
            )
            # Re-apply non-query filters on fallback
            if document_id:
                stmt_fallback = stmt_fallback.where(FlashcardModel.document_id == document_id)
            if collection_id:
                member_sub2 = select(NoteCollectionMemberModel.note_id).where(
                    NoteCollectionMemberModel.collection_id == collection_id
                )
                stmt_fallback = stmt_fallback.where(FlashcardModel.note_id.in_(member_sub2))
            if tag:
                tag_sub2 = select(NoteTagIndexModel.note_id).where(
                    or_(
                        NoteTagIndexModel.tag_full == tag,
                        NoteTagIndexModel.tag_full.like(tag + "/%"),
                    )
                )
                stmt_fallback = stmt_fallback.where(FlashcardModel.note_id.in_(tag_sub2))
            if bloom_level_min is not None:
                stmt_fallback = stmt_fallback.where(
                    FlashcardModel.bloom_level.is_not(None),
                    FlashcardModel.bloom_level >= bloom_level_min,
                )
            if bloom_level_max is not None:
                stmt_fallback = stmt_fallback.where(
                    FlashcardModel.bloom_level.is_not(None),
                    FlashcardModel.bloom_level <= bloom_level_max,
                )
            if fsrs_state:
                stmt_fallback = stmt_fallback.where(FlashcardModel.fsrs_state == fsrs_state)
            if flashcard_type:
                stmt_fallback = stmt_fallback.where(FlashcardModel.flashcard_type == flashcard_type)

            count_fb = select(func.count()).select_from(stmt_fallback.subquery())
            total = (await session.execute(count_fb)).scalar_one()
            if total > 0:
                stmt = stmt_fallback
                logger.info("flashcard.search: FTS5 returned 0, LIKE fallback found %d", total)

        # Paginate
        stmt = stmt.order_by(FlashcardModel.created_at.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(stmt)
        cards = list(result.scalars().all())

        return cards, total

    async def generate(
        self,
        document_id: str,
        scope: Literal["full", "section"],
        section_heading: str | None,
        count: int,
        session: AsyncSession,
        difficulty: Literal["easy", "medium", "hard"] = "medium",
        context: str | None = None,
    ) -> list[FlashcardModel]:
        """Generate flashcards from document chunks using LLM.

        When *context* (selected text) is provided, uses it directly instead of
        fetching chunks -- this produces questions grounded in the exact selection.
        Otherwise fetches chunks (all or filtered by section heading), calls LiteLLM,
        parses JSON output, and persists cards in SQLite with fsrs_state='new'.
        """
        llm = get_llm_service()

        doc_result = await session.execute(
            select(DocumentModel).where(DocumentModel.id == document_id)
        )
        doc = doc_result.scalar_one_or_none()
        content_type = doc.content_type if doc else "unknown"

        # S179: infer genre for genre-aware system prompt
        genre = _infer_genre(doc)
        system_prompt = _build_genre_system_prompt(genre)

        # When the caller supplies selected text, use it directly (bypass classifier).
        chunk_classification: str | None = None
        section_ctx: dict[str, tuple[str, str | None]] = {}
        resolved_section_heading: str | None = None
        if context and context.strip():
            combined_text = context.strip()[:_CHUNK_CHAR_LIMIT]
            # Still need a chunk_id (NOT NULL) — grab the first chunk for the document.
            first_chunk_result = await session.execute(
                select(ChunkModel.id)
                .where(ChunkModel.document_id == document_id)
                .order_by(ChunkModel.chunk_index)
                .limit(1)
            )
            first_chunk_id = first_chunk_result.scalar_one_or_none() or document_id
        else:
            chunks = await _fetch_chunks(document_id, scope, section_heading, session, content_type)
            if not chunks:
                return []

            # S188: look up section headings for context enrichment
            section_ctx = await _get_section_context_for_chunks(chunks, session)

            # S179: classify chunks and filter to concept/definition (+ adjacent elaborators)
            classified = _filter_chunks_by_classification(chunks)
            if classified:
                eligible_chunks = [c for c, _ in classified]
                chunk_classification = classified[0][1]  # dominant label of first chunk
                logger.info(
                    "flashcard.generate: %d/%d chunks eligible after classification (genre=%s)",
                    len(eligible_chunks),
                    len(chunks),
                    genre,
                )
            else:
                # Safety net: no chunks classified as concept/definition -- use all chunks
                eligible_chunks = chunks
                logger.info(
                    "flashcard.generate: no concept/definition chunks found, using all %d chunks",
                    len(chunks),
                )

            # S188: build enriched text with section heading prefixes
            if section_ctx:
                combined_text, first_chunk_id = _build_enriched_text(eligible_chunks, section_ctx)
            else:
                combined_text, first_chunk_id = _build_text(eligible_chunks)
            if not combined_text:
                return []

            # S188: resolve section heading for cards (first chunk's section)
            first_sec = eligible_chunks[0].section_id if eligible_chunks else None
            if first_sec and first_sec in section_ctx:
                resolved_section_heading = _resolve_section_heading(
                    eligible_chunks[0], section_ctx
                )

        # S188: enrich system prompt with Bloom L3+ targeting and citation instruction
        system_prompt += _BLOOM_L3_INSTRUCTION

        # S188: for books, inject entity names into the system prompt
        extra_instructions = ""
        if content_type == "book":
            extra_instructions = _BOOK_CONTENT_GUIDELINE
            entity_names = await _get_entity_names_for_document(
                document_id, types=["PERSON", "PLACE"], limit=5
            )
            if entity_names:
                names_str = ", ".join(entity_names)
                extra_instructions += (
                    f"Key characters and places in this work: {names_str}. "
                    "Reference these names directly in questions when relevant.\n"
                )

        # S188: for technical docs, include code block excerpts
        is_tech = content_type in ("code", "tech_book", "tech_article")
        has_context = context and context.strip()
        if is_tech and not has_context:
            code_chunks = [c for c in eligible_chunks if c.has_code]
            if code_chunks:
                code_excerpts = "\n\n".join(
                    c.text[:1000] for c in code_chunks[:3]
                )
                extra_instructions += (
                    f"Code blocks from the document:\n{code_excerpts}\n"
                    "Include code examples in questions where appropriate.\n"
                )

        prompt = FLASHCARD_USER_TMPL.format(
            count=count,
            difficulty=difficulty,
            difficulty_guidelines=_DIFFICULTY_GUIDELINES.get(difficulty, ""),
            extra_instructions=extra_instructions,
            text=combined_text,
        )

        with trace_chain(
            "flashcard.generate",
            input_value=f"doc={document_id} scope={scope} count={count} difficulty={difficulty}",
        ) as span:
            span.set_attribute("flashcard.document_id", document_id)
            span.set_attribute("flashcard.scope", scope)
            span.set_attribute("flashcard.requested_count", count)
            span.set_attribute("flashcard.difficulty", difficulty)
            if section_heading:
                span.set_attribute("flashcard.section_heading", section_heading)

            raw = await llm.generate(prompt, system=system_prompt, stream=False)
            cards_data = _parse_llm_response(raw, document_id)
            span.set_attribute("flashcard.generated_count", len(cards_data))

        now = datetime.now(UTC)

        # Pre-compute existing embeddings once (avoids re-embedding on every card).
        # Also embed all candidate questions in one batch, then filter duplicates in-memory.
        import numpy as np  # noqa: PLC0415

        from app.services.embedder import get_embedding_service  # noqa: PLC0415

        _existing_qs, existing_vecs = await _fetch_existing_embeddings("default", session)

        # Collect valid candidates first, then dedup in a single embed batch
        candidates: list[dict] = []
        for item in cards_data:
            if not isinstance(item, dict):
                continue
            q = str(item.get("question", "")).strip()
            a = str(item.get("answer", "")).strip()
            if q and a:
                candidates.append(item)

        # Batch-embed all candidate questions in one call
        if candidates and existing_vecs is not None:
            try:
                embedder = get_embedding_service()
                cand_texts = [str(c.get("question", "")).strip() for c in candidates]
                cand_vecs = await asyncio.to_thread(embedder.encode, cand_texts)
                cand_vecs = np.array(cand_vecs)
            except Exception:
                logger.warning(
                    "Embedding dedup: candidate encode failed; skipping dedup", exc_info=True
                )
                cand_vecs = None
        else:
            cand_vecs = None

        # Build accepted set, checking each candidate against existing + previously accepted
        pool_vecs = existing_vecs  # grows as we accept cards
        flashcards: list[FlashcardModel] = []
        for i, item in enumerate(candidates):
            question = str(item.get("question", "")).strip()
            answer = str(item.get("answer", "")).strip()
            source_excerpt = str(item.get("source_excerpt", "")).strip()
            # Dedup check using pre-computed vectors
            if cand_vecs is not None and pool_vecs is not None:
                if _is_near_duplicate(cand_vecs[i], pool_vecs):
                    logger.info(
                        "flashcard.generate: skipping near-duplicate question: %r",
                        question[:80],
                    )
                    continue
                # Add accepted card's vector to pool so intra-batch duplicates are also caught
                pool_vecs = np.vstack([pool_vecs, cand_vecs[i : i + 1]])
            # S188: extract bloom_level from LLM response if present
            card_bloom_level = item.get("bloom_level")
            if isinstance(card_bloom_level, int) and 1 <= card_bloom_level <= 6:
                pass  # valid
            else:
                card_bloom_level = None

            card = FlashcardModel(
                id=str(uuid.uuid4()),
                document_id=document_id,
                chunk_id=first_chunk_id,
                question=question,
                answer=answer,
                source_excerpt=source_excerpt,
                difficulty=difficulty,
                fsrs_state="new",
                fsrs_stability=0.0,
                fsrs_difficulty=0.0,
                due_date=now,
                reps=0,
                lapses=0,
                created_at=now,
                chunk_classification=chunk_classification,
                bloom_level=card_bloom_level,
                section_heading=resolved_section_heading,
            )
            session.add(card)
            await _sync_flashcard_fts(card, session)
            flashcards.append(card)

        if flashcards:
            await session.commit()
            for card in flashcards:
                await session.refresh(card)

        return flashcards


    async def generate_from_notes(
        self,
        tag: str | None,
        note_ids: list[str] | None,
        count: int,
        session: AsyncSession,
        difficulty: Literal["easy", "medium", "hard"] = "medium",
    ) -> list[FlashcardModel]:
        """Generate flashcards from user notes scoped by tag or explicit note IDs.

        Raises ValueError if neither tag nor note_ids is provided.
        Returns [] if no matching notes are found.
        """
        if not tag and not note_ids:
            raise ValueError("Must provide tag or note_ids")

        llm = get_llm_service()

        if note_ids:
            result = await session.execute(
                select(NoteModel).where(NoteModel.id.in_(note_ids))
            )
            notes = list(result.scalars().all())
        else:
            result = await session.execute(
                select(NoteModel).where(
                    text(
                        "EXISTS (SELECT 1 FROM json_each(notes.tags)"
                        " WHERE json_each.value = :tag)"
                    ).bindparams(tag=tag)
                )
            )
            notes = list(result.scalars().all())

        if not notes:
            return []

        combined_text = "\n\n".join(n.content for n in notes)[:_CHUNK_CHAR_LIMIT]
        if not combined_text:
            return []

        # Pass 1: extract typed concepts from the notes.
        extract_prompt = NOTES_CONCEPT_EXTRACT_TMPL.format(
            max_concepts=max(count, 8),
            text=combined_text,
        )

        with trace_chain(
            "flashcard.generate_from_notes",
            input_value=f"tag={tag} note_ids={note_ids} count={count} difficulty={difficulty}",
        ) as span:
            span.set_attribute("flashcard.source", "note")
            span.set_attribute("flashcard.requested_count", count)
            span.set_attribute("flashcard.difficulty", difficulty)

            raw_concepts = await llm.generate(
                extract_prompt, system=NOTES_CONCEPT_EXTRACT_SYSTEM, stream=False
            )
            domain, concepts = _parse_concept_extract(raw_concepts)
            concepts = concepts[:count]

            if not concepts:
                return []

            # Pass 2: generate one typed card per concept, grounded against original text.
            card_prompt = NOTES_CARD_FROM_CONCEPTS_TMPL.format(
                domain=domain,
                difficulty=difficulty,
                difficulty_guidelines=_DIFFICULTY_GUIDELINES.get(difficulty, ""),
                concepts_json=json.dumps(concepts, ensure_ascii=False),
                text=combined_text,
            )
            raw = await llm.generate(
                card_prompt, system=NOTES_CARD_FROM_CONCEPTS_SYSTEM, stream=False
            )
            cards_data = _parse_llm_response(raw, "notes")
            span.set_attribute("flashcard.generated_count", len(cards_data))

        now = datetime.now(UTC)
        flashcards: list[FlashcardModel] = []
        for item in cards_data:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question", "")).strip()
            answer = str(item.get("answer", "")).strip()
            source_excerpt = str(item.get("source_excerpt", "")).strip()
            if not question or not answer:
                continue
            card = FlashcardModel(
                id=str(uuid.uuid4()),
                document_id=None,
                chunk_id=None,
                source="note",
                question=question,
                answer=answer,
                source_excerpt=source_excerpt,
                difficulty=difficulty,
                fsrs_state="new",
                fsrs_stability=0.0,
                fsrs_difficulty=0.0,
                due_date=now,
                reps=0,
                lapses=0,
                created_at=now,
            )
            session.add(card)
            await _sync_flashcard_fts(card, session)
            flashcards.append(card)

        if flashcards:
            await session.commit()
            for card in flashcards:
                await session.refresh(card)

        return flashcards

    async def generate_from_collection(
        self,
        collection_id: str,
        count_per_note: int,
        difficulty: Literal["easy", "medium", "hard"],
        session: AsyncSession,
        force_regenerate: bool = False,
    ) -> dict:
        """Generate flashcards for every note in a collection with hash-based deduplication.

        Each note is processed sequentially (I-1: no asyncio.gather with shared session).
        Returns {created: int, skipped: int, deck: str}.
        """
        llm = get_llm_service()

        # 1. Fetch collection name
        coll_result = await session.execute(
            select(NoteCollectionModel).where(NoteCollectionModel.id == collection_id)
        )
        collection = coll_result.scalar_one_or_none()
        if collection is None:
            raise ValueError(f"Collection {collection_id!r} not found")

        deck_name = collection.name

        # 2. Fetch member note_ids
        member_result = await session.execute(
            select(NoteCollectionMemberModel.note_id).where(
                NoteCollectionMemberModel.collection_id == collection_id
            )
        )
        note_ids = [row[0] for row in member_result.all()]

        created = 0
        skipped = 0

        # 3. Process each note sequentially
        for note_id in note_ids:
            note_result = await session.execute(
                select(NoteModel).where(NoteModel.id == note_id)
            )
            note = note_result.scalar_one_or_none()
            if note is None or not note.content:
                continue

            content_hash = hashlib.sha256(
                note.content[:500].encode()
            ).hexdigest()[:16]

            if not force_regenerate:
                count_result = await session.execute(
                    select(func.count()).select_from(FlashcardModel).where(
                        FlashcardModel.deck == deck_name,
                        FlashcardModel.source == "note",
                        FlashcardModel.source_content_hash == content_hash,
                    )
                )
                existing = count_result.scalar_one()
                if existing > 0:
                    skipped += 1
                    continue

            combined_text = note.content[:_CHUNK_CHAR_LIMIT]
            # Pass 1: extract typed concepts.
            raw_concepts = await llm.generate(
                NOTES_CONCEPT_EXTRACT_TMPL.format(
                    max_concepts=max(count_per_note, 8),
                    text=combined_text,
                ),
                system=NOTES_CONCEPT_EXTRACT_SYSTEM,
                stream=False,
            )
            domain, concepts = _parse_concept_extract(raw_concepts)
            concepts = concepts[:count_per_note]
            if not concepts:
                continue

            # Pass 2: generate one typed card per concept, grounded against original text.
            raw = await llm.generate(
                NOTES_CARD_FROM_CONCEPTS_TMPL.format(
                    domain=domain,
                    difficulty=difficulty,
                    difficulty_guidelines=_DIFFICULTY_GUIDELINES.get(difficulty, ""),
                    concepts_json=json.dumps(concepts, ensure_ascii=False),
                    text=combined_text,
                ),
                system=NOTES_CARD_FROM_CONCEPTS_SYSTEM,
                stream=False,
            )
            cards_data = _parse_llm_response(raw, note_id)

            now = datetime.now(UTC)
            for item in cards_data:
                if not isinstance(item, dict):
                    continue
                question = str(item.get("question", "")).strip()
                answer = str(item.get("answer", "")).strip()
                source_excerpt = str(item.get("source_excerpt", "")).strip()
                if not question or not answer:
                    continue
                card = FlashcardModel(
                    id=str(uuid.uuid4()),
                    document_id=None,
                    chunk_id=None,
                    source="note",
                    deck=deck_name,
                    source_content_hash=content_hash,
                    note_id=note_id,
                    question=question,
                    answer=answer,
                    source_excerpt=source_excerpt,
                    difficulty=difficulty,
                    fsrs_state="new",
                    fsrs_stability=0.0,
                    fsrs_difficulty=0.0,
                    due_date=now,
                    reps=0,
                    lapses=0,
                    created_at=now,
                )
                session.add(card)
                await _sync_flashcard_fts(card, session)
                created += 1

            await session.commit()

        return {"created": created, "skipped": skipped, "deck": deck_name}

    async def generate_from_gaps(
        self,
        gaps: list[str],
        document_id: str,
        session: AsyncSession,
    ) -> tuple[int, list[str]]:
        """Generate one flashcard per gap using bounded LLM concurrency (semaphore=5).

        Skips gaps whose LLM response cannot be parsed.
        Raises litellm.ServiceUnavailableError if Ollama is unreachable.
        Returns (created_count, card_ids).
        """
        llm = get_llm_service()
        semaphore = asyncio.Semaphore(5)

        async def _generate_one(gap: str) -> FlashcardModel | None:
            async with semaphore:
                prompt = GAP_FLASHCARD_USER_TMPL.format(gap=gap)
                raw = await llm.generate(prompt, system=GAP_FLASHCARD_SYSTEM, stream=False)
                item = _parse_gap_flashcard(raw, gap)
                if item is None:
                    return None
                now = datetime.now(UTC)
                return FlashcardModel(
                    id=str(uuid.uuid4()),
                    document_id=document_id if document_id else None,
                    chunk_id=None,
                    source="gap",
                    deck="gaps",
                    question=item["front"].strip(),
                    answer=item["back"].strip(),
                    source_excerpt=gap,
                    fsrs_state="new",
                    fsrs_stability=0.0,
                    fsrs_difficulty=0.0,
                    due_date=now,
                    reps=0,
                    lapses=0,
                    created_at=now,
                )

        raw_results = await asyncio.gather(
            *[_generate_one(g) for g in gaps], return_exceptions=True
        )
        # Re-raise Ollama-offline errors so the router can map them to 503.
        # Any other unexpected exception is logged and skipped (same policy as malformed JSON).
        for exc in raw_results:
            if isinstance(exc, (litellm.ServiceUnavailableError, litellm.APIConnectionError)):
                raise exc
            if isinstance(exc, BaseException):
                logger.warning(
                    "generate_from_gaps: unexpected error for a gap, skipping: %s", exc
                )
        results: list[FlashcardModel | None] = [
            r for r in raw_results if not isinstance(r, BaseException)
        ]
        cards = [r for r in results if r is not None]
        ids: list[str] = []
        for card in cards:
            session.add(card)
            await _sync_flashcard_fts(card, session)
            ids.append(card.id)
        if cards:
            await session.commit()
            logger.info(
                "generate_from_gaps: created %d flashcards from %d gaps",
                len(cards),
                len(gaps),
            )
        return len(cards), ids


    async def generate_from_feynman_gaps(
        self,
        gaps: list[str],
        document_id: str,
        session: AsyncSession,
    ) -> tuple[int, list[str]]:
        """Generate concept_explanation flashcards from Feynman session gaps.

        Identical to generate_from_gaps but sets source='feynman',
        deck='feynman', flashcard_type='concept_explanation'.
        Raises litellm.ServiceUnavailableError if Ollama is unreachable.
        Returns (created_count, card_ids).
        """
        llm = get_llm_service()
        semaphore = asyncio.Semaphore(5)

        async def _generate_one(gap: str) -> FlashcardModel | None:
            async with semaphore:
                prompt = GAP_FLASHCARD_USER_TMPL.format(gap=gap)
                raw = await llm.generate(prompt, system=GAP_FLASHCARD_SYSTEM, stream=False)
                item = _parse_gap_flashcard(raw, gap)
                if item is None:
                    return None
                now = datetime.now(UTC)
                return FlashcardModel(
                    id=str(uuid.uuid4()),
                    document_id=document_id if document_id else None,
                    chunk_id=None,
                    source="feynman",
                    deck="feynman",
                    flashcard_type="concept_explanation",
                    question=item["front"].strip(),
                    answer=item["back"].strip(),
                    source_excerpt=gap,
                    fsrs_state="new",
                    fsrs_stability=0.0,
                    fsrs_difficulty=0.0,
                    due_date=now,
                    reps=0,
                    lapses=0,
                    created_at=now,
                )

        raw_results = await asyncio.gather(
            *[_generate_one(g) for g in gaps], return_exceptions=True
        )
        for exc in raw_results:
            if isinstance(exc, (litellm.ServiceUnavailableError, litellm.APIConnectionError)):
                raise exc
            if isinstance(exc, BaseException):
                logger.warning(
                    "generate_from_feynman_gaps: unexpected error for a gap, skipping: %s", exc
                )
        results: list[FlashcardModel | None] = [
            r for r in raw_results if not isinstance(r, BaseException)
        ]
        cards = [r for r in results if r is not None]
        ids: list[str] = []
        for card in cards:
            session.add(card)
            await _sync_flashcard_fts(card, session)
            ids.append(card.id)
        if cards:
            await session.commit()
            logger.info(
                "generate_from_feynman_gaps: created %d flashcards from %d gaps",
                len(cards),
                len(gaps),
            )
        return len(cards), ids

    async def generate_from_graph(
        self,
        document_id: str,
        k: int,
        session: AsyncSession,
        cards_per_pair: int = 1,
    ) -> list[FlashcardModel]:
        """Generate flashcards from Kuzu entity relationship pairs.

        For each of the top-k entity pairs (by edge weight), fetches shared
        chunk context and calls LiteLLM with a relationship-framing prompt.
        Falls through gracefully when Kuzu is empty or Ollama is unreachable.
        """
        from app.services.graph import get_graph_service  # noqa: PLC0415

        llm = get_llm_service()
        graph = get_graph_service()

        # Fetch top-k pairs by confidence (RELATED_TO) -- fall back to CO_OCCURS if empty
        pairs_4 = graph.get_related_entity_pairs_for_document(document_id, limit=k)
        if pairs_4:
            pairs: list[tuple[str, str, str, float]] = pairs_4
        else:
            co_pairs = graph.get_co_occurring_pairs_for_document(document_id, limit=k)
            pairs = [(a, b, "co-occurs", w) for a, b, w in co_pairs]

        if not pairs:
            logger.info("generate_from_graph: no entity pairs found for doc=%s", document_id)
            return []

        semaphore = asyncio.Semaphore(5)

        async def _generate_one(
            name_a: str, name_b: str, relation_label: str
        ) -> list[FlashcardModel]:
            async with semaphore:
                from app.services.retriever import get_retriever  # noqa: PLC0415

                retriever = get_retriever()
                query = f"{name_a} {name_b}"
                scored_chunks = await retriever.retrieve(
                    query=query, document_ids=[document_id], k=5
                )
                if not scored_chunks:
                    return []

                context = "\n\n".join(c.text for c in scored_chunks)[:_CHUNK_CHAR_LIMIT]
                first_chunk_id = scored_chunks[0].chunk_id

                prompt = GRAPH_FLASHCARD_USER_TMPL.format(
                    name_a=name_a,
                    name_b=name_b,
                    relation_label=relation_label or "related",
                    context=context,
                    count=cards_per_pair,
                )
                raw = await llm.generate(prompt, system=GRAPH_FLASHCARD_SYSTEM, stream=False)
                cards_data = _parse_llm_response(raw, document_id)

                now = datetime.now(UTC)
                cards: list[FlashcardModel] = []
                for item in cards_data:
                    if not isinstance(item, dict):
                        continue
                    question = str(item.get("question", "")).strip()
                    answer = str(item.get("answer", "")).strip()
                    source_excerpt = str(item.get("source_excerpt", "")).strip()
                    if not question or not answer:
                        continue
                    cards.append(
                        FlashcardModel(
                            id=str(uuid.uuid4()),
                            document_id=document_id,
                            chunk_id=first_chunk_id,
                            source="graph",
                            deck="graph",
                            question=question,
                            answer=answer,
                            source_excerpt=source_excerpt,
                            difficulty="medium",
                            fsrs_state="new",
                            fsrs_stability=0.0,
                            fsrs_difficulty=0.0,
                            due_date=now,
                            reps=0,
                            lapses=0,
                            created_at=now,
                        )
                    )
                return cards

        raw_results = await asyncio.gather(
            *[_generate_one(a, b, label) for a, b, label, _conf in pairs],
            return_exceptions=True,
        )

        all_cards: list[FlashcardModel] = []
        for res in raw_results:
            if isinstance(res, (litellm.ServiceUnavailableError, litellm.APIConnectionError)):
                raise res  # type: ignore[misc]
            if isinstance(res, BaseException):
                logger.warning("generate_from_graph: error for a pair: %s", res)
                continue
            all_cards.extend(res)  # type: ignore[arg-type]

        for card in all_cards:
            session.add(card)
            await _sync_flashcard_fts(card, session)
        if all_cards:
            await session.commit()
            for card in all_cards:
                await session.refresh(card)
            logger.info(
                "generate_from_graph: created %d cards for doc=%s", len(all_cards), document_id
            )

        return all_cards


    async def generate_technical(
        self,
        document_id: str,
        scope: Literal["full", "section"],
        section_heading: str | None,
        count: int,
        session: AsyncSession,
    ) -> list[FlashcardModel]:
        """Generate Bloom's-taxonomy-typed flashcards for tech_book/tech_article documents.

        Uses TECH_FLASHCARD_SYSTEM exclusively. Stores flashcard_type and bloom_level
        on every generated card.
        """
        llm = get_llm_service()

        doc_result = await session.execute(
            select(DocumentModel).where(DocumentModel.id == document_id)
        )
        doc = doc_result.scalar_one_or_none()
        content_type = doc.content_type if doc else "unknown"

        chunks = await _fetch_chunks(document_id, scope, section_heading, session, content_type)
        if not chunks:
            return []

        # Determine context signals for the prompt
        has_code = any(c.has_code for c in chunks)
        admonition_type: str | None = None
        if scope == "section" and section_heading:
            sec_result = await session.execute(
                select(SectionModel)
                .where(SectionModel.document_id == document_id)
                .where(SectionModel.heading == section_heading)
                .limit(1)
            )
            sec = sec_result.scalar_one_or_none()
            if sec:
                admonition_type = sec.admonition_type

        combined_text, first_chunk_id = _build_text(chunks)
        if not combined_text:
            return []

        prompt = TECH_FLASHCARD_USER_TMPL.format(
            count=count,
            section_heading=section_heading or "(none)",
            has_code=str(has_code),
            admonition_type=admonition_type or "(none)",
            text=combined_text,
        )

        with trace_chain(
            "flashcard.generate_technical",
            input_value=f"doc={document_id} scope={scope} count={count}",
        ) as span:
            span.set_attribute("flashcard.document_id", document_id)
            span.set_attribute("flashcard.scope", scope)
            span.set_attribute("flashcard.requested_count", count)
            span.set_attribute("flashcard.mode", "technical")

            raw = await llm.generate(prompt, system=TECH_FLASHCARD_SYSTEM, stream=False)
            cards_data = _parse_llm_response(raw, document_id)
            span.set_attribute("flashcard.generated_count", len(cards_data))

        now = datetime.now(UTC)
        flashcards: list[FlashcardModel] = []
        for item in cards_data:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question", "")).strip()
            answer = str(item.get("answer", "")).strip()
            source_excerpt = str(item.get("source_excerpt", "")).strip()
            flashcard_type = str(item.get("flashcard_type", "definition")).strip()
            raw_bloom = item.get("bloom_level")
            # Coerce bloom_level defensively: LLM may return int, float, or "4" string
            if isinstance(raw_bloom, (int, float)):
                bloom_level: int | None = int(raw_bloom)
            elif isinstance(raw_bloom, str) and raw_bloom.isdigit():
                bloom_level = int(raw_bloom)
            else:
                bloom_level = None
            if not question or not answer:
                continue
            card = FlashcardModel(
                id=str(uuid.uuid4()),
                document_id=document_id,
                chunk_id=first_chunk_id,
                question=question,
                answer=answer,
                source_excerpt=source_excerpt,
                difficulty="medium",
                fsrs_state="new",
                fsrs_stability=0.0,
                fsrs_difficulty=0.0,
                due_date=now,
                reps=0,
                lapses=0,
                created_at=now,
                flashcard_type=flashcard_type,
                bloom_level=bloom_level,
            )
            session.add(card)
            await _sync_flashcard_fts(card, session)
            flashcards.append(card)

        if flashcards:
            await session.commit()
            for card in flashcards:
                await session.refresh(card)

        return flashcards


    async def generate_cloze(
        self,
        section_id: str,
        count: int,
        session: AsyncSession,
    ) -> list[FlashcardModel]:
        """Generate cloze deletion flashcards for a section.

        Prompts the LLM to produce {{term}} fill-in-the-blank sentences.
        Validates that each card has at least one blank. Retries once if the
        first response contains zero valid cards. Cards whose cloze_text has
        no {{}} markers are skipped.

        question = cloze_text with {{term}} replaced by [____] (for list views)
        answer = comma-separated terms from the blanks
        cloze_text = raw {{term}} text for frontend rendering
        """
        llm = get_llm_service()

        chunk_result = await session.execute(
            select(ChunkModel)
            .where(ChunkModel.section_id == section_id)
            .order_by(ChunkModel.chunk_index)
        )
        chunks = list(chunk_result.scalars().all())
        if not chunks:
            return []

        document_id = chunks[0].document_id
        first_chunk_id = chunks[0].id

        combined_text, _ = _build_text(chunks)
        if not combined_text:
            return []

        prompt = CLOZE_USER_TMPL.format(count=count, text=combined_text)

        with trace_chain(
            "flashcard.generate_cloze",
            input_value=f"section={section_id} count={count}",
        ) as span:
            span.set_attribute("flashcard.section_id", section_id)
            span.set_attribute("flashcard.requested_count", count)
            span.set_attribute("flashcard.mode", "cloze")

            raw = await llm.generate(prompt, system=CLOZE_SYSTEM, stream=False)
            items = _parse_cloze_llm_response(raw)

            if not items:
                logger.warning(
                    "generate_cloze: no valid cards on first attempt for section=%s, retrying",
                    section_id,
                )
                raw2 = await llm.generate(prompt, system=CLOZE_SYSTEM, stream=False)
                items = _parse_cloze_llm_response(raw2)

            span.set_attribute("flashcard.generated_count", len(items))

        now = datetime.now(UTC)
        flashcards: list[FlashcardModel] = []
        for item in items:
            cloze_text = str(item.get("cloze_text", "")).strip()
            source_excerpt = str(item.get("source_excerpt", "")).strip()
            blanks = _parse_cloze_text(cloze_text)
            if not blanks:
                continue
            question = _build_cloze_question(cloze_text)
            answer = ", ".join(blanks)
            card = FlashcardModel(
                id=str(uuid.uuid4()),
                document_id=document_id,
                chunk_id=first_chunk_id,
                source="document",
                deck="default",
                question=question,
                answer=answer,
                source_excerpt=source_excerpt,
                difficulty="medium",
                is_user_edited=False,
                fsrs_state="new",
                fsrs_stability=0.0,
                fsrs_difficulty=0.0,
                due_date=now,
                reps=0,
                lapses=0,
                created_at=now,
                flashcard_type="cloze",
                bloom_level=None,
                cloze_text=cloze_text,
            )
            session.add(card)
            await _sync_flashcard_fts(card, session)
            flashcards.append(card)

        if flashcards:
            await session.commit()
            for card in flashcards:
                await session.refresh(card)

        return flashcards


_flashcard_service: FlashcardService | None = None


def get_flashcard_service() -> FlashcardService:
    global _flashcard_service  # noqa: PLW0603
    if _flashcard_service is None:
        _flashcard_service = FlashcardService()
    return _flashcard_service
