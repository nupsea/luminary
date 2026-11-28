"""The question call alone, under several source rules, on the same passages and key sentences.

Usage: question_variants.py <per-doc> <out.md> [variant,...]
Each passage's key is picked once (as the builder does) and every variant phrases a question about
it; the checks the builder runs on a question decide pass or refusal. No wrong answers, judge or
guess: this isolates the phrasing step.
"""

import asyncio
import collections
import json
import sys

from app.services.quiz_parsers import QuizRefusal, check_question, parse_question, without_source_clause

from app.database import get_session_factory
from app.services import quiz_builder, quiz_prompts
from app.services.llm import get_llm_service

DOCS = {
    "DDIA": "dad8a693-b933-4935-a580-a03b1866255d",
    "moby-dick": "b573268f-0319-4236-a029-ac732cbddd89",
    "federalist": "fa6e1ca4-ea86-414e-86dc-cc87637791d3",
}
_NEVER = (
    'and never says passage, text, author, document, book, chapter, excerpt, material, '
    '"the narrator" or "this".'
)
RULES = {
    "old": 'The question makes sense to someone who has never seen this material: it names its '
    'subject ("leader-based replication", "Ishmael"), ' + _NEVER,
    "plain": "The question names exactly who or what it asks about, " + _NEVER,
    "new": quiz_prompts._SOURCE_RULE,
}
VARIANTS = {
    "old": ("old", False),
    "current": ("new", False),
}
PER_DOC = int(sys.argv[1])
OUT = sys.argv[2]
CHOSEN = sys.argv[3].split(",") if len(sys.argv) > 3 else list(VARIANTS)


async def cases():
    out = []
    async with get_session_factory()() as session:
        for name, doc in DOCS.items():
            chunks = await quiz_builder.scope_chunks(session, doc, None)
            pool = quiz_builder.windows(chunks)
            summaries = await quiz_builder._summaries(session, doc)
            step = max(1, len(pool) // (PER_DOC * 2))
            picked = []
            for w in pool[::step]:
                taken = await quiz_builder._take([w], "single", summaries)
                if taken:
                    picked.append((name, taken[0], taken[1], summaries.get(w.section_id or "", "")))
                if len(picked) == PER_DOC:
                    break
            out.extend(picked)
    return out


async def one(writer, window, keys, about):
    raw = await writer.ask(quiz_prompts.question_prompt(window.text, keys, "", ""))
    try:
        stem, answers = parse_question(raw, 1)
        check_question(stem, answers, keys, window.text)
        await quiz_builder._check_keys(answers, keys)
    except QuizRefusal as refusal:
        return refusal.kind, raw
    return "pass", raw


async def main():
    found = await cases()
    llm = get_llm_service()
    tallies = {v: collections.Counter() for v in CHOSEN}
    lines = []
    for n, (doc, window, keys, about) in enumerate(found, 1):
        writer = quiz_builder._Writer(llm=llm, model=None, document_id=DOCS[doc])
        lines.append(f"### {n}. {doc}\n\n- key: {keys[0]}\n")
        for v in CHOSEN:
            rule, with_summary = VARIANTS[v]
            quiz_prompts._SOURCE_RULE = RULES[rule]
            verdict, raw = await one(writer, window, keys, about if with_summary else "")
            tallies[v][verdict] += 1
            try:
                q = json.loads(raw)
                shown = f"{without_source_clause(q.get('question') or '')} -> {q.get('answer')}"
            except (ValueError, AttributeError):
                shown = raw[:200]
            lines.append(f"- **{v}** [{verdict}]: {shown}")
            print(n, v, verdict, flush=True)
        lines.append("")
    head = [f"# Question variants, {len(found)} passages\n"]
    for v in CHOSEN:
        t = tallies[v]
        head.append(f"- **{v}**: pass {t['pass']} of {sum(t.values())}; " + ", ".join(
            f"{k} {c}" for k, c in t.most_common() if k != "pass"))
    with open(OUT, "w") as f:
        f.write("\n".join(head + ["", *lines]))


asyncio.run(main())
