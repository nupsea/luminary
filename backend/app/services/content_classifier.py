"""Decide what kind of document this is, from the document.

The previous rules scored 4 of 13 on the repo's own corpus. Three things were
wrong with them and each is worth stating, because they are easy to reintroduce:

1. **They read the first 5,000 characters.** For a Project Gutenberg book that
   window is the licence, not the book -- `hamlet.txt` carries 27 lines of it
   and `the_odyssey.txt` 25. Every literary text was classified on boilerplate.
2. **They matched single words anywhere.** `references` in a textbook made it a
   paper; `\\b[A-Z][a-zA-Z]+:\\s` made `Chapter 1: ` a conversation; a `=====`
   rule made a design-review document Kindle clippings.
3. **First match won.** Ordering silently decided the answer, so a technical
   book that mentioned "abstract" could never reach the technical rule.

So: sample the body rather than the head, require signals to *recur* rather
than merely appear, and score every candidate instead of returning on the first
hit. The coarse family (technical / prose / conversation / notes) is what the
pipeline actually branches on, so the rules are tuned for that first -- the user
can always correct the exact type, and the picker stays visible so they can.
"""

from __future__ import annotations

import re

# Gutenberg wraps every text in a licence. The markers are stable across the
# corpus and are the only reliable way to find where the actual work starts.
_GUTENBERG_START = re.compile(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.I)
_GUTENBERG_END = re.compile(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.I)

# A real Kindle clipping carries its own header, not just a rule of equals
# signs -- a design-review fixture using `=====` as a divider was classified as
# clippings on that alone.
#
# Both parts must be present but in either order: the divider *separates*
# entries in a real `My Clippings.txt`, so the first entry has none above it and
# requiring it first never matches a single-entry export.
_KINDLE_DIVIDER = re.compile(r"^=+\s*$", re.M)
_KINDLE_ENTRY = re.compile(r"^-\s*Your (?:Highlight|Note|Bookmark)\b", re.I | re.M)

# A speaker line starts the line, names someone short, and ends in a colon.
# Anchoring to the line start is what stops "Chapter 1: " and "Note: " counting.
_SPEAKER_LINE = re.compile(r"^\s{0,4}([A-Z][\w.'-]{1,24}(?:\s[A-Z][\w.'-]{1,24})?)\s*[:.]\s+\S")

# Front-matter keys look exactly like speaker turns. `daily_thoughts_2026.txt`
# is a journal whose "Date:" lines are 46% of it -- the highest speaker share
# outside the actual transcripts.
# Role labels stand in for names in interviews and talk transcripts and are
# conventionally lower-case, which the capitalised-name pattern above misses.
_ROLE_SPEAKER = re.compile(
    r"^\s{0,4}(interviewer|interviewee|speaker|host|guest|moderator|panelist|"
    r"participant|caller|narrator|q|a)\s*\d{0,2}\s*[:.]\s+\S",
    re.I,
)

_METADATA_LABELS = frozenset(
    {
        "date", "author", "title", "source", "tags", "note", "notes", "updated",
        "created", "summary", "status", "url", "link", "from", "to", "subject",
        "location", "time", "topic", "category", "type", "version",
    }
)
_TRANSCRIPT_HEADER = re.compile(
    r"^\s*(participants?|speakers?|attendees|transcript)\s*:", re.I | re.M
)

_CODE_FENCE = re.compile(r"^\s*```", re.M)
# A PDF puts "3.2" on its own line, so a title cannot be required alongside it
# -- which admits every bare decimal. The leading-zero and two-digit guards
# exclude plot ticks and measurements; data at or above 1.0 is still
# indistinguishable from a section number. Capture group so callers count
# distinct values: duplicated extraction (#97) otherwise multiplies one skeleton.
_NUMBERED_SECTION = re.compile(r"^[ \t]{0,4}([1-9]\d?(?:\.\d{1,2}){1,2})\.?(?=[ \t]|$)", re.M)
_PAPER_HEADING = re.compile(
    r"^\s{0,4}(?:\d+\.?\s*)?(abstract|introduction|related work|methodology|methods|"
    r"experimental setup|results|discussion|conclusion|references|bibliography)\s*$",
    re.I | re.M,
)
# Density over this list is what separates a technical work from prose, so the
# list has to be broad enough that no single term carries a document: at 24
# terms, `art_of_unix.txt` reached its density on one word ("protocol"). The
# terms are ordinary computing vocabulary rather than any one field's jargon --
# a list tuned to a corpus would classify that corpus and nothing else.
_TECH_VOCAB = re.compile(
    r"\b(algorithm|algorithms|api|apis|function|functions|parameter|parameters|"
    r"dataset|datasets|gradient|tensor|matrix|kernel|compiler|runtime|database|"
    r"databases|query|queries|schema|server|servers|protocol|protocols|latency|"
    r"throughput|neural|regression|inference|deployment|repository|kubernetes|"
    r"docker|syntax|variable|variables|interface|interfaces|implementation|"
    r"binary|bytes|buffer|cache|thread|threads|process|processes|module|modules|"
    r"library|libraries|compile|debug|debugging|filesystem|unix|linux|kernel|"
    r"config|configuration|specification|encoding|whitespace|command|commands|"
    r"script|scripts|input|output|stdin|stdout|regex|integer|string|strings|"
    r"pointer|memory|cpu|gpu|network|networking|client|packet|packets)\b",
    re.I,
)

_CODE_EXTENSIONS = ("py", "js", "ts", "go", "java", "rs", "cpp", "c", "rb")

# Below this a document is a note rather than a work, whatever else it looks
# like. `ml_notes.txt` (~400 words) and `daily_thoughts_2026.txt` sit here;
# `the_odyssey.txt` at ~130k does not.
_NOTES_MAX_WORDS = 2000

# What a short document must score before it is called something other than a
# note. `ml_notes.txt` reaches 2.0 (prose, on the absence of technical
# vocabulary); a 100-word file with six code fences reaches 3.0.
_SHORT_DOC_CONFIDENCE = 2.5

# See the conversation block: measured gap is 0.019 to 0.170.
_SPEAKER_SHARE_FLOOR = 0.10


def strip_boilerplate(raw_text: str) -> str:
    """Return the work, without a Gutenberg licence wrapped around it."""
    start = _GUTENBERG_START.search(raw_text)
    body = raw_text[start.end() :] if start else raw_text
    end = _GUTENBERG_END.search(body)
    if end:
        body = body[: end.start()]
    return body.strip() or raw_text


def sample_body(raw_text: str, window: int = 6000) -> str:
    """Text from three points in the body, not just the opening.

    An opening is the least representative part of a document: front matter,
    a title page, a licence, an abstract. Sampling at 10%, 45% and 75% costs
    nothing and means a signal has to actually recur to be counted.
    """
    body = strip_boilerplate(raw_text)
    if len(body) <= window:
        return body
    third = window // 3
    return "\n".join(
        body[int(len(body) * frac) : int(len(body) * frac) + third] for frac in (0.10, 0.45, 0.75)
    )


_CONTENTS_MARKER = re.compile(r"table of contents|^\s*contents\s*$", re.I | re.M)
_DOTTED_LEADER = re.compile(r"\.{4,}")
_NUMERIC_LINE = re.compile(r"^\s*[\d.]+\s*$", re.M)

# Bracketed on the library: contents pages run 0.24-0.64, prose windows 0.0.
_NUMERIC_LINE_SHARE = 0.15


def looks_like_front_matter(window: str) -> bool:
    """Whether this window is a contents listing rather than the work.

    Not sentence density: `art_of_unix` opens with a chapter contents whose
    entries each end in a full stop, so it scores as prose. A listing is caught
    by saying so, by dotted leaders, or by a column of page numbers.
    """
    if _CONTENTS_MARKER.search(window) or _DOTTED_LEADER.search(window):
        return True
    lines = [ln for ln in window.splitlines() if ln.strip()]
    if not lines:
        return False
    numeric = sum(1 for ln in lines if _NUMERIC_LINE.match(ln))
    return numeric / len(lines) > _NUMERIC_LINE_SHARE


def subject_excerpt(raw_text: str, window: int = 2000) -> str:
    """The excerpt to judge a document's subject from.

    The opening, which measured 20/21 against 17/21 for a body sample: a work
    states its subject early. Falls back to the body only when the opening is a
    contents listing, so a clean opening is read exactly as before, and returns
    "" when both are listings -- the caller reports that as unclassified.

    Finds contents listings and nothing else. An illustration list or a
    publisher's note after the licence marker still reaches the probe.
    """
    body = strip_boilerplate(raw_text)
    head = body[:window].strip()
    if head and not looks_like_front_matter(head):
        return head
    fallback = sample_body(raw_text, window=window).strip()
    if fallback and looks_like_front_matter(fallback):
        return ""
    return fallback


# Section markers by convention. `_FLAT_MARKER` is the gap that made The
# Elements of Style read as prose: `_NUMBERED_SECTION` only ever matched
# dot-decimals, so its 60 numbered rules were invisible.
_FLAT_MARKER = re.compile(r"^[ \t]{0,6}\d{1,3}\.[ \t]+[A-Z]", re.M)
_NAMED_MARKER = re.compile(
    r"^[ \t]{0,6}(?:Article|Section|Rule|Clause|Item|Appendix)\b", re.I | re.M
)
# Chapter, Part, Book, Canto, Act, Scene are how a NARRATIVE divides itself.
# Counting them makes every novel a reference: Hamlet rates 1.63 on them alone.
_NARRATIVE_DIVISION = re.compile(
    r"^[ \t]{0,6}(?:Chapter|Part|Book|Canto|Act|Scene)\b", re.I | re.M
)

# Three dated units is a habit rather than a mention.
_DATED_ENTRY = re.compile(
    r"^[ \t]{0,6}(?:Date\s*:|\d{4}-\d{2}-\d{2}\b|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b)",
    re.I | re.M,
)

# Past this length, marker density describes how long a document is rather than
# what it is: `ibm-sdm-vol-2` carries 1,391 markers and rates 0.47 uncapped.
_MARKER_RATE_WORD_CAP = 200_000

# Below this, a rate means little: five numbered lines in a 2,600-word release
# note rate 1.91. The smallest true reference measured, `art_of_unix`, has 41.
_MIN_SECTION_MARKERS = 8


def count_section_markers(text: str) -> int:
    """Section markers, narrative divisions excluded."""
    return (
        len(_FLAT_MARKER.findall(text))
        + len(_NUMBERED_SECTION.findall(text))
        + len(_NAMED_MARKER.findall(text))
    )


def section_marker_rate(text: str, word_count: int) -> float:
    """Section markers per 1,000 words, against a capped length.

    Bracketed across 20 documents: `federalist_papers` at 0.43 is the most
    sectioned prose, `art_of_unix` at 2.68 the least sectioned reference.
    """
    if word_count <= 0:
        return 0.0
    denominator = min(word_count, _MARKER_RATE_WORD_CAP) / 1000
    return count_section_markers(text) / denominator


def count_numbered_sections(text: str) -> int:
    """How many distinct numbered sections the text appears to carry.

    Distinct rather than total: extraction that repeats a section body would
    otherwise multiply one skeleton into a structural score it did not earn.
    """
    return len(set(_NUMBERED_SECTION.findall(text)))


def _speaker_stats(text: str) -> tuple[int, int, float]:
    """(distinct speakers, speaker lines, share of non-empty lines).

    Names are filtered against `_METADATA_LABELS` rather than by requiring a
    name to recur. Recurrence looked like the safer test and is not: a two-line
    exchange has no repeat, and two-person transcripts are the common case --
    `modern_retrieval_talk_transcript.txt` is host-and-guest and nothing else.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return 0, 0, 0.0
    names: dict[str, int] = {}
    for ln in lines:
        role = _ROLE_SPEAKER.match(ln)
        if role:
            names[role.group(1).lower()] = names.get(role.group(1).lower(), 0) + 1
            continue
        m = _SPEAKER_LINE.match(ln)
        if m:
            name = m.group(1).strip().lower()
            if name not in _METADATA_LABELS:
                names[name] = names.get(name, 0) + 1
    total = sum(names.values())
    return len(names), total, total / len(lines)


def classify_content(
    raw_text: str,
    sections: list[dict],
    word_count: int,
    file_ext: str,
    filename: str = "",
) -> str:
    """The document's content type, decided by scoring rather than by ordering."""
    ext = (file_ext or "").lower().lstrip(".")
    if ext in ("mp3", "m4a", "wav"):
        return "audio"
    if ext == "mp4":
        return "video"
    if ext in _CODE_EXTENSIONS:
        return "code"
    if ext == "epub":
        return "book"

    head = raw_text[:20000]
    if re.search(r"clippings", filename, re.I) or (
        _KINDLE_DIVIDER.search(head) and _KINDLE_ENTRY.search(head)
    ):
        return "kindle_clippings"

    full_body = strip_boilerplate(raw_text)
    body = sample_body(raw_text)
    headings = " \n".join(str(s.get("heading") or "") for s in sections)
    distinct_speakers, speaker_lines, speaker_share = _speaker_stats(body)

    scores: dict[str, float] = dict.fromkeys(
        ("conversation", "tech_book", "tech_article", "paper", "book", "notes"), 0.0
    )

    # Conversation: several people, each speaking repeatedly, over a good share
    # of the text. A play reaches this too, so length and prose decide below.
    # Share is the discriminator, not head-count. Measured on the labelled
    # corpus: the largest share outside a transcript is 0.019 (a stray
    # "Geography:" in Alice, "Senate:" in the Federalist Papers), and the
    # smallest inside one is 0.170. The floor sits in that gap.
    if distinct_speakers >= 2 and speaker_share >= _SPEAKER_SHARE_FLOOR:
        scores["conversation"] += 3.0 + min(speaker_share * 10, 3.0)
    if _TRANSCRIPT_HEADER.search(raw_text[:2000]):
        scores["conversation"] += 3.0

    # Technical: fenced code and numbered sections are structural, and the
    # vocabulary check stops a novel with one numbered list from qualifying.
    # Structural markers are counted over the whole body: they are sparse by
    # nature, and a sample large enough to find them reliably would not be a
    # sample. A 375 KB markdown textbook showed 0 fences in a 6 KB window and
    # dozens in the file.
    fences = len(_CODE_FENCE.findall(full_body))
    numbered = count_numbered_sections(full_body)
    tech_hits = len(_TECH_VOCAB.findall(body))
    tech_density = tech_hits / max(len(body.split()), 1) * 1000
    if fences >= 4:
        scores["tech_book"] += 3.0
    elif fences >= 2:
        scores["tech_book"] += 1.5
    if numbered >= 8:
        scores["tech_book"] += 2.5
    elif numbered >= 3:
        scores["tech_book"] += 1.5
    if tech_density >= 3:
        scores["tech_book"] += 2.0
        scores["tech_article"] += 1.5
    elif tech_density >= 1.5:
        scores["tech_book"] += 1.0
        scores["tech_article"] += 1.0

    # Paper: the section skeleton of a paper, as headings on their own lines.
    paper_headings = len({m.lower() for m in _PAPER_HEADING.findall(body + "\n" + headings)})
    if paper_headings >= 3:
        scores["paper"] += 4.0
    elif paper_headings == 2:
        scores["paper"] += 2.0
    elif paper_headings == 1:
        scores["paper"] += 1.5
    # A paper opens with its abstract. One such heading anywhere is weak -- a
    # textbook has a References line -- but one at the top is the real shape.
    if _PAPER_HEADING.match(full_body.lstrip()[:400].split("\n")[0].strip() or "x"):
        scores["paper"] += 1.5

    # Prose: long-form text that is none of the above. Chapter headings help but
    # are not required -- plays and epics have none, and requiring them is what
    # sent every novel to "notes".
    if word_count > _NOTES_MAX_WORDS:
        scores["book"] += 1.5
    # Chapter headings deliberately score nothing. They look like the obvious
    # prose signal and are not one -- a technical book is divided into chapters
    # exactly like a novel, so the bonus only ever fired on both. It is what
    # made `art_of_unix.txt` a book: +1.5 for its chapters outran the technical
    # vocabulary that was correctly detected.
    #
    # Prose is the absence of the other signals rather than a signal of its own,
    # so length alone must not outweigh them either.
    if tech_density < 1.5:
        scores["book"] += 2.0

    # A long work with speaker turns is usually a play or a novel with dialogue
    # rather than a meeting -- but not when the turns are nearly the whole text.
    # A play carries stage directions, scene headings and narration between its
    # turns, so they dilute; a recorded transcript is turns and almost nothing
    # else, and a three-hour podcast is still a conversation.
    #
    # Not bracketed by the corpus: no labelled prose file has a speaker share
    # above 0.019, so the dilution floor is reasoned from the formats rather
    # than measured. A play formatted as pure "NAME: line" turns would land on
    # the wrong side of it.
    if word_count >= 20000 and scores["conversation"] > 0 and speaker_share < 0.5:
        scores["conversation"] -= 3.0

    # Technical beats prose when both fire: the pipeline branches on it, and
    # chunking a manual as a novel is the more expensive mistake.
    if scores["tech_book"] >= 4.0:
        scores["tech_book"] += 1.5

    best = max(scores, key=lambda k: scores[k])
    # Notes is the fallback, not a competitor. Scoring it by length alone let a
    # short document outrank whatever it plainly was: a 100-word file with six
    # code fences, or a two-line interview, both came back "notes" because they
    # were short. Short *and* unstructured is a note; short with strong
    # structure is a small example of the thing its structure says it is.
    if word_count <= _NOTES_MAX_WORDS and scores[best] < _SHORT_DOC_CONFIDENCE:
        return "notes"
    if scores[best] <= 0:
        return "notes"
    # tech_book vs tech_article is a sizing choice, not a category: long or
    # heavily structured is a book, otherwise an article.
    if best == "tech_book" and word_count < 5000 and fences < 2 and numbered < 3:
        return "tech_article"
    return best


# Bracketed by `federalist_papers` at 0.43 (prose) and `art_of_unix` at 2.68.
_REFERENCE_MARKER_RATE = 1.5

# `Introducing Contextual Retrieval` at 1,704 words is an article;
# `luminary_conceptual_foundations` at 5,312 is a reference.
_ARTICLE_MAX_WORDS = 5000


def classify_form(
    raw_text: str,
    sections: list[dict],
    word_count: int,
    file_ext: str,
    filename: str = "",
) -> str:
    """The document's shape, from structure alone.

    **No vocabulary signal takes part.** Deriving `form` from `content_type` put
    `reference` behind `tech_book`, which needs technical vocabulary, so a
    non-technical manual could not be one -- held out, The Elements of Style,
    the US Constitution and a cookbook all read as prose.

    Order matters: a paper is numbered too, so its skeleton is looked for first,
    and speaker turns before length so a short transcript is not a note.
    """
    ext = (file_ext or "").lower().lstrip(".")
    if ext in _CODE_EXTENSIONS:
        return "source_code"
    if ext in ("mp3", "m4a", "wav", "mp4"):
        return "dialogue"

    head = raw_text[:20000]
    if re.search(r"clippings", filename, re.I) or (
        _KINDLE_DIVIDER.search(head) and _KINDLE_ENTRY.search(head)
    ):
        return "entries"

    body = sample_body(raw_text)
    full = strip_boilerplate(raw_text)
    headings = " \n".join(str(s.get("heading") or "") for s in sections)
    distinct_speakers, _, speaker_share = _speaker_stats(body)

    # A play carries stage directions and scene headings between its turns, so
    # they dilute; a transcript is turns and almost nothing else.
    if distinct_speakers >= 2 and speaker_share >= _SPEAKER_SHARE_FLOOR:
        if word_count < 20000 or speaker_share >= 0.5:
            return "dialogue"
        return "script"

    paper_headings = len({m.lower() for m in _PAPER_HEADING.findall(body + "\n" + headings)})
    if paper_headings >= 3:
        return "paper"

    if (
        count_section_markers(full) >= _MIN_SECTION_MARKERS
        and section_marker_rate(full, word_count) >= _REFERENCE_MARKER_RATE
    ):
        return "reference"

    # Dated or delimited units, not merely short: keying on length alone made a
    # 1,704-word blog post a journal.
    if len(_DATED_ENTRY.findall(full)) >= 3:
        return "entries"

    if word_count < _ARTICLE_MAX_WORDS:
        return "article"
    return "prose"
