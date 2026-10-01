"""Grounded Q&A: prompts, query rewriting, and citation parsing and grounding.

The SSE stream that drives the chat graph and calls these is app/runtime/qa_stream.py.
"""

import json
import logging
import re

from app.services.graph import get_graph_service
from app.services.intent import matches_summary_request
from app.services.llm import get_llm_service
from app.types import ScoredChunk

logger = logging.getLogger(__name__)

NOT_FOUND_SENTINEL = "NOT_FOUND_IN_CONTENT"

# Query rewriting — resolve vague pronouns via graph entity lookup

VAGUE_REF_RE = re.compile(
    r"\b(they|he|she|it|them|the author|the speaker|the protagonist|"
    r"the character|the narrator|the writer|both|the two|someone|anyone)\b",
    re.IGNORECASE,
)

_REWRITE_SYSTEM = (
    "Rewrite the question replacing vague references with specific names from the list. "
    "Return only the rewritten question, no explanation."
)


async def _maybe_rewrite_query(
    question: str, document_ids: list[str] | None, prior_context: str | None = None
) -> str:
    """Return a (possibly rewritten) query with vague references resolved.

    Contract:
    - No vague refs detected → returns question unchanged (0 LLM calls, 0 graph queries).
    - document_ids is None (all-docs scope) → returns question unchanged.
    - The graph has 0 entities → returns question unchanged.
    - LLM fails → logs warning and returns question unchanged (non-fatal).
    - prior_context: last user turn from conversation history — prepended to the
      rewrite prompt so the LLM can resolve vague follow-up pronouns.
    """
    if VAGUE_REF_RE.search(question) is None:
        return question
    if document_ids is None:
        return question
    try:
        entity_names = await get_graph_service().get_entities_for_documents(document_ids)
    except Exception:
        logger.warning("_maybe_rewrite_query: graph lookup failed", exc_info=True)
        return question
    if not entity_names:
        return question
    try:
        llm = get_llm_service()
        prompt = f"Question: {question}\nAvailable names: {', '.join(entity_names)}"
        if prior_context:
            prompt = f"Prior exchange:\n{prior_context}\n\n{prompt}"
        result = await llm.generate(prompt, system=_REWRITE_SYSTEM, stream=False)
        rewritten = str(result).strip()
        if rewritten:
            return rewritten
    except Exception:
        logger.warning("_maybe_rewrite_query: LLM rewrite failed", exc_info=True)
    return question


async def _fill_citation_locations(citations: list[dict]) -> None:
    """Fill `section_heading` and `page` on each citation, in place.

    Resolved from the chunk's row rather than from the retrieved chunk, which
    never carries either. `page` stays the navigable sheet number the viewer
    scrolls to; `pdf_page_label` (what the sheet is printed as) is carried by
    `source_citations` and is not part of this shape.
    """
    from app.repos.document_repo import fetch_chunk_locations  # noqa: PLC0415

    chunk_ids = [c["chunk_id"] for c in citations if c.get("chunk_id")]
    if not chunk_ids:
        return
    locations = await fetch_chunk_locations(chunk_ids)
    for c in citations:
        loc = locations.get(c.get("chunk_id") or "")
        if loc is None:
            continue
        if loc.heading and not (c.get("section_heading") or "").strip():
            c["section_heading"] = loc.heading
        if loc.pdf_page and not c.get("page"):
            c["page"] = loc.pdf_page


def _enrich_citation_titles(
    citations: list[dict],
    chunks: list[ScoredChunk],
    doc_titles: dict[str, str],
    scope: str,
) -> list[dict]:
    """Populate (or clear) document_title in each citation.

    scope='single' — set document_title=None on all citations (redundant when
    the user is already reading a specific document).

    scope='all' — name the document each citation actually came from.

    A marker citation already carries the `document_id` of the chunk it was
    resolved from, so that is what names it. The previous lookup matched on
    (section_heading, page) instead, and every retrieved chunk carries
    ("", 0) -- see `fetch_chunk_locations` -- so the index collapsed to a
    single entry and "first match wins" relabelled every citation with the
    first chunk's document. Measured on two chunks from two documents, the
    second was attributed to the first. Fall back to the chunk match only for
    citations with no document_id (a retyped excerpt that never resolved).
    """
    if scope == "single":
        for c in citations:
            c["document_title"] = None
        return citations

    chunk_docs = {chunk.chunk_id: chunk.document_id for chunk in chunks}

    # Retained for citations carrying neither id -- a retyped excerpt that never
    # resolved to a marker. Keyed only on a *non-empty* heading: every retrieved
    # chunk carries ("", 0), so an unguarded key made one entry that relabelled
    # every citation with the first chunk's document.
    heading_index: dict[tuple[str, int], str] = {}
    for chunk in chunks:
        heading = (chunk.section_heading or "").strip()
        if not heading:
            continue
        heading_index.setdefault((heading, chunk.page), chunk.document_id)

    for c in citations:
        doc_id = c.get("document_id") or chunk_docs.get(c.get("chunk_id") or "")
        if not doc_id:
            heading = (c.get("section_heading") or "").strip()
            if heading:
                doc_id = heading_index.get((heading, int(c.get("page") or 0)))
        if doc_id and doc_id in doc_titles:
            c["document_title"] = doc_titles[doc_id]

    return citations


# Deciding to ATTACH the executive summary is a looser judgement than routing to
# the summary node: it only adds context, so a false positive costs prompt budget
# rather than answering the wrong question. It must nonetheless be a superset of
# the routing set, or the two disagree -- "Recap the document" counted as summary
# intent here while routing sent it to search, because the lists were maintained
# separately and drifted.
_LOOSE_SUMMARY_KEYWORDS: frozenset[str] = frozenset({"brief", "briefly", "summaries", "main idea"})


def _should_use_summary(question: str) -> bool:
    """Return True if the question has summary-intent keywords."""
    q = question.lower()
    return matches_summary_request(question) or any(kw in q for kw in _LOOSE_SUMMARY_KEYWORDS)


# Every prompt that asks for citations states this. Naming a source is a pointer,
# not a transcription: asking the model to retype the quote produced narration and
# commentary in the excerpt field, and then telling it to copy verbatim made it
# stop citing rather than risk it. The backend fills the excerpt from the chunk
# the marker names, so the model never has to reproduce text (I-33).
CITATION_RULE = (
    "Each passage in the context is labelled with a marker like [S1]. Cite by "
    'marker: {"source":"S1"}. Cite every passage you actually used, and only '
    "those. Do not copy the passage text — the source text is filled in for you. "
    'Optionally add {"quote":"..."} with a few words from the passage to point at '
    "the relevant sentence."
)

# A question can assume what its document contradicts ("Mercury's plan" when the plan is
# Jove's). Saying "not found" then tells the user the document is silent; it is not (#158).
PREMISE_RULE = (
    "If the question assumes something the context contradicts, say so first, then answer "
    "from what the context says and cite the passage that contradicts it. That is an "
    f"answer, never {NOT_FOUND_SENTINEL}. "
)


QA_SYSTEM_PROMPT = (
    "You are a grounded knowledge assistant. "
    "Answer only using the provided context. "
    f"{PREMISE_RULE}"
    f"If the answer is not present, respond exactly: {NOT_FOUND_SENTINEL}. "
    "Do not speculate. "
    "Write your answer as Markdown prose (use **bold**, bullet lists, and headings where helpful). "
    "Then on a new line write this JSON: "
    '{"citations":[{"source":"S1"}],"confidence":"high|medium|low"}\n'
    f"{CITATION_RULE}"
)

# A subject-less notes question is answered from the most recent notes (#141). No
# sentinel: notes_node takes this path only when there are notes to report.
QA_NOTES_RECENT_SYSTEM_PROMPT = (
    "You are a knowledge assistant answering from the user's own notes. "
    "The user asked what they noted without naming a specific subject, so the context "
    "holds their most recent notes. Say that these are their most recent notes, then "
    "report what the notes say. Use only the notes in the context and add nothing "
    "that is not in them. "
    "Write your answer as Markdown prose. "
    "Then on a new line write this JSON: "
    '{"citations":[],"confidence":"high|medium|low"}'
)

# Creative mode: opt-in via the UI toggle. Still grounded in the learner's own
# retrieved material (synthesize_node returns not_found when nothing is retrieved),
# but the model is licensed to invent narrative framing/voice and the sampling
# temperature is raised. Deliberately omits the NOT_FOUND sentinel: creative
# requests over real grounding should always produce a piece, not refuse.
QA_CREATIVE_SYSTEM_PROMPT = (
    "You are Lumen, an imaginative learning companion. The user wants a creative piece "
    "(a story, poem, dialogue, analogy, or the like) grounded in their own material below. "
    "Draw the facts, themes, characters, and details from the provided context. Invent the "
    "narrative framing, structure, and voice freely -- but never invent facts that contradict "
    "the material. Write vivid, engaging Markdown prose; be playful and original while staying "
    "true to the source. "
    "Then on a new line write this JSON: "
    '{"citations":[{"source":"S1"}],"confidence":"high|medium|low"}\n'
    f"{CITATION_RULE}"
)

# Higher sampling temperature for creative mode. Models that reject temperature
# (e.g. gpt-5) drop it harmlessly via litellm.drop_params.
QA_CREATIVE_TEMPERATURE = 0.85

# Direct mode: opt-in via the UI Direct toggle. Bypasses retrieval over the library
# and sends the question straight to the selected model. Deliberately omits citation instructions
# and the NOT_FOUND sentinel: direct answers are ungrounded general-knowledge responses.
QA_DIRECT_SYSTEM_PROMPT = (
    "You are Lumen, a knowledgeable learning companion. Answer the user's question directly "
    "from your general knowledge. Be accurate, clear, and well-structured. "
    "Write your answer in Markdown prose (use headings, bold text, lists, and code blocks). "
    "Do not cite document passages or invent citation markers."
)


# Used only for factual intent: falls back to general knowledge with a disclaimer
# when the document doesn't contain the answer.
QA_FACTUAL_SYSTEM_PROMPT = (
    "You are a knowledgeable learning assistant. "
    "Prefer the provided context when answering. "
    f"{PREMISE_RULE}"
    "If the answer is not in the provided context, answer from your general knowledge "
    "and begin that part of your answer with: 'This is not covered in your documents, but: '. "
    f"Only respond exactly: {NOT_FOUND_SENTINEL} if you have no knowledge of the topic whatsoever. "
    "Write your answer as Markdown prose (use **bold**, bullet lists, and headings where helpful). "
    "Then on a new line write this JSON: "
    '{"citations":[{"source":"S1"}],"confidence":"high|medium|low"}\n'
    f"{CITATION_RULE} A part of the answer that came from your general knowledge "
    "has no passage to cite."
)


def _marker_prefix_holdback(text: str, markers: tuple[str, ...]) -> int:
    """Length of the longest suffix of ``text`` that is a prefix of some marker.

    Used while streaming to hold back only the tail that might be the start of a
    stop marker split across tokens, so prose flushes immediately.
    """
    longest = 0
    for marker in markers:
        for k in range(min(len(text), len(marker) - 1), 0, -1):
            if text[-k:] == marker[:k]:
                longest = max(longest, k)
                break
    return longest


def _salvage_truncated_answer(json_text: str) -> str:
    """Recover the "answer" string from a truncated/malformed JSON block.

    Local models sometimes embed the whole answer in JSON (Style B) and then hit
    the generation token limit mid-block, so json.loads fails on every repair.
    The answer text itself is still intact up to the truncation point — walk the
    JSON string manually (honouring escapes) instead of throwing it away.
    """
    m = re.search(r'"answer"\s*:\s*"', json_text)
    if not m:
        return ""
    body = json_text[m.end() :]
    out: list[str] = []
    escapes = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            out.append(escapes.get(body[i + 1], body[i + 1]))
            i += 2
            continue
        if ch == '"':
            break
        out.append(ch)
        i += 1
    return "".join(out).strip()


# A bare heading the model sometimes writes just before its citation JSON
# (optionally markdown-bold/italic): "**Citations:**", "Sources:", "References".
_CITATION_HEADING_RE = re.compile(
    r"^[*_\s>#-]*(citations?|sources?|references?)\s*:?\s*[*_\s]*$",
    re.IGNORECASE,
)


def _is_placeholder_citation(c: dict) -> bool:
    """True when a citation is just the prompt's format example echoed back
    (empty or "..." title AND excerpt) — no real reference content."""

    def _blank(v: object) -> bool:
        return not str(v or "").strip().strip(".").strip()

    # A marker citation carries neither title nor excerpt by design -- both are
    # filled in from the chunk it names -- so it must not read as a placeholder.
    if not _blank(c.get("source")) or not _blank(c.get("chunk")):
        return False
    return _blank(c.get("document_title")) and _blank(c.get("excerpt"))


# A quote is only a quote if the grounding contains it. Models fill `excerpt`
# with narration ("After the mysterious disappearance of the time machine...")
# or with commentary about the context ("The context does not provide specific
# details...") and both render as a source chip indistinguishable from a real
# one. Long quotes are often stitched with ellipses or re-punctuated, so match
# on a contiguous run of normalised tokens rather than the whole string.
_MIN_GROUNDED_RUN_TOKENS = 8


def _normalize_for_match(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def _excerpt_is_grounded(excerpt: str, normalized_grounding: str) -> bool:
    tokens = _normalize_for_match(excerpt).split()
    if not tokens or not normalized_grounding:
        return False
    if len(tokens) <= _MIN_GROUNDED_RUN_TOKENS:
        return " ".join(tokens) in normalized_grounding
    return any(
        " ".join(tokens[i : i + _MIN_GROUNDED_RUN_TOKENS]) in normalized_grounding
        for i in range(len(tokens) - _MIN_GROUNDED_RUN_TOKENS + 1)
    )


_MARKER_RE = re.compile(r"s?(\d+)", re.IGNORECASE)
_EXCERPT_MAX_CHARS = 320

# Shared with the chunk-derived source_citations in synthesize_node so both lists
# under one answer obey one policy. Relieved of having to retype the quote, a
# model cites freely: a 737-character answer came back with 12 chips, each a real
# passage, and `paper` cited every answer it gave (coverage 1.0000) while under
# half those chips supported anything. Availability is not relevance, so rank by
# retrieval score, drop what sits far below the best, then cap.
MAX_CITATIONS = 5
CITATION_REL_RATIO = 0.5
CITATION_MIN_SCORE = 0.01


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])[\"'”’)\]]*\s+")

# Words carry no evidence of what a passage is about, so they must not decide
# which sentence gets shown. Kept deliberately small and domain-neutral.
_EXCERPT_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "his",
        "i",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "she",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "which",
        "who",
        "will",
        "with",
        "you",
        "your",
        "not",
        "no",
        "do",
        "does",
        "did",
        "so",
        "if",
    ]
)


def _content_tokens(text: str) -> set[str]:
    return {
        t
        for t in re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split()
        if len(t) > 2 and t not in _EXCERPT_STOPWORDS
    }


_ENTITY_TAIL_RE = re.compile(r"\[Entities:\s*[^\]]*\]\s*")


def _strip_context_headers(text: str, doc_title: str) -> str:
    """Drop retrieval scaffolding `keyword_index_node` glues onto chunk text.

    The FTS5 index text is `context_header || text || entities_text`
    (`embed.py`'s `keyword_index_node`) so BM25 can match on a title, a
    section heading, or a canonical entity name -- `[Title > Heading]` in
    front, `[Entities: A, B, C]` (`build_entity_tail`) behind. A chunk
    surfaced by the lexical leg of hybrid search returns this glued string as
    its `.text`, not the plain `ChunkModel.text`. Neither marker is document
    content -- the reader's section body never contains either -- so an
    excerpt window that starts on or grows into one puts a string in the
    reader's citation-click highlight (frontend/src/lib/citation/target.ts)
    that cannot exist in the rendered prose, and the whole highlight silently
    fails to place. A neighbour-expanded `source_text` joins several chunks,
    each carrying its own markers, so every occurrence is removed, not just a
    leading one.
    """
    text = _ENTITY_TAIL_RE.sub("", text)
    if not doc_title:
        return text
    pattern = re.compile(r"\[" + re.escape(doc_title) + r"(?:\s*>\s*[^\]]*)?\]\s*")
    return pattern.sub("", text)


def _excerpt_from_chunk(
    chunk_text: str, hint: str = "", answer: str = "", doc_title: str = ""
) -> str:
    """Cut the part of *chunk_text* that bears on *answer*, verbatim.

    Showing the head of the chunk shows the wrong text: a chunk is sized for the
    embedder, so the sentence that carries the claim sits anywhere in it. Measured
    over `book` chips, 12 of 15 excerpts were head cuts, and judging the displayed
    excerpt scored 0.5667 against 0.8667 for the same chips judged on their full
    chunk — the citations were right and the window was wrong.

    *hint* is whatever the model typed as its quote and *answer* is the prose the
    chip sits under. Both are used only to choose which sentences to show, never
    as content, so a paraphrased hint costs relevance and can never put words in
    the source's mouth. *doc_title* names the chunk's own retrieval breadcrumb so
    it can be dropped before any sentence is chosen, never as a source of truth.
    """
    text = " ".join(chunk_text.split())
    text = _strip_context_headers(text, doc_title).strip()
    if not text or len(text) <= _EXCERPT_MAX_CHARS:
        return text
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if not sentences:
        return text[:_EXCERPT_MAX_CHARS].rsplit(" ", 1)[0] + "..."

    target = _content_tokens(answer)
    hint_tokens = _content_tokens(hint)
    if not target and not hint_tokens:
        best = 0
    else:

        def score(sentence: str) -> float:
            tokens = _content_tokens(sentence)
            if not tokens:
                return 0.0
            # Weight the model's own pointer above general answer overlap, and
            # normalise by length so a long sentence does not win on volume.
            overlap = len(tokens & target) + 3 * len(tokens & hint_tokens)
            return overlap / (len(tokens) ** 0.5)

        best = max(range(len(sentences)), key=lambda i: score(sentences[i]))

    # Grow outward from the best sentence while the budget allows, preferring the
    # following sentence so the excerpt reads forward.
    lo = hi = best
    length = len(sentences[best])
    while True:
        nxt = hi + 1
        prv = lo - 1
        grew = False
        if nxt < len(sentences) and length + len(sentences[nxt]) + 1 <= _EXCERPT_MAX_CHARS:
            length += len(sentences[nxt]) + 1
            hi = nxt
            grew = True
        if prv >= 0 and length + len(sentences[prv]) + 1 <= _EXCERPT_MAX_CHARS:
            length += len(sentences[prv]) + 1
            lo = prv
            grew = True
        if not grew:
            break

    window = " ".join(sentences[lo : hi + 1]).strip()
    if len(window) > _EXCERPT_MAX_CHARS:
        window = window[:_EXCERPT_MAX_CHARS].rsplit(" ", 1)[0] + "..."
    # A space after the ellipsis, not fused to the window: synthesize_node's
    # source_citations feed this into word-splitting fuzzy matching
    # (frontend/src/lib/citation/target.ts), where "...The" is a token "The"
    # never occurs in.
    return ("... " if lo > 0 else "") + window


def _resolve_marker_citations(
    citations: list[dict],
    cited_chunks: list[dict],
    doc_titles: dict[str, str],
    answer: str = "",
) -> tuple[list[dict], int]:
    """Fill each marker citation in from the chunk it names.

    The model names a source (`[S2]`) instead of retyping it, so the excerpt is
    verbatim by construction and the citation carries the `chunk_id` needed to
    deep-link. Returns (citations, unresolved_count); a marker pointing at no such
    chunk is dropped, because the source it claims does not exist.
    """
    if not cited_chunks:
        return citations, 0
    resolved: list[dict] = []
    seen_chunk_ids: set[str] = set()
    unresolved = 0
    for c in citations:
        raw = c.get("source") if c.get("source") is not None else c.get("chunk")
        if raw is None:
            resolved.append(c)
            continue
        m = _MARKER_RE.fullmatch(str(raw).strip().strip("[]").strip())
        idx = int(m.group(1)) if m else 0
        if not 1 <= idx <= len(cited_chunks):
            unresolved += 1
            logger.warning("qa: dropped citation naming a source that does not exist: %r", raw)
            continue
        chunk = cited_chunks[idx - 1]
        # Two markers pointing at one chunk are one source, not two chips.
        chunk_key = chunk.get("chunk_id") or f"_idx{idx}"
        if chunk_key in seen_chunk_ids:
            continue
        seen_chunk_ids.add(chunk_key)
        doc_id = chunk.get("document_id", "")
        doc_title = doc_titles.get(doc_id) or c.get("document_title") or ""
        resolved.append(
            {
                "document_title": doc_title,
                "section_heading": chunk.get("section_heading") or "",
                "page": chunk.get("page", 0),
                "excerpt": _excerpt_from_chunk(
                    # Never the packed `text` (a generated section summary can
                    # ride in front of it, I-33) and never `source_text` alone
                    # (search_node's neighbour expansion joins it across a
                    # section boundary by chunk_index, which does not reset
                    # per section -- an excerpt cut from the join can quote
                    # real prose from the PREVIOUS section under this one's
                    # heading). `own_text` is this chunk alone; only chunks
                    # without it (graph_node, comparative_node) fall through.
                    chunk.get("own_text") or chunk.get("source_text") or chunk.get("text", ""),
                    str(c.get("quote") or ""),
                    answer,
                    doc_title,
                ),
                "chunk_id": chunk.get("chunk_id", ""),
                "document_id": doc_id,
                "_score": float(chunk.get("score") or 0.0),
            }
        )
    return resolved, unresolved


def _gate_and_rank_citations(citations: list[dict]) -> list[dict]:
    """Rank chips by retrieval score, drop weak ones, cap the list.

    The same gate `source_citations` has always applied, on the list the model
    chose. A marker citation carries the score of the chunk it names; a legacy
    excerpt citation carries none and cannot be ranked, so it is kept in place
    behind the ranked ones rather than being scored as zero and dropped.

    The single best source always survives: an answer that retrieved something
    should never show zero sources because the gate was strict.
    """
    ranked = [c for c in citations if "_score" in c]
    unranked = [c for c in citations if "_score" not in c]
    if ranked:
        ranked.sort(key=lambda c: c["_score"], reverse=True)
        floor = max(CITATION_MIN_SCORE, ranked[0]["_score"] * CITATION_REL_RATIO)
        kept = [ranked[0]] + [c for c in ranked[1:] if c["_score"] >= floor]
    else:
        kept = []
    out = (kept + unranked)[:MAX_CITATIONS]
    for c in out:
        c.pop("_score", None)
    return out


def _drop_ungrounded_citations(citations: list[dict], grounding_texts: list[str]) -> list[dict]:
    """Drop citations whose excerpt does not occur in the answer's grounding.

    Verified against the grounding the answer was generated from, not the whole
    document: an excerpt the model recited from its own memory of the source is
    still text the answer was not grounded on, and carries no chunk to link to.
    Dropping leaves the answer with fewer chips or none; the chunk-derived
    `source_citations` are unaffected, so the sources panel still stands.
    """
    if not grounding_texts:
        return citations
    normalized = _normalize_for_match(" ".join(grounding_texts))
    kept: list[dict] = []
    for c in citations:
        excerpt = str(c.get("excerpt") or "").strip()
        if not excerpt or _excerpt_is_grounded(excerpt, normalized):
            kept.append(c)
        else:
            logger.warning(
                "qa: dropped ungrounded citation excerpt (%d chars): %.80s",
                len(excerpt),
                excerpt,
            )
    return kept


# The only values a confidence may take. The prompt spells them out as
# `"confidence":"high|medium|low"`, so the spec string itself is a value the
# model can emit and must never be accepted as one.
CONFIDENCE_LEVELS = frozenset({"high", "medium", "low"})


_INLINE_MARKER_RE = re.compile(r"\[S(\d+)\]")


def _inline_marker_citations(answer: str) -> list[dict]:
    """Marker citations for the [S2]s an answer wrote in its prose and left out of
    the JSON block; small models do this, and the answer then showed no source.
    A marker still resolves only to a passage the model was given (I-33)."""
    seen = dict.fromkeys(_INLINE_MARKER_RE.findall(answer))
    return [{"source": f"S{n}"} for n in seen]


def _split_response(full_text: str) -> tuple[str, list[dict], str]:
    """Extract (answer_text, citations, confidence) from the LLM response.

    The LLM is instructed to write prose then append a JSON citations block.
    Two output styles are handled:
      Style A: [prose]\\n{"citations": [...], "confidence": "..."}
      Style B: {"answer": "...", "citations": [...], "confidence": "..."}
               (some models embed the answer inside the JSON)
    Truncated generations (the block never closes) are salvaged rather than
    dropped: the embedded answer is recovered character-wise.
    """
    # Find the last JSON block containing our citations payload.
    json_start = -1
    for pattern in (r'\{\s*"citations"\s*:', r'\{\s*"answer"\s*:'):
        matches = list(re.finditer(pattern, full_text, re.DOTALL))
        if matches:
            json_start = matches[-1].start()
            break

    if json_start == -1:
        answer = full_text.strip()
        # Default confidence based on answer length: short/empty answers are low,
        # substantive answers without a JSON block default to medium.
        confidence = "medium" if len(answer) > 80 else "low"
        return answer, _inline_marker_citations(answer), confidence

    # Parse the JSON block, tolerating truncation.
    parsed: dict = {}
    parse_failed = False
    json_text = full_text[json_start:]
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError:
        parse_failed = True
        end = json_text.rfind("}")
        if end != -1:
            try:
                parsed = json.loads(json_text[: end + 1])
                parse_failed = False
            except json.JSONDecodeError:
                pass

    citations: list[dict] = [c for c in parsed.get("citations", []) if isinstance(c, dict)]
    # Drop placeholder citations: small models often echo the prompt's format
    # example verbatim ({"document_title":"...","excerpt":"...","page":0}) instead
    # of filling it in. Such a citation carries no information and would render as
    # a useless "... · p.0" chip. The grounded source_citations (from retrieved
    # chunks) are the trustworthy reference list.
    citations = [c for c in citations if not _is_placeholder_citation(c)]

    def _strip_json_preamble(text: str) -> str:
        """Remove trailing lines that are label preambles, not answer content:
        a JSON hint ("JSON:", "Here is the JSON:") or a heading the model wrote
        before its citation block ("**Citations:**", "Sources:", "References:")."""
        lines = text.split("\n")
        while lines and (
            re.search(r"\bjson\b", lines[-1], re.IGNORECASE)
            or _CITATION_HEADING_RE.match(lines[-1])
        ):
            lines.pop()
        return "\n".join(lines).strip()

    # Style B: answer is embedded in the JSON.
    if "answer" in parsed and isinstance(parsed["answer"], str):
        answer = _strip_json_preamble(parsed["answer"].strip())
    else:
        # Style A: prose precedes the JSON block.
        # Strip any trailing lines that are format labels, not answer content.
        # LLMs sometimes echo instruction fragments (e.g. "JSON:", "Here is the
        # JSON:", "ONLY JSON (no prose ...):") — these always contain "json".
        answer = _strip_json_preamble(full_text[:json_start].strip())
        if parse_failed:
            salvaged = _salvage_truncated_answer(json_text)
            if len(salvaged) > len(answer):
                answer = salvaged

    confidence = parsed.get("confidence")
    if isinstance(confidence, str):
        confidence = confidence.strip().lower()
    if confidence not in CONFIDENCE_LEVELS:
        # No usable confidence: a truncated block, or the model echoing the
        # format spec back at us. The prompt shows it
        # `"confidence":"high|medium|low"` and a 4B model returns that string
        # verbatim often enough to matter -- it passed a bare "is a non-empty
        # string" test and reached the UI as a confidence level, which is the
        # product's own placeholder being read as its measurement. Fall back to
        # the same length heuristic as the no-JSON path.
        confidence = "medium" if len(answer) > 80 else "low"
    return answer, citations or _inline_marker_citations(answer), confidence
