"""Detect a model stuck repeating itself, so a streamed answer can be stopped there.

A small local model can fall into a verbatim loop and, with no output cap, stream it
until the context window fills: a 63k-character answer that cycled one 150-word list.
"""

import re

# Bracketed by the cases in test_repetition.py: a 150-word list cycled for minutes
# fires; a 50-word refrain sung three times (150 words) does not.
MIN_COPIES = 3
MIN_REPEATED_WORDS = 200
MAX_PERIOD_WORDS = 500
_TAIL_WORDS = MIN_REPEATED_WORDS + MAX_PERIOD_WORDS * MIN_COPIES
_TAIL_CHARS = _TAIL_WORDS * 16

_WORD = re.compile(r"\S+")


def repetition_cut(text: str) -> int | None:
    """Offset where the text's trailing loop begins its second copy, or None.

    The first copy is kept: it may be real content the model then got stuck on.
    """
    offset = max(0, len(text) - _TAIL_CHARS)
    matches = list(_WORD.finditer(text, offset))[-_TAIL_WORDS:]
    words = [m.group().lower() for m in matches]
    n = len(words)
    for period in range(1, min(MAX_PERIOD_WORDS, n // MIN_COPIES) + 1):
        matched = 0
        while matched < n - period and words[n - 1 - matched] == words[n - 1 - matched - period]:
            matched += 1
        span = matched + period
        if span >= MIN_REPEATED_WORDS and span >= MIN_COPIES * period:
            return matches[n - span + period].start()
    return None
