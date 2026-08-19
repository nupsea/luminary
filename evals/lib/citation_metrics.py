"""Citation grounding metrics for eval runs (S215)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal

Verdict = Literal["yes", "no", "partial"]

def pair_answer_with_citations(
    answer_text: str, citations: list[object]
) -> list[tuple[str, str]]:
    """Pair an answer with each citation excerpt returned beside it.

    The QA endpoint emits prose followed by a JSON citations block, never inline
    ``[N]`` markers (`app/services/qa.py`), so no claim can be attributed to one
    specific citation. Attributing them anyway would be inventing a link the
    product never made.

    What is measurable is the property a reader actually depends on: every source
    chip shown under an answer should support what the answer said. So each
    citation is judged against the whole answer, and the rate is the fraction of
    shown citations that hold up.

    An earlier version of this metric split prose on ``[N]`` markers. It scored
    `None` in all 285 recorded runs, because the product has never emitted them.
    """
    answer = " ".join(answer_text.split())
    if not answer:
        return []
    pairs: list[tuple[str, str]] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        excerpt = str(citation.get("text") or citation.get("excerpt") or "").strip()
        if excerpt:
            pairs.append((answer, excerpt))
    return pairs


def judge_citation(claim: str, chunk: str, judge_model: str) -> Verdict:
    """Judge whether *chunk* supports *claim* using LiteLLM strict JSON output.

    *claim* is the whole answer, because the product emits no per-claim markers
    to attribute a citation to (see ``pair_answer_with_citations``). The prompt
    must therefore ask what a reader asks -- does this chip support something the
    answer said -- not whether one excerpt carries the entire answer. An earlier
    prompt demanded the citation "fully supports the claim" against that whole
    answer, which no single excerpt can do: measured over book chips, it scored
    `no` on a verbatim correct citation and `partial` on two more (0.500 vs 0.750
    on identical chips). Scores from before that fix are not comparable to scores
    after it.
    """
    import litellm  # noqa: PLC0415

    prompt = (
        "Decide whether the citation text supports at least one claim made in the "
        "answer. Return only JSON with this exact shape: "
        "{\"verdict\":\"yes|no|partial\"}.\n\n"
        f"Answer:\n{claim}\n\nCitation text:\n{chunk}"
    )
    response = litellm.completion(
        model=judge_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a citation-grounding judge. An answer may make several "
                    "claims and cite several sources; each source is expected to "
                    "support part of the answer, not all of it. Use yes when the "
                    "citation text supports at least one specific claim the answer "
                    "makes, partial when it is on-topic but supports no specific "
                    "claim, and no when it is irrelevant to the answer, contradicts "
                    "it, or is commentary about the context rather than a quote "
                    "from it."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    content = response.choices[0].message.content or "{}"
    verdict = str(json.loads(content).get("verdict", "")).lower()
    if verdict not in {"yes", "no", "partial"}:
        return "no"
    return verdict  # type: ignore[return-value]


def compute_citation_support_rate(
    pairs: list[tuple[str, str]],
    *,
    judge: Callable[[str, str], Verdict],
) -> float | None:
    """Return ``(yes + 0.5 * partial) / total`` for claim/chunk pairs.

    Resilient to per-pair judge failures: each judge call is wrapped, errors
    are counted and logged, and the rate is computed over successful judgements
    only. Returns None if zero pairs were judged successfully.
    """
    import sys  # noqa: PLC0415

    if not pairs:
        print(
            "WARNING: citation_support_rate skipped -- no answer carried a "
            "citation with an excerpt. Every answer was uncited, which "
            "citation_coverage reports as a product result rather than a gap "
            "in the measurement.",
            file=sys.stderr,
        )
        return None
    score = 0.0
    judged = 0
    failures = 0
    for claim, chunk in pairs:
        try:
            verdict = judge(claim, chunk)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(
                f"WARNING: citation judge call failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            continue
        judged += 1
        if verdict == "yes":
            score += 1.0
        elif verdict == "partial":
            score += 0.5
    total = len(pairs)
    if failures:
        pct = failures / total
        print(
            f"WARNING: {failures}/{total} citation judge calls failed "
            f"({pct:.0%}).",
            file=sys.stderr,
        )
        if pct >= 0.5:
            print(
                "WARNING: citation_support_rate is unreliable -- majority of "
                "judge calls failed. Check the judge model availability.",
                file=sys.stderr,
            )
    if judged == 0:
        return None
    return score / judged
