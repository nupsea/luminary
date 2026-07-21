"""score_concepts node -- the studyability gate (relevance lever 2).

`is_junk_entity` (lever 1) kills format-junk deterministically, but it cannot judge whether a
real word is a *studyable concept*. "iceberg tables" is; "servers", "stock", "example code",
and "tabular" are not -- they are too generic, placeholder, or instructional to learn about on
their own. That judgement needs a model.

This node asks the LLM, in batches, to flag the low-quality level-2 concepts and marks them
``status="candidate"`` (the codebase's existing "extracted but not promoted" state -- already
excluded from grounding and study). Junk stays inspectable in the graph; it just stops surfacing
as something to learn. Runs after label_levels (labels exist) and before persist (which honours
the per-node status). Strictly fail-open: any model hiccup keeps every concept ``proposed`` so a
gate failure never silently empties a library.
"""

from __future__ import annotations

import json

from app.services.llm import get_llm_service
from app.workflows.concept_nodes._shared import ConceptPipelineState, record

_BATCH = 25
_SYS = (
    "You are curating a study app's concept list. Each item is a candidate concept extracted "
    "from the user's documents. Keep an item if it names a real, independent idea a learner "
    "could study (a technology, technique, theory, pattern, or named entity). Reject an item "
    "if it is too generic to study on its own (e.g. 'servers', 'stock', 'dynamic'), a "
    "placeholder or example name (e.g. 'example code', 'sample table'), an instruction or "
    "sentence fragment, or a raw code/identifier token. Reply with ONLY a JSON array of the "
    "1-based indices to REJECT, e.g. [2,5,9]. If none should be rejected, reply []."
)


def _parse_rejects(raw: str, n: int) -> set[int]:
    """Parse the model's reply into a set of 0-based indices, defensively."""
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        return set()
    try:
        arr = json.loads(raw[start : end + 1])
    except (ValueError, TypeError):
        return set()
    out: set[int] = set()
    for x in arr:
        if isinstance(x, int) and 1 <= x <= n:
            out.add(x - 1)
    return out


async def score_concepts(state: ConceptPipelineState) -> ConceptPipelineState:
    h = state.get("hierarchy")
    if not h or not h.get("concepts"):
        record(state, "score_concepts", {"flagged": 0})
        return state

    concepts = h["concepts"]
    llm = get_llm_service()
    flagged: list[str] = []

    for start in range(0, len(concepts), _BATCH):
        batch = concepts[start : start + _BATCH]
        listing = "\n".join(
            f"{i + 1}. {c.get('label') or c.get('sun') or ''}" for i, c in enumerate(batch)
        )
        try:
            raw = await llm.complete(
                messages=[
                    {"role": "system", "content": _SYS},
                    {"role": "user", "content": listing},
                ],
                temperature=0.0,
                background=True,
            )
        except Exception:
            continue  # fail-open: leave this batch as proposed
        for idx in _parse_rejects(raw, len(batch)):
            batch[idx]["status"] = "candidate"
            flagged.append(batch[idx].get("label") or batch[idx].get("sun") or "")

    record(
        state,
        "score_concepts",
        {
            "concepts": len(concepts),
            "flagged": len(flagged),
            "flagged_sample": sorted(flagged)[:25],
        },
    )
    return state
