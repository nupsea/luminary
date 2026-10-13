"""Terms a video's own metadata spells, for biasing speech-to-text toward them.

A speech model writes what a word sounds like, so the words it gets wrong are the
ones whose spelling is not derivable from sound: mixed case ("LanceDB"), letters
with digits ("K3"), acronyms ("RAG") and proper nouns. Those are what this keeps.
Every term comes from the uploader's own title, channel, tags, chapters and
description; nothing here supplies a term of its own.
"""

import re
from collections import Counter

_URL = re.compile(r"(?:https?://|www\.)\S+|\S+@\S+\.\S+")
# Sentence and list boundaries: what follows one is capitalised by position, not
# because it names something.
_BOUNDARY = re.compile(r"[\n.!?:;|•·–—]+|\s-\s|\(|\)|\[|\]|\"")
# Commas and slashes are tokens so they end a run ("BM25, Vector search") without
# ending the clause.
_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9'+._-]*[A-Za-z0-9+])?|[,/]")
_PRONOUN = re.compile(r"I(?:'[a-z]+)?")
# A run of name-like words longer than this is a Title Case line, not a name.
_MAX_RUN_WORDS = 3
# A tag past this length is a sentence the uploader typed into the tag box.
_MAX_TAG_WORDS = 4


def _strip_possessive(token: str) -> str:
    return token[:-2] if token.endswith(("'s", "'S")) else token


def _is_spelled_term(token: str) -> bool:
    """A word whose spelling a listener could not recover from its sound."""
    if not any(c.isalpha() for c in token):
        return False
    return any(c.isdigit() for c in token) or any(c.isupper() for c in token[1:])


def _is_capitalised(token: str) -> bool:
    # The pronoun is capitalised wherever it stands ("I've", "I'll").
    return token[0].isupper() and not _PRONOUN.fullmatch(token)


def _clauses(text: str) -> list[list[str]]:
    return [
        [_strip_possessive(t) for t in _TOKEN.findall(clause)]
        for clause in _BOUNDARY.split(_URL.sub(" ", text))
    ]


def _runs(tokens: list[str]):
    """(mid_clause, run) per maximal run of capitalised or spelled tokens.

    Mid-clause means after an uncapitalised word: a timestamp before "Intro" does
    not make its capital mean anything.
    """
    seen_lower = False
    run: list[str] = []
    run_mid = False
    for token in [*tokens, ""]:
        if token and (_is_capitalised(token) or _is_spelled_term(token)):
            if not run:
                run_mid = seen_lower
            run.append(token)
            continue
        if run:
            yield run_mid, run
            run = []
        if token[:1].isalpha():
            seen_lower = True


def _terms_in(text: str, names: set[str]) -> list[str]:
    """Spelled terms and name runs.

    A clause-initial capital is positional, so there a word counts only if it is
    spelled or the metadata capitalises it mid-clause somewhere (`names`).
    """
    terms: list[str] = []
    for clause in _clauses(text):
        for mid, run in _runs(clause):
            for group in [run] if mid else _name_groups(run, names):
                if len(group) > _MAX_RUN_WORDS:
                    terms.extend(t for t in group if _is_spelled_term(t))
                # A lone letter is the pronoun "I" or an initial, not a name.
                elif len(" ".join(group)) > 1:
                    terms.append(" ".join(group))
    return terms


def _name_groups(run: list[str], names: set[str]) -> list[list[str]]:
    """Contiguous stretches of a clause-initial run that are spelled or known names."""
    groups: list[list[str]] = [[]]
    for token in run:
        if _is_spelled_term(token) or token in names:
            groups[-1].append(token)
        elif groups[-1]:
            groups.append([])
    return groups


def _head(meta: dict) -> list[str]:
    head = [
        value.strip()
        for value in (meta.get("title"), meta.get("uploader") or meta.get("channel"))
        if isinstance(value, str) and value.strip()
    ]
    head.extend(
        tag.strip()
        for tag in meta.get("tags") or []
        if isinstance(tag, str) and 0 < len(tag.split()) <= _MAX_TAG_WORDS
    )
    return head


def _names(sources: list[str], description: str) -> set[str]:
    """Words the metadata capitalises where position does not explain it."""
    names: set[str] = set()
    for text in sources:
        for clause in _clauses(text):
            runs = list(_runs(clause))
            names.update(t for mid, run in runs if mid for t in run)
            # In prose, a line that is only a short capitalised run is a byline
            # ("Anup Sethuram"); a title or chapter is Title Case by convention.
            if text is description:
                names.update(_byline(clause, runs))
    return names


def _byline(clause: list[str], runs: list[tuple[bool, list[str]]]) -> list[str]:
    words = [t for t in clause if t not in {",", "/"}]
    whole = len(runs) == 1 and runs[0][1] == words
    return words if whole and 2 <= len(words) <= _MAX_RUN_WORDS else []


def vocabulary_from_metadata(meta: dict) -> list[str]:
    """Title, channel and tags first, then terms ranked by how often the uploader wrote them."""
    head = _head(meta)
    chapters = [c.get("title", "") for c in meta.get("chapters") or [] if isinstance(c, dict)]
    description = meta.get("description") or ""
    sources = [*head, *chapters, description]
    names = _names(sources, description)

    counts: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    for text in sources:
        for term in _terms_in(text, names):
            counts[term] += 1
            first_seen.setdefault(term, len(first_seen))
    ranked = sorted(counts, key=lambda t: (-counts[t], first_seen[t]))

    vocabulary: list[str] = []
    for term in [*head, *ranked]:
        if not _covered(term, vocabulary):
            vocabulary.append(term)
    return vocabulary


def _covered(term: str, kept: list[str]) -> bool:
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term.casefold())}(?![A-Za-z0-9])")
    return any(pattern.search(k.casefold()) for k in kept)


def hotwords(vocabulary: list[str] | None) -> str | None:
    """The prompt string. faster-whisper keeps its first 223 tokens, so order is priority."""
    return ", ".join(vocabulary) if vocabulary else None
