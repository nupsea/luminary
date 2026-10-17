"""Repair misheard terms in a transcript against a glossary, never by rewriting it (I-66).

Code proposes every candidate span; the model only picks between the sentence as heard
and with the glossary term, so it cannot introduce a term or touch other text. Terms
come from the source's own metadata and the user's vocabulary; nothing here supplies one.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.repos.transcript_repo import fetch_transcript_inputs, save_transcript_corrections
from app.services.llm_admission import awaited
from app.services.settings_service import get_local_chat_model

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'.+-]*[A-Za-z0-9+]|[A-Za-z0-9]")
# A glossary entry longer than this is a title, not a term anyone mishears whole.
_MAX_TERM_WORDS = 3
# Below three letters every same-initial word scores alike ("an" vs "AI" is 0.5).
_MIN_TERM_CHARS = 3
# Recall gate only; the model is the precision gate. Bracketed by "rack" -> "RAG"
# (0.571, kept) and "Dara engineering is" -> "DataEngBytes" (0.552, refused); I-66.
MIN_SIMILARITY = 0.56
_LENGTH_RATIO = (0.6, 1.6)


@dataclass(frozen=True)
class Candidate:
    segment: int
    start: int
    end: int
    heard: str
    term: str
    score: float


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.casefold())


def normalize_terms(terms: list[str]) -> list[str]:
    """Stripped, de-duplicated ignoring case, first spelling kept."""
    seen: set[str] = set()
    kept: list[str] = []
    for raw in terms:
        term = " ".join(raw.split())
        if term and term.casefold() not in seen:
            seen.add(term.casefold())
            kept.append(term)
    return kept


def glossary(*sources: list[str]) -> list[str]:
    return [
        t
        for t in normalize_terms([t for source in sources for t in source])
        if len(t.split()) <= _MAX_TERM_WORDS and len(_norm(t)) >= _MIN_TERM_CHARS
    ]


def _similar(heard: str, term: str) -> float:
    """Spelling similarity of the letters alone; 0 when the first sounds or lengths part.

    A recognizer writes a digit for a number it heard, so the numbers must agree:
    "KemiK3" can be "Kimi K3", "L2, and" cannot be "LanceDB".
    """
    h, t = _norm(heard), _norm(term)
    if not h or h[0] != t[0] or not (_LENGTH_RATIO[0] <= len(h) / len(t) <= _LENGTH_RATIO[1]):
        return 0.0
    if re.sub(r"\D", "", h) != re.sub(r"\D", "", t):
        return 0.0
    return SequenceMatcher(None, h, t).ratio()


def _spans(text: str, max_words: int):
    words = list(_WORD.finditer(text))
    for i in range(len(words)):
        for j in range(i, min(i + max_words, len(words))):
            yield words[i].start(), words[j].end()


def _common_terms(segments: list[dict], terms: list[str]) -> set[str]:
    """One-word terms spelled like any word, which the transcript itself writes in lower case.

    A description capitalises "Vector" mid-sentence; that does not make "vector" a
    mishearing of it.
    """
    lowered = {w for s in segments for w in _WORD.findall(s["text"]) if w.islower()}
    return {
        t
        for t in terms
        if " " not in t
        and not any(c.isdigit() or c.isupper() for c in t[1:])
        and t.casefold() in lowered
    }


def _scored(
    idx: int, text: str, terms: list[str], max_words: int, ordinary: Callable[[str], bool]
) -> list[Candidate]:
    scored = []
    for start, end in _spans(text, max_words):
        heard = text[start:end]
        # A span holding a term as written is that term plus a neighbour.
        if any(t in heard and term_pattern(t).search(heard) for t in terms):
            continue
        # A word the recognizer holds whole is one it heard ("rate"); a mishearing
        # of a term is usually not one ("RAAG"). I-66.
        if all(ordinary(w) for w in _WORD.findall(heard)):
            continue
        for term in terms:
            score = _similar(heard, term)
            if score >= MIN_SIMILARITY:
                scored.append(Candidate(idx, start, end, heard, term, round(score, 3)))
    return scored


def find_candidates(
    segments: list[dict], terms: list[str], *, ordinary: Callable[[str], bool]
) -> list[Candidate]:
    """Non-overlapping spans per segment that read like a term and are not already one.

    `ordinary(word)` is whether the speech model's vocabulary holds the word whole.
    """
    terms = [t for t in terms if t not in _common_terms(segments, terms)]
    max_words = max((len(t.split()) for t in terms), default=0) + 1
    found: list[Candidate] = []
    for idx, seg in enumerate(segments):
        scored = _scored(idx, seg["text"], terms, max_words, ordinary)
        taken: list[Candidate] = []
        for cand in sorted(scored, key=lambda c: (-c.score, c.start - c.end)):
            if all(cand.end <= t.start or cand.start >= t.end for t in taken):
                taken.append(cand)
        found.extend(sorted(taken, key=lambda c: c.start))
    return found


_PROMPT = """A speech recognizer transcribed a recorded talk and sometimes mishears names \
and technical terms. The talk's glossary includes "{term}".

Context before: {before}
Context after: {after}

One of these two sentences is what the speaker said:
A: {a}
B: {b}

Which sentence did the speaker say? Reply with exactly one letter: A or B."""


def parse_choice(raw: str) -> str | None:
    """"A" or "B" when the reply is exactly that letter, else None."""
    letter = str(raw).strip().strip(".*\"' ").upper()
    return letter if letter in {"A", "B"} else None


async def _choose(segments: list[dict], cand: Candidate, *, corrected_first: bool) -> bool | None:
    """Whether the model picks the corrected sentence; None when it could not be asked."""
    from app.services.llm import get_llm_service  # noqa: PLC0415

    original = segments[cand.segment]["text"]
    corrected = original[: cand.start] + cand.term + original[cand.end :]
    a, b = (corrected, original) if corrected_first else (original, corrected)
    prompt = _PROMPT.format(
        term=cand.term,
        before=segments[cand.segment - 1]["text"] if cand.segment > 0 else "",
        after=segments[cand.segment + 1]["text"] if cand.segment + 1 < len(segments) else "",
        a=a,
        b=b,
    )
    try:
        with awaited():
            # Local in every mode: transcription never puts document text on the wire
            # (engine-and-hosts.md). Sampled, an unsure choice wins both orders by chance.
            raw = await get_llm_service().generate(
                prompt, model=get_local_chat_model(), background=True, temperature=0
            )
    except Exception as exc:
        logger.warning("transcript correction call failed (non-fatal): %s", exc)
        return None
    choice = parse_choice(raw)
    if choice is None:
        logger.warning("transcript correction reply unparseable: %.200s", raw)
        return None
    return (choice == "A") == corrected_first


async def judge(segments: list[dict], cand: Candidate) -> bool | None:
    """Accepted only when the corrected sentence wins in both orders (I-66).

    A model that leans to yes or to one position cannot win both orders.
    """
    first = await _choose(segments, cand, corrected_first=True)
    if first is None:
        return None
    if not first:
        return False
    return await _choose(segments, cand, corrected_first=False)


def _apply_spans(segments: list[dict], chosen: set[Candidate]) -> list[dict]:
    by_segment: dict[int, list[Candidate]] = {}
    for cand in chosen:
        by_segment.setdefault(cand.segment, []).append(cand)
    out = [dict(s) for s in segments]
    for idx, cands in by_segment.items():
        text = out[idx]["text"]
        for cand in sorted(cands, key=lambda c: -c.start):
            text = text[: cand.start] + cand.term + text[cand.end :]
        out[idx]["text"] = text
    return out


def term_pattern(heard: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(heard)}(?![A-Za-z0-9])", re.IGNORECASE)


def replace_heard(text: str, heard: str, term: str) -> tuple[str, int]:
    return term_pattern(heard).subn(lambda _m: term, text)


def _apply_user(segments: list[dict], corrections: list[dict]) -> tuple[list[dict], list[dict]]:
    out = [dict(s) for s in segments]
    records = []
    for corr in corrections:
        total = 0
        for seg in out:
            seg["text"], n = replace_heard(seg["text"], corr["heard"], corr["term"])
            total += n
        records.append({**corr, "count": total})
    return out, records


def _model_records(chosen: set[Candidate]) -> list[dict]:
    counts: dict[tuple[str, str], int] = {}
    for cand in chosen:
        counts[(cand.heard, cand.term)] = counts.get((cand.heard, cand.term), 0) + 1
    return [
        {"heard": h, "term": t, "source": "model", "count": n}
        for (h, t), n in sorted(counts.items())
    ]


async def _judged(
    segments: list[dict],
    candidates: list[Candidate],
    on_progress: Callable[[float], None] | None = None,
) -> set[Candidate]:
    chosen: set[Candidate] = set()
    unjudged = 0
    for i, cand in enumerate(candidates):
        if on_progress is not None:
            on_progress(i / len(candidates))
        verdict = await judge(segments, cand)
        if verdict is None:
            unjudged += 1
        elif verdict:
            chosen.add(cand)
    logger.info(
        "transcript correction: %d candidates, %d accepted, %d unjudged",
        len(candidates),
        len(chosen),
        unjudged,
    )
    return chosen


async def correct_transcript(
    document_id: str,
    segments: list[dict],
    *,
    ordinary: Callable[[str], bool] | None,
    on_progress: Callable[[float], None] | None = None,
) -> list[dict]:
    """Re-apply the user's corrections, then the judged glossary pass.

    `ordinary` is the speech model's whole-word test; None (captions an uploader
    wrote) skips the glossary pass, since nothing was misheard. `on_progress`
    receives the fraction of candidate spans judged: one model call or two each.
    """
    vocabulary, recorded, personal = await fetch_transcript_inputs(document_id)
    user = [c for c in recorded if c.get("source") == "user"]
    segments, records = _apply_user(segments, user)
    chosen: set[Candidate] = set()
    if ordinary is not None:
        terms = glossary(vocabulary, personal)
        candidates = find_candidates(segments, terms, ordinary=ordinary)
        chosen = await _judged(segments, candidates, on_progress)
        segments = _apply_spans(segments, chosen)
    await save_transcript_corrections(document_id, [*records, *_model_records(chosen)])
    return segments
