"""Where a golden row's hint came from, recorded rather than remembered.

`realign_hints.py` dumps the top-5 chunks for rows whose hint is not retrieved,
so a corrected hint can be chosen by hand. Replacing a non-verbatim hint with a
verbatim one is correct. Choosing among verbatim candidates by what the
retriever happened to surface is not: the retriever ends up defining its own
target, and the score that follows measures agreement with itself.

Nothing recorded which of the two had happened, which is the whole problem —
the two are indistinguishable in the file afterwards.

A dataset declares a default in its `.meta.json`; a row overrides it when it
differs. `realigned` additionally requires a reason, because that is the one
value that needs a human to say why it was safe.
"""

from __future__ import annotations

from typing import Any

# Rows written by the generator and never touched.
GENERATED = "generated"
# Hint replaced with text copied verbatim from the source, chosen without
# consulting retrieval. Safe: it fixes a hint that could never match.
CORRECTED_VERBATIM = "corrected-verbatim"
# Hint chosen from what retrieval returned. The circular case.
REALIGNED = "realigned"
# Passages sampled mechanically from the index (the flashcard golden).
SAMPLED = "sampled"
# Written by a person, no model involved (the intent goldens).
HAND = "hand"
# Datasets that predate this record. Not a value to use for anything new: it
# means the answer was not kept, which is exactly what this module fixes.
UNRECORDED = "unrecorded-pre-provenance"

VALUES = frozenset(
    {GENERATED, CORRECTED_VERBATIM, REALIGNED, SAMPLED, HAND, UNRECORDED}
)


def provenance_of(row: dict[str, Any], default: str) -> str:
    value = row.get("provenance")
    return value if isinstance(value, str) and value else default


def violations(rows: list[dict[str, Any]], meta: dict[str, Any]) -> list[str]:
    """What is wrong with a dataset's provenance, as messages. Empty is clean."""
    default = meta.get("row_provenance")
    problems: list[str] = []
    if not default:
        return [
            "meta.json declares no `row_provenance`, so nothing records where "
            "these hints came from"
        ]
    if default not in VALUES:
        problems.append(f"unknown row_provenance {default!r}; expected one of {sorted(VALUES)}")

    for index, row in enumerate(rows, start=1):
        value = provenance_of(row, default)
        if value not in VALUES:
            problems.append(f"row {index}: unknown provenance {value!r}")
        if value == REALIGNED and not str(row.get("provenance_reason", "")).strip():
            problems.append(
                f"row {index}: realigned against retriever output with no reason recorded"
            )
    return problems
