"""Per passage: the key length picks beside the key closeness to the section summary picks."""
import asyncio, os, sqlite3, sys
import numpy as np
from app.database import get_session_factory
from app.services import quiz_builder
from app.services.embedder import get_embedding_service
from app.services.quiz_material import key_candidates

DOCS = {"moby-dick": "b573268f-0319-4236-a029-ac732cbddd89", "federalist": "fa6e1ca4-ea86-414e-86dc-cc87637791d3", "DDIA": "dad8a693-b933-4935-a580-a03b1866255d"}
con = sqlite3.connect(os.path.expanduser("~/DEV/LM/lm-quiz-verify-data/luminary.db"))
emb = get_embedding_service()

async def main():
    async with get_session_factory()() as s:
        for name, doc in DOCS.items():
            summ = {}
            for sid, content in con.execute("select section_id, content from section_summaries where document_id=? order by unit_index", (doc,)):
                summ.setdefault(sid, []).append(content)
            ws = quiz_builder.windows(await quiz_builder.scope_chunks(s, doc, None))
            shown = 0
            for w in ws:
                cands = key_candidates(w.text)[:8]
                if len(cands) < 3 or w.section_id not in summ:
                    continue
                v = np.array(emb.encode([" ".join(summ[w.section_id])[:2000]] + cands), dtype=np.float32)
                sims = v[1:] @ v[0]
                best = cands[int(sims.argmax())]
                if best != cands[0]:
                    print(f"\n[{name}] LENGTH: {cands[0][:160]}\n          CENTRAL ({sims.max():.2f} vs {sims[0]:.2f}): {best[:160]}")
                    shown += 1
                if shown >= 5:
                    break

asyncio.run(main())
