"""Pure, document-agnostic helpers for generating + filtering golden Q&A.

Extracted from dataset_generator_service so the DB-backed generator and the
file-based eval CLI (evals/generate_golden.py) share one implementation. No
database or document-specific logic lives here — everything operates on plain
source text so it works for any document.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _retrieval_norm(value: str) -> str:
    """Match the retrieval-metric normalisation (smart quotes + whitespace) so the
    golden-quality verbatim check agrees with how HR@5/MRR find hints."""
    value = value.replace("‘", "'").replace("’", "'")
    value = value.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", value).strip().lower()


def golden_dataset_quality(rows: list[dict[str, Any]], source_text: str) -> dict[str, Any]:
    """Deterministic, unbiased quality signals for a golden dataset.

    No LLM judge is used — every number is a reproducible structural check, so the
    score cannot be gamed by or biased toward any model. The dominant signal is
    hint_verbatim_rate: a hint that is not a verbatim substring of the source is
    unretrievable, which would unfairly depress HR@5/MRR for every retriever.
    """
    n = len(rows)
    if n == 0:
        return {"n": 0, "quality_score": 0.0}
    source_norm = _retrieval_norm(source_text)

    def _answer(r: dict) -> str:
        return str(r.get("ground_truth_answer") or r.get("answer") or "")

    verbatim = sum(
        1 for r in rows if _retrieval_norm(str(r.get("context_hint", "")))[:80] in source_norm
    )
    self_contained = sum(
        1
        for r in rows
        if not any(p in str(r.get("question", "")).lower() for p in _DOC_REFERENCE_PHRASES)
    )
    answer_ok = sum(1 for r in rows if len(_answer(r).strip()) >= 10)
    q_words = [len(str(r.get("question", "")).split()) for r in rows]
    mean_len = sum(q_words) / n
    var = sum((w - mean_len) ** 2 for w in q_words) / n
    distinct_personas = len({r.get("persona") for r in rows if r.get("persona")})

    verbatim_rate = verbatim / n
    self_rate = self_contained / n
    answer_rate = answer_ok / n
    # Composite weighted toward retrievability (the fairness guarantee).
    quality_score = 0.5 * verbatim_rate + 0.25 * self_rate + 0.25 * answer_rate
    return {
        "n": n,
        "hint_verbatim_rate": verbatim_rate,
        "self_contained_rate": self_rate,
        "answer_ok_rate": answer_rate,
        "question_len_mean": round(mean_len, 1),
        "question_len_std": round(var**0.5, 1),
        "distinct_personas": distinct_personas,
        "quality_score": quality_score,
    }


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM response did not contain a JSON object")
    return json.loads(stripped[start : end + 1])


_FRONT_BACK_MATTER = frozenset(
    "foreword preface acknowledgments acknowledgement dedication copyright isbn"
    " publisher colophon bibliography index glossary".split()
)


def is_structural_chunk(text: str) -> bool:
    """True for chunks unlikely to yield good content questions: short blocks,
    low alphabetic density (code/tables/captions), and front/back matter."""
    stripped = text.strip()
    if len(stripped) < 200:
        return True
    words = stripped.split()
    if len(words) < 40:
        return True
    alpha_ratio = sum(1 for c in stripped if c.isalpha()) / len(stripped)
    if alpha_ratio < 0.55:
        return True
    lower_words = {w.strip(".,;:\"'").lower() for w in words[:30]}
    if lower_words & _FRONT_BACK_MATTER:
        return True
    header_match = re.match(r"\s*\[([^\]]+)\]", stripped)
    if header_match:
        header = header_match.group(1).lower()
        if any(
            tag in header
            for tag in (
                "foreword", "preface", "acknowledgment", "acknowledgement",
                "dedication", "praise for", "about the author", "introduction",
                "part i.", "part ii.", "part iii.", "part iv.",
            )
        ):
            return True
    return False


_STOPWORDS = frozenset(
    "a an the is are was were be been being have has had do does did will would could should "
    "may might shall can of in on at to for with by from as into through during about above "
    "between but and or nor not if then that this these those it its we our they their i my "
    "what which who when where how".split()
)


def hint_grounded(hint_norm: str, source_norm: str) -> bool:
    """True when >=75% of the non-stopword words in the hint appear in the source."""
    hint_words = [w for w in hint_norm.split() if w not in _STOPWORDS and len(w) > 2]
    if not hint_words:
        return False
    source_words = set(source_norm.split())
    overlap = sum(1 for w in hint_words if w in source_words)
    return overlap / len(hint_words) >= 0.75


def dedupe_by_embedding(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    questions = [c["question"] for c in candidates]
    if len(questions) < 2:
        return candidates
    try:
        import numpy as np  # noqa: PLC0415

        from app.services.embedder import get_embedding_service  # noqa: PLC0415

        vectors = np.array(get_embedding_service().encode(questions), dtype=np.float32)
        norms = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-10)
        kept: list[int] = []
        for idx, vector in enumerate(norms):
            if not kept:
                kept.append(idx)
                continue
            sims = norms[kept] @ vector
            if not bool(np.any(sims > 0.95)):
                kept.append(idx)
        return [candidates[i] for i in kept]
    except Exception:
        logger.debug("embedding dedupe unavailable; falling back to exact-question dedupe")
        seen: set[str] = set()
        unique: list[dict[str, str]] = []
        for candidate in candidates:
            key = normalize_text(candidate["question"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique


# Document-reference phrases: a good golden question tests the subject, never
# "what does the text say". Rejecting these is what separates a knowledge probe
# from reading comprehension.
_DOC_REFERENCE_PHRASES = (
    "according to the text", "according to the guide",
    "according to the source", "according to the passage",
    "according to the author", "according to the document",
    "the text states", "the text says", "the text describes",
    "the text explains", "the text mentions", "the text notes",
    "the text suggests", "the guide states", "the guide describes",
    "the guide mentions", "the source states", "the passage states",
    "the author states", "the author describes", "the author explains",
    "the author mentions", "the author suggests",
    "as stated in", "as described in", "as mentioned in",
    "as noted in", "as explained in",
    "according to this", "this text", "this guide", "this source",
    "this passage", "this document", "this section", "this chapter",
    "the text", "the guide", "the source", "the passage",
    "the document", "the section", "the chapter", "the excerpt",
    "is mentioned", "is listed", "is highlighted", "is described",
    "is stated", "is noted", "is referenced", "is discussed",
    "are mentioned", "are listed", "are highlighted", "are described",
    "are stated", "are noted",
    "what does the source", "what is the main point", "in point ",
    "who wrote", "who is the author", "who authored", "who edited",
    "foreword", "preface", "acknowledgment", "dedication",
    "who dedicated", "copyright", "isbn", "publisher", "published by",
    "edition of", "this book", "the book",
    "page number", "chapter number", "section number",
    "table of contents", "appendix",
)


def quality_filter(
    questions: list[dict[str, Any]],
    source_text: str,
) -> list[dict[str, str]]:
    """Keep only self-contained, source-grounded Q&A. Generic over source text."""
    source_norm = normalize_text(source_text)
    filtered: list[dict[str, str]] = []
    for raw in questions:
        question = str(raw.get("question", "")).strip()
        answer = str(raw.get("answer") or raw.get("ground_truth_answer") or "").strip()
        context_hint = str(raw.get("context_hint", "")).strip()
        if not question or len(answer) < 10 or not context_hint:
            continue
        q_lower = question.lower()
        if any(phrase in q_lower for phrase in _DOC_REFERENCE_PHRASES):
            continue
        if not hint_grounded(normalize_text(context_hint), source_norm):
            continue
        filtered.append(
            {
                "question": question,
                "ground_truth_answer": answer,
                "context_hint": context_hint,
            }
        )
    return dedupe_by_embedding(filtered)


def build_generation_prompt(chunk_text: str, count: int, persona: str | None = None) -> str:
    persona_line = (
        f"\nREADER PERSONA: Write every question the way THIS reader would naturally ask it"
        f" — {persona}. Keep it grounded in the source; do not invent facts.\n"
        if persona
        else ""
    )
    return (
        f"You are simulating {count} REAL people querying an AI study assistant about the material"
        " below. Produce question/answer pairs that feel genuinely human and varied — like a real"
        " chat log, NOT a uniform set of exam cards.\n"
        f"{persona_line}\n"
        "VARY THESE ACROSS THE BATCH (this is the point — do not make them all alike):\n"
        "- FORM: mix terse imperatives ('explain backpropagation', 'walk me through dropout'),"
        " bare keyword queries ('weight decay?', 'adam vs sgd'), full questions, comparisons"
        " ('difference between layer norm and batch norm?'), example requests ('give me an example"
        " of multi-label classification'), and troubleshooting ('why are my hidden units staying"
        " identical even with sgd?').\n"
        "- LENGTH: some very short (2-6 words), some medium, some long and rambling with a bit of"
        " situational context. Do not cluster around one length.\n"
        "- REGISTER: mix formal and casual. For casual/beginner ones, lowercase is fine and an"
        " occasional realistic typo is welcome ('whats the differnce...') as long as it stays"
        " understandable.\n"
        "- ANSWER DEPTH MUST MATCH THE QUESTION: a quick factual question gets a crisp 1-2"
        " sentence answer; an 'explain'/'why'/'how' question gets a thorough answer of several"
        " sentences that actually teaches. Never make every answer the same length.\n\n"
        "HARD RULES:\n"
        "- Self-contained: ask about the SUBJECT, never the document. No 'the text', 'the passage',"
        " 'this section', 'the author', or any chapter/figure/exercise reference.\n"
        "- Grounded: the answer must be fully supported by the source — invent nothing, and base it"
        " only on what this passage actually says.\n"
        "- Answers state facts directly. Never write 'the passage says', 'the source states', or"
        " 'according to the text' in the answer — just give the answer as established knowledge.\n"
        "- context_hint must be a verbatim phrase (5-20 words) copied exactly from the source.\n"
        "- No questions about authorship, copyright, ISBN, or publication metadata.\n\n"
        "Return ONLY valid JSON:\n"
        '{"questions":[{"question":"...","answer":"...","context_hint":"verbatim"}]}\n\n'
        f"SOURCE:\n{chunk_text[:6000]}"
    )
