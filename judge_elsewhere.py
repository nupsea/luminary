"""The open-book judge given each wrong option's nearest chunks from the rest of the document,
and asked for every option the material makes true, on accepted items from saved runs.

Usage: judge_elsewhere.py <db>:<item_id> [...]
"""
import asyncio
import json
import random
import sqlite3
import os
import sys

from app.services.llm import get_llm_service
from app.services.quiz_material import join_chunks
from app.services.quiz_prompts import LETTERS, QUIZ_SYSTEM
from app.services.retriever import get_retriever

JUDGE = "ollama/gemma4:latest"
PROMPT = """MATERIAL:
\"\"\"
{passage}
\"\"\"

{elsewhere}QUESTION: {question}

{options}

Using only the material, choose every option it shows to be a right answer to the question,
however many that is. If none is, return an empty list.

Return only JSON: {{"answer": ["<letter>"]}}"""


async def one(db, item_id, llm):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    item = con.execute("select * from quiz_items where id=?", (item_id,)).fetchone()
    ids = json.loads(item["source_chunk_ids"])
    texts = dict(con.execute(f"select id, text from chunks where id in ({','.join('?' * len(ids))})", ids).fetchall())
    passage = join_chunks([texts[i] for i in ids])
    opts = con.execute("select * from quiz_options where item_id=? order by position", (item_id,)).fetchall()
    extra, seen = [], set(ids)
    for o in opts:
        if o["is_correct"] or not os.environ.get("ELSEWHERE"):
            continue
        hits = await asyncio.to_thread(get_retriever().vector_search, o["text"], [item["document_id"]], 2)
        for h in hits:
            if h.chunk_id not in seen:
                seen.add(h.chunk_id)
                extra.append(h.text)
    order = list(range(len(opts)))
    random.Random(item["stem"]).shuffle(order)
    shown = [opts[i] for i in order]
    right = sorted(LETTERS[p] for p, o in enumerate(shown) if o["is_correct"])
    prompt = PROMPT.format(passage=passage, elsewhere=('ELSEWHERE IN THE SAME DOCUMENT:\n"""\n' + "\n\n".join(extra) + '\n"""\n\n') if extra else "", question=item["stem"],
                           options="\n".join(f"{LETTERS[p]}. {o['text']}" for p, o in enumerate(shown)))
    raw = await llm.generate(prompt, system=QUIZ_SYSTEM, model=JUDGE, stream=False, background=True,
                             response_format={"type": "json_object"}, temperature=0)
    try:
        picked = sorted(str(x).upper() for x in json.loads(raw).get("answer", []))
    except ValueError:
        picked = raw[:80]
    verdict = "same" if picked == right else "REFUSES"
    print(f"{item_id[:8]} {verdict:8} right {right} picked {picked} | {item['stem'][:70]} | extra {len(extra)} chunks", flush=True)


async def main():
    llm = get_llm_service()
    for arg in sys.argv[1:]:
        db, item_id = arg.rsplit(":", 1)
        await one(db, item_id, llm)

asyncio.run(main())
